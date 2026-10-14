"""渠道 B 站点批量探查：找出各省司法厅 / 地市政府的「行政复议决定」公开专栏。

对一批首页做浅抓取，提取含「复议」的链接；命中后人工（或再跑一轮）钻取确认列表结构。
只读公开首页，1.5s 礼貌间隔，单站超时 12s，失败不阻断。

用法：python probe_sites.py [--group prov|city|all]
"""

from __future__ import annotations

import argparse
import re
import time
from urllib.parse import urljoin

from common import report, session

PROV = {
    "北京": "https://sfj.beijing.gov.cn/",
    "天津": "https://sfj.tj.gov.cn/",
    "河北": "https://sft.hebei.gov.cn/",
    "山西": "https://sft.shanxi.gov.cn/",
    "内蒙古": "https://sft.nmg.gov.cn/",
    "辽宁": "https://sft.ln.gov.cn/",
    "吉林": "https://sft.jl.gov.cn/",
    "黑龙江": "https://sft.hlj.gov.cn/",
    "上海": "https://sfj.sh.gov.cn/",
    "江苏": "https://sft.jiangsu.gov.cn/",
    "安徽": "https://sft.ah.gov.cn/",
    "福建": "https://sft.fujian.gov.cn/",
    "江西": "https://sft.jiangxi.gov.cn/",
    "山东": "https://sft.shandong.gov.cn/",
    "河南": "https://sft.henan.gov.cn/",
    "湖北": "https://sft.hubei.gov.cn/",
    "湖南": "https://sft.hunan.gov.cn/",
    "广东": "https://sft.gd.gov.cn/",
    "广西": "https://sft.gxzf.gov.cn/",
    "海南": "https://sft.hainan.gov.cn/",
    "重庆": "https://sfj.cq.gov.cn/",
    "四川": "https://sft.sc.gov.cn/",
    "贵州": "https://sft.guizhou.gov.cn/",
    "云南": "https://sft.yn.gov.cn/",
    "陕西": "https://sft.shaanxi.gov.cn/",
    "甘肃": "https://sft.gansu.gov.cn/",
    "青海": "https://sft.qinghai.gov.cn/",
    "宁夏": "https://sft.nx.gov.cn/",
    "新疆": "https://sft.xinjiang.gov.cn/",
}

# 复议机关通常是市/县政府——治安处罚复议决定多在市级专栏
CITY = {
    "杭州": "https://www.hangzhou.gov.cn/",
    "宁波": "https://www.ningbo.gov.cn/",
    "温州": "https://www.wenzhou.gov.cn/",
    "长沙": "https://www.changsha.gov.cn/",
    "太原": "https://www.taiyuan.gov.cn/",
    "昆明": "https://www.km.gov.cn/",
    "合肥": "https://www.hefei.gov.cn/",
    "南京": "https://www.nanjing.gov.cn/",
    "苏州": "https://www.suzhou.gov.cn/",
    "深圳": "https://www.sz.gov.cn/",
    "广州": "https://www.gz.gov.cn/",
    "成都": "https://www.chengdu.gov.cn/",
    "武汉": "https://www.wuhan.gov.cn/",
    "郑州": "https://www.zhengzhou.gov.cn/",
    "济南": "https://www.jinan.gov.cn/",
    "青岛": "https://www.qingdao.gov.cn/",
}

LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{0,60}?复议[^<]{0,40})</a>', re.I)
ALT_RE = re.compile(r'href="([^"]+)"[^>]+title="([^"]{0,60}?复议[^"]{0,40})"')


def probe(name: str, url: str) -> tuple[int, list[tuple[str, str]]]:
    """返回 (状态, [(绝对URL, 链接文字)])；只保留指向本站、含复议的链接。"""
    s = session()
    try:
        r = s.get(url, timeout=12, verify=False)
    except Exception:
        try:
            r = s.get(url.replace("https://", "http://"), timeout=12, verify=False)
        except Exception as e:  # noqa: BLE001
            report(f"{name}: ❌ {type(e).__name__} {str(e)[:60]}")
            return 0, []
    if r.status_code != 200 or not r.text:
        report(f"{name}: ⚠️ HTTP {r.status_code}, len={len(r.text)}")
        return r.status_code, []
    host = re.match(r"https?://([^/]+)/", url).group(1)
    hits: dict[str, str] = {}
    for pat in (LINK_RE, ALT_RE):
        for href, text in pat.findall(r.text):
            if not text.strip():
                continue
            full = urljoin(str(r.url), href)
            if host not in full and "gov.cn" not in full:
                continue
            # 只要"决定/案件/公开/结果/文书/信息"语义的，过滤纯新闻
            if re.search(r"决定|案件|公开|结果|文书|专栏|平台", text):
                hits.setdefault(full, text.strip())
    mark = "✅" if hits else "—"
    report(f"{name}: {mark} HTTP {r.status_code} len={len(r.text)} 复议语义链接 {len(hits)}")
    for u, t in list(hits.items())[:3]:
        report(f"    [{t[:36]}] {u[:100]}")
    return r.status_code, list(hits.items())


def main() -> None:
    import urllib3

    urllib3.disable_warnings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="all", choices=["prov", "city", "all"])
    ap.add_argument("--only", default="", help="只探查名字含此子串的站点")
    args = ap.parse_args()

    targets: dict[str, str] = {}
    if args.group in ("prov", "all"):
        targets.update(PROV)
    if args.group in ("city", "all"):
        targets.update(CITY)
    if args.only:
        targets = {k: v for k, v in targets.items() if args.only in k}
    report(f"探查 {len(targets)} 个站点 ...\n")
    for name, url in targets.items():
        probe(name, url)
        time.sleep(1.5)


if __name__ == "__main__":
    main()
