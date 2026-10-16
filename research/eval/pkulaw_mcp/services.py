"""法宝 MCP 服务清单与封装。

单价取自本账号 list_entitlements（2026-10-16）；变动时用 `python -m pkulaw_mcp services --refresh` 核对。
参数名取自各服务 tools/list，不要凭文档猜。
"""
from __future__ import annotations

from dataclasses import dataclass

from .client import Gateway, PkulawError


@dataclass(frozen=True)
class Service:
    id: str
    path: str
    title: str
    points: int
    use: str


SERVICES: dict[str, Service] = {s.id: s for s in [
    Service("account", "/pkulaw-account/mcp", "查询积分余额", 0, "余额、开通状态与单价"),
    Service("enforcement-doc", "/pkulaw-enforcement-doc/mcp", "检索行政执法", 75, "行政处罚决定书目录、普查、出处定位"),
    Service("procuratorate-doc", "/pkulaw-procuratorate-doc/mcp", "检索检察文书", 75, "不起诉决定书等（行刑边界）"),
    Service("statute-history", "/pkulaw-statute-history/mcp", "法规与法条沿革", 75, "条文历次版本原文、版本对照（规范库核验、时间效力）"),
    Service("fatiao", "/mcp-fatiao", "精准查找法条-关键词", 25, "单条法条现行原文"),
    Service("law-keyword", "/mcp-law", "检索法律法规-关键词", 25, "定位法规、司法解释、部门文件、地方裁量基准"),
    Service("law-semantic", "/mcp-law-search-service", "检索法律法规-语义", 125, "按问题找法条"),
    Service("case-keyword", "/mcp-case", "检索司法案例-关键词", 25, "司法案例目录（前 20 条）"),
    Service("case-semantic", "/mcp-case-search-service", "检索司法案例-语义", 125, "类案检索对照（M5）"),
    Service("case-number", "/case_number_recognition", "案号识别与溯源", 125, "案号溯源"),
    Service("law-recognition", "/law_recognition", "法条识别与溯源", 125, "文书中的法条识别"),
    Service("doc-link", "/add-doc-link", "法宝超链", 125, "说理文本加法条超链"),
    Service("citation-validator", "/pku_citation_validator", "修正生成幻觉-法条", 125, "M6 说理法条校验（红线 R2）"),
    # 法律智能检索（mcp-law-agg，125 分）已开通，但网关路径未知（/mcp-law-agg 返回 404），暂不收录
]}


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != ""}


class Pkulaw:
    """按服务封装的调用；每个方法返回 Gateway.call 的结果（structured / text / cached）。"""

    def __init__(self, gateway: Gateway):
        self.gw = gateway

    def _call(self, service_id: str, tool: str, arguments: dict, refresh: bool = False) -> dict:
        s = SERVICES[service_id]
        return self.gw.call(s.path, tool, _drop_none(arguments), points=s.points, refresh=refresh)

    # ---- 账户（0 分，不缓存：余额要实时） ----
    def balance(self, window_days: int = 30) -> dict:
        return self._call("account", "get_points_balance", {"expiringWindowDays": window_days}, refresh=True)["structured"]

    def entitlements(self) -> dict:
        return self._call("account", "list_entitlements", {}, refresh=True)["structured"]

    # ---- 行政执法 / 检察文书（每次最多 20 条，不能翻页；结果带命中总数） ----
    def search_enforcement(self, query_text: str | None = None, *, title: str | None = None,
                           document_no: str | None = None, regions: list[str] | None = None,
                           punishment_type: str | None = None, target: list[str] | None = None,
                           enforce_type: list[str] | None = None, start: str | None = None,
                           end: str | None = None, semantic: bool = False) -> dict:
        return self._call("enforcement-doc", "search_enforcement", {
            "queryText": query_text, "title": title, "documentNo": document_no, "lawRegional": regions,
            "punishmentType": punishment_type, "punishmentTarget": target, "lawEnforceType": enforce_type,
            "startPunishmentDate": start, "endPunishmentDate": end,
            "searchType": "semantic" if semantic else "keyword"})

    def search_procuratorate(self, query_text: str | None = None, *, title: str | None = None,
                             case_no: str | None = None, category: list[str] | None = None,
                             document_attr: list[str] | None = None, start: str | None = None,
                             end: str | None = None, semantic: bool = False) -> dict:
        return self._call("procuratorate-doc", "search_procuratorate", {
            "queryText": query_text, "title": title, "caseFlag": case_no, "category": category,
            "documentAttr": document_attr, "startDate": start, "endDate": end,
            "searchType": "semantic" if semantic else "keyword"})

    # ---- 法规 ----
    def article_history(self, law_title: str, article: str, as_of: str | None = None) -> dict:
        """某条的历次版本原文（按现行条号）；一次调用同时拿到旧版对应条文。"""
        return self._call("statute-history", "get_article_history",
                          {"lawTitle": law_title, "articleNumber": str(article), "asOf": as_of})

    def law_versions(self, law_title: str) -> dict:
        return self._call("statute-history", "list_law_versions", {"lawTitle": law_title})

    def diff_article(self, law_title: str, article: str, from_version: str, to_version: str) -> dict:
        return self._call("statute-history", "diff_article_versions", {
            "lawTitle": law_title, "articleNumber": str(article),
            "fromVersion": from_version, "toVersion": to_version})

    def law_item(self, title: str, tiao_num: float) -> dict:
        """现行版单条原文。tiao_num：2 = 第二条，2.1 = 第二条之一。

        注意：标题匹配不上时，网关会返回别的文件中同号的条文而不报错（实测：公安部分项通知查"第一条"
        返回了无关通报）。调用方必须核对返回的 Title / DocumentNO。
        """
        return self._call("fatiao", "get_law_item_content", {"title": title, "tiao_num": tiao_num})

    def search_articles(self, text: str, *, lib: str | None = None, timeliness: str | None = None,
                        issue_department: str | None = None, size: int = 10) -> dict:
        """语义检索法条（125 分/次，最多 20 条）。按"一、二、"分项的部门文件取不到单条时用它。"""
        return self._call("law-semantic", "search_article", {
            "text": text, "lib": lib, "timeliness": timeliness,
            "issue_department": issue_department, "size": size})

    def law_list(self, title: str | None = None, fulltext: str | None = None, *,
                 effectiveness: list[str] | None = None, timeliness: list[str] | None = None) -> dict:
        if not (title or fulltext):
            raise PkulawError("标题关键词与正文关键词至少填一个")
        return self._call("law-keyword", "get_law_list", {
            "title": title, "fulltext": fulltext, "effectiveness": effectiveness, "timeliness": timeliness})

    # ---- 司法案例 ----
    def case_list(self, title: str | None = None, fulltext: str | None = None, *,
                  document_attr: list[str] | None = None, court: str | None = None,
                  case_class: str | None = None, start: str | None = None, end: str | None = None) -> dict:
        if not (title or fulltext):
            raise PkulawError("标题关键词与正文关键词至少填一个")
        return self._call("case-keyword", "get_case_list", {
            "title": title, "fulltext": fulltext, "documentAttr": document_attr, "court": court,
            "caseClassName": case_class, "startLastInstanceDate": start, "endLastInstanceDate": end})
