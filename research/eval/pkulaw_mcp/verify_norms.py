"""用北大法宝原文核对规范库（门禁 G0.1 的"来源可靠"部分；法律组签字仍需另做）。

做法：
  - 治安管理处罚法：按 2025 版条号调"法条沿革"，一次同时拿到 2025 版与 2012 版对应条文；
  - 行政处罚法、法释〔2005〕3号：按条调"精准查找法条"，并核对返回的文件名与文号（网关在标题匹配
    不上时会返回别的文件的同号条文）；
  - 公安部分项通知（公通字〔2005〕30号、〔2007〕1号）：按条目内容做语义检索，只认文号相符的结果。
比较前统一全半角、引号、空白，去掉"第×条""×、"前缀。

运行：research/.venv/Scripts/python research/eval/pkulaw_mcp/verify_norms.py --budget 1200
已调用过的查询走缓存不再扣分；--offline 只用缓存复现报告。
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pkulaw_mcp import Gateway, Pkulaw, PkulawError  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
NORMS = ROOT / "justilaw-api" / "app" / "discretion" / "norms" / "national"

# 法释〔2005〕3号要取的条：第一条（聚众赌博门槛）、第八条（赌资）、第九条（娱乐活动不以赌博论处）
SPC_ARTICLES = [1, 8, 9]
SPC_TITLE = "最高人民法院、最高人民检察院关于办理赌博刑事案件具体应用法律若干问题的解释"
# 分项通知：条目 → 语义检索用语
NOTICE_QUERIES = {
    "gtz-2005-30": ("公通字〔2005〕30号", {
        "6": "赌博违法案件 赌资 个人投注的财物数额无法确定时 参赌财物总额 参赌人数",
        "9": "不以营利为目的 亲属之间 带有少量财物输赢 打麻将 玩扑克 娱乐活动 不予处罚",
        "赌资较大": "赌博违法案件 赌资较大 数额标准 由省级公安机关 结合本地实际 确定",
    }),
    "gtz-2007-1": ("公通字〔2007〕1号", {
        "4": "违反治安管理行为人 减轻处罚情节 法定处罚种类只有一种 幅度以下 拘留并处罚款 单独或者同时减轻",
        "5": "治安管理处罚法第二十一条第二项 初次违反治安管理 第一次被公安机关发现或者查处",
    }),
}


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = re.sub(r"^第[一二三四五六七八九十百零〇两]+条(之[一二三四五六七八九十]+)?", "", t)
    t = re.sub(r"^[一二三四五六七八九十]+、", "", t)
    t = re.sub(r"\s+", "", t)
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"), ("＜", "<"), ("＞", ">")):
        t = t.replace(a, b)
    return t


def doc_no(text: str) -> str:
    return re.sub(r"[\[\]〔〕［］()（）\s]", "", unicodedata.normalize("NFKC", text or ""))


def compare(ours: str | None, theirs: str | None) -> dict:
    if theirs is None:
        return {"result": "法宝未取到"}
    if ours is None:
        return {"result": "规范库未录入", "pkulaw_text": theirs}
    a, b = norm(ours), norm(theirs)
    if a == b:
        return {"result": "一致"}
    diff = [f"{op} 库[{a[i1:i2]}] 法宝[{b[j1:j2]}]" for op, i1, i2, j1, j2 in
            difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op != "equal"]
    return {"result": "不一致", "diff": diff[:10], "pkulaw_text": theirs}


def check_psal(pk: Pkulaw, psal25: dict, psal12: dict) -> list[dict]:
    rows = []
    for art in psal25["articles"]:
        h = pk.article_history("治安管理处罚法", art)["structured"]
        by_version = {e["versionRef"]: e for e in h["timeline"]}
        e25 = by_version.get("2025修订")
        if e25:
            rows.append({"law": "psal-2025", "article": art, "pkulaw_url": e25["citation"]["url"],
                         **compare(psal25["articles"][art], e25["text"])})
        else:  # 新增条文没有沿革快照（实测第二十一条），改取现行原文
            rows.append(check_law_item(pk, "psal-2025", "治安管理处罚法", None, "治安管理处罚法(2025修订)",
                                       int(art), psal25["articles"][art]))
        e12 = by_version.get("2012修正")
        if e12:
            art12 = str(int(float(e12["articleNumber"])))
            rows.append({"law": "psal-2012", "article": art12, "maps_to_2025": art,
                         "pkulaw_url": e12["citation"]["url"], "change_2012_to_2025": e25 and e25["changeTypeChinese"],
                         **compare(psal12["articles"].get(art12), e12["text"])})
    covered = {r["article"] for r in rows if r["law"] == "psal-2012"}
    rows += [{"law": "psal-2012", "article": a, "result": "未覆盖（2025 版无对应条）"}
             for a in psal12["articles"] if a not in covered]
    # 2025 版第一百四十四条（施行日期）对应的 2012 版第一百一十九条是旧法施行日期，引擎不需要
    return [r for r in rows if not (r["law"] == "psal-2012" and r.get("maps_to_2025") == "144")]


def check_law_item(pk: Pkulaw, law_id: str, title: str, expect_doc_no: str | None, expect_title: str,
                   article: int, ours: str | None) -> dict:
    data = (pk.law_item(title, article)["structured"] or {}).get("Data") or {}
    title_ok = expect_title in (data.get("Title") or "")
    no_ok = expect_doc_no is None or doc_no(expect_doc_no) == doc_no(data.get("DocumentNO") or "")
    if not (title_ok and no_ok):
        return {"law": law_id, "article": str(article), "result": "法宝返回了别的文件",
                "returned": f"{data.get('Title')} {data.get('DocumentNO')}"}
    url = re.search(r"\((https?://[^)]+)\)", data.get("Url") or "")
    return {"law": law_id, "article": str(article), "pkulaw_url": url and url.group(1),
            **compare(ours, data.get("FullText"))}


def check_notice(pk: Pkulaw, doc_id: str, number: str, items: dict, docs: dict) -> list[dict]:
    rows = []
    ours = (docs.get(doc_id) or {}).get("articles") or {}
    for item, query in items.items():
        res = pk.search_articles(query, issue_department="公安部", size=20)["structured"] or {}
        hit = next((r for r in res.get("result") or []
                    if doc_no(r.get("doc_no")) == doc_no(number) and r.get("article")), None)
        if not hit:
            rows.append({"law": doc_id, "article": item, "result": "法宝未取到"})
            continue
        got = re.match(r"^([一二三四五六七八九十]+)、(关于[^\n]*问题\n)?", hit["article"])
        label = got and got.group(1)
        heading = got and got.group(2) and got.group(2).strip()
        body = hit["article"][got.end():] if got else hit["article"]  # 小标题单独记，不算正文
        rows.append({"law": doc_id, "article": item, "pkulaw_item": label, "heading": heading,
                     "pkulaw_url": hit.get("url"), **compare(ours.get(item), body)})
    return rows


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=0)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    pk = Pkulaw(Gateway(budget=a.budget, offline=a.offline))

    load = lambda name: yaml.safe_load((NORMS / name).read_text("utf-8"))  # noqa: E731
    psal25, psal12, apl = load("psal-2025.yaml"), load("psal-2012.yaml"), load("apl-2021.yaml")
    interp = load("interpretations.yaml")
    docs = {d["doc_id"]: {**d, "articles": {str(k): v for k, v in (d.get("articles") or {}).items()}}
            for d in interp["documents"]}

    rows: list[dict] = []
    try:
        rows += check_psal(pk, psal25, psal12)
        rows.append(check_law_item(pk, "apl-2021", "行政处罚法", None, "行政处罚法(2021修订)", 37,
                                   apl["articles"].get("37")))
        spc = docs["spc-spp-2005-gambling"]["articles"]
        rows += [check_law_item(pk, "spc-spp-2005-gambling", SPC_TITLE, "法释〔2005〕3号", SPC_TITLE, n,
                                spc.get(str(n))) for n in SPC_ARTICLES]
        for doc_id, (number, items) in NOTICE_QUERIES.items():
            rows += check_notice(pk, doc_id, number, items, docs)
    except PkulawError as e:
        print("中止：", e)

    out = pk.gw.data_dir / "norm_check"
    out.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": time.strftime("%Y-%m-%d"), "spent": pk.gw.spent, "rows": rows}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    for r in rows:
        extra = "；".join(r.get("diff", [])) or r.get("returned", "")
        print(f"{r['law']:<24} {r['article']:<6} {r['result']:<10} {extra[:160]}")
    print(f"\n本次花费 {pk.gw.spent} 分；报告 {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
