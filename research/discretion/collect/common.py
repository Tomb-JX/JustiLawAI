"""裁量引擎数据采集公共库：路径约定、礼貌 HTTP、SHA-256、manifest 台账。

路径约定（引擎方案 §7 + 数据收集计划 §6）：
  research/data/                  运行时数据区（.gitignore 整体排除，永不入库）
  research/discretion/collect/    采集脚本（入库）
  manifest.csv                    本目录下的数据来源台账（入库；只登记来源与哈希，不含正文）

台账纪律：每批采集 = 每行记录，字段见 MANIFEST_FIELDS；同一来源 + 同一哈希不重复登记。
"""

from __future__ import annotations

import csv
import hashlib
import os
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
# 数据目录在仓库之外（分工文档 workstreams.md §3）：默认 D:/02_Dev/Data/justilaw-research，
# 可用环境变量 JUSTILAW_DATA_DIR 覆盖；引擎侧只读此目录，中间产物写 <DATA_DIR>/engine/。
DATA_DIR = Path(os.environ.get("JUSTILAW_DATA_DIR", "D:/02_Dev/Data/justilaw-research"))
RAW_DIR = DATA_DIR / "raw"
MANIFEST = HERE / "manifest.csv"

MANIFEST_FIELDS = [
    "id",              # 渠道代号-序号，如 D-001 / B-001
    "channel",         # A 公安合作 / B 复议 / C 诉讼 / D 公开数据集 / E 公开公示 / F 合成 / manual 手动导入
    "source_type",     # 数据集 / 复议决定书 / 判决书 / 处罚决定 / 规范文件 / …
    "source_url_or_ref",  # 来源 URL 或文号
    "region",
    "behavior_date",
    "decision_date",
    "law_version",
    "title",
    "sha256",
    "harvest_date",
    "harvest_by",
    "status",          # 待筛选 / 纳入 / 排除
    "notes",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
GOV_DELAY_S = 2.0  # 对政府站点的礼貌间隔


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# 部分政府站点（深圳 sf.sz.gov.cn 等）服务端 ECC 握手不兼容 Python OpenSSL（BAD_ECPOINT），
# 改用纯 RSA 密钥交换套件即可握手（curl 可通、Python 报错的站都先试这组）
NO_EC_CIPHERS = "AES128-GCM-SHA256:AES256-GCM-SHA384:AES128-SHA:AES256-SHA"


def session(ciphers: str | None = None) -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕过环境代理：政府站点国内直连，避免代理出口被 403
    # 政府站点 WAF（东城等）按请求头概率拦截：头集越接近浏览器越稳（详见 collect/README 已知坑）
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,zh-TW;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    if ciphers:
        import ssl

        from requests.adapters import HTTPAdapter
        from urllib3.util.ssl_ import create_urllib3_context

        class _CipherAdapter(HTTPAdapter):
            def init_poolmanager(self, *a, **kw):
                kw["ssl_context"] = create_urllib3_context(ciphers=ciphers, cert_reqs=ssl.CERT_NONE)
                return super().init_poolmanager(*a, **kw)

        s.mount("https://", _CipherAdapter())
    return s


_SHARED_SESSION: requests.Session | None = None


def get_with_retry(url: str, *, tries: int = 5, timeout: int = 30, sess: requests.Session | None = None, **kw) -> requests.Response:
    """统一走浏览器头会话；WAF 节点规则有轮换，403 时多等几次常能过。TLS 兼容站传 sess。"""
    global _SHARED_SESSION
    if sess is None and _SHARED_SESSION is None:
        _SHARED_SESSION = session()
    s = sess or _SHARED_SESSION
    last_exc: Exception | None = None
    for i in range(tries):
        try:
            resp = s.get(url, timeout=timeout, **kw)
            resp.raise_for_status()
            return resp
        except Exception as e:  # noqa: BLE001 - 记录最后一次异常后重试
            last_exc = e
            time.sleep(2**i + 1)
    raise RuntimeError(f"下载失败（{tries} 次）：{url}") from last_exc


def manifest_load() -> list[dict]:
    if not MANIFEST.exists():
        return []
    with open(MANIFEST, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def manifest_add(row: dict) -> str:
    """追加一行台账，返回分配的 id；同渠道同来源 URL 已存在则原样返回其 id。

    去重按 (channel, source_url_or_ref)：同一 URL 两次抓到的正文字节可能有微差
    （页面动态内容），按哈希去重会造成重复登记。字段值清洗换行防 CSV 断行。
    """
    for k, v in list(row.items()):
        if isinstance(v, str):
            row[k] = v.replace("\r", " ").replace("\n", " ").strip()
    rows = manifest_load()
    for r in rows:
        if (
            r["channel"] == row.get("channel")
            and r["source_url_or_ref"] == row.get("source_url_or_ref")
        ):
            return r["id"]
    prefix = row.get("channel") or "X"
    # 序号取同前缀已有最大值 +1：按行数计数在台账经历删行重建后会与旧号冲突（B-098 事故）
    used = [int(r["id"][len(prefix) + 1:]) for r in rows
            if r["id"].startswith(f"{prefix}-") and r["id"][len(prefix) + 1:].isdigit()]
    seq = max(used, default=0) + 1
    row["id"] = f"{prefix}-{seq:03d}"
    row.setdefault("harvest_date", datetime.now().strftime("%Y-%m-%d"))
    row.setdefault("harvest_by", "collect-script")
    row.setdefault("status", "待筛选")
    for k in MANIFEST_FIELDS:
        row.setdefault(k, "")
    with open(MANIFEST, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        if f.tell() == 0:
            w.writeheader()
        w.writerow(row)
    return row["id"]


def report(msg: str) -> None:
    print(msg, flush=True)


# ---------- 数据登记表（项目现状总览 §6：构建/导入脚本自动追加一行，文档只引版本号） ----------

REGISTRY = DATA_DIR / "REGISTRY.csv"
REGISTRY_FIELDS = ["layer", "path", "records", "sha256", "producer", "pipeline_version",
                   "created_at", "status", "note"]


def dir_digest(path: Path) -> str:
    """目录内容摘要：按文件名排序的「相对路径 + 文件 SHA-256」串接后取 SHA-256。

    对文件返回自身哈希；目录含清单与各文件哈希，任一文件改动都会改变摘要。
    """
    p = Path(path)
    if p.is_file():
        return sha256_path(p)
    lines = []
    for f in sorted(p.rglob("*")):
        if f.is_file() and ".bak" not in f.suffixes:
            lines.append(f"{f.relative_to(p).as_posix()}\t{sha256_path(f)}")
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def registry_add(layer: str, path, *, records: int, producer: str,
                 pipeline_version: str = "", status: str = "现行", note: str = "") -> None:
    """向 $JUSTILAW_DATA_DIR/REGISTRY.csv 追加一行（文件不存在则写表头）。

    layer 对齐总览 §4 分层：L0 原始 / L1 解析（parsed-1）/ L1-legacy（工作副本）等；
    status：现行 / 已取代 / 工作副本。临时目录（测试等）不登记。
    """
    sp = str(path)
    import tempfile
    if "pytest-of-" in sp or sp.startswith(tempfile.gettempdir()):
        return
    row = {
        "layer": layer, "path": str(path), "records": records,
        "sha256": dir_digest(Path(path)), "producer": producer,
        "pipeline_version": pipeline_version,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": status, "note": note,
    }
    # 同路径旧行一律标"已取代"（每个路径只保留最后一个版本为现值）
    rows: list[dict] = []
    if REGISTRY.exists():
        with REGISTRY.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("path") == row["path"] and r.get("status") != "已取代":
                    r["status"] = "已取代"
                rows.append(r)
    rows.append(row)
    tmp = REGISTRY.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(REGISTRY)
