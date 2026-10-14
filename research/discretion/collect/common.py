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
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent.parent / "data"
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


def session() -> requests.Session:
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
    return s


_SHARED_SESSION: requests.Session | None = None


def get_with_retry(url: str, *, tries: int = 5, timeout: int = 30, **kw) -> requests.Response:
    """统一走浏览器头会话；WAF 节点规则有轮换，403 时多等几次常能过。"""
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        _SHARED_SESSION = session()
    last_exc: Exception | None = None
    for i in range(tries):
        try:
            resp = _SHARED_SESSION.get(url, timeout=timeout, **kw)
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
    """追加一行台账，返回分配的 id；同 source+sha256 已存在则原样返回其 id。"""
    rows = manifest_load()
    for r in rows:
        if r["source_url_or_ref"] == row.get("source_url_or_ref") and r["sha256"] == row.get("sha256"):
            return r["id"]
    prefix = row.get("channel") or "X"
    seq = sum(1 for r in rows if r["id"].startswith(f"{prefix}-")) + 1
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
