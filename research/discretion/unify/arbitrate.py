"""Compatibility boundary for observation-preserving outcome arbitration.

The legacy legal-ceiling selector and unbudgeted/truncated referee path are retired.
Historical decisions remain untouched. New CLI requires --out and defaults to plan.
"""
from __future__ import annotations

from urllib.parse import urlsplit

# 兜底白名单；正式来源是 $DATA/config/arbiter_models.json——换裁判模型不再需要改代码
# （审计 P1-13：改码即改实现哈希，白名单与契约冻结本不该互相锁死）。
ARBITER_MODEL_WHITELIST = {'qwen3.8-max', 'kimi-k3', 'mimo-v2.6-pro', 'mimo-v2.6-flash'}


def arbiter_whitelist():
    from s1 import data_root
    path = data_root() / "config" / "arbiter_models.json"
    if path.is_file():
        import json
        value = json.loads(path.read_text("utf-8"))
        if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value) or not value:
            raise ValueError("arbiter_models.json 须为非空字符串数组")
        return set(value)
    return set(ARBITER_MODEL_WHITELIST)


class IsolationError(AssertionError):
    pass


def check_isolation(provider):
    host = (urlsplit(provider.base_url).hostname or '').lower()
    if host == 'deepseek.com' or host.endswith('.deepseek.com') or provider.model not in arbiter_whitelist():
        raise IsolationError('D-002: outcome referee must be a registered non-DeepSeek provider')


def legal_anchor(field, a, b):
    """Deprecated selection API: a normative ceiling never selects observed truth."""
    return None


if __name__ == '__main__':
    from run_outcomes import main
    main()
