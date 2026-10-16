"""北大法宝 MCP 调用层：会话、积分预算、本地缓存、调用台账与各服务的封装。

    from pkulaw_mcp import Gateway, Pkulaw
    pk = Pkulaw(Gateway(budget=600))
    pk.article_history("治安管理处罚法", "82")

相同参数的调用只付一次积分：结果缓存在 $JUSTILAW_DATA_DIR/engine/pkulaw_mcp/cache/，
每次调用（含缓存命中）记入 ledger.csv。说明见 docs/05-research/pkulaw-mcp-enforcement.md。
"""
from .client import BudgetExceeded, Gateway, PkulawError
from .services import SERVICES, Pkulaw, Service

__all__ = ["BudgetExceeded", "Gateway", "Pkulaw", "PkulawError", "SERVICES", "Service"]
