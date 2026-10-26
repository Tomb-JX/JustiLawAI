"""Compatibility boundary for observation-preserving outcome arbitration.

The legacy legal-ceiling selector and unbudgeted/truncated referee path are retired.
Historical decisions remain untouched. New CLI requires --out and defaults to plan.
"""
from __future__ import annotations

from urllib.parse import urlsplit

ARBITER_MODEL_WHITELIST = {'qwen3.8-max', 'kimi-k3', 'mimo-v2.6-pro', 'mimo-v2.6-flash'}


class IsolationError(AssertionError):
    pass


def check_isolation(provider):
    host = (urlsplit(provider.base_url).hostname or '').lower()
    if host == 'deepseek.com' or host.endswith('.deepseek.com') or provider.model not in ARBITER_MODEL_WHITELIST:
        raise IsolationError('D-002: outcome referee must be a registered non-DeepSeek provider')


def legal_anchor(field, a, b):
    """Deprecated selection API: a normative ceiling never selects observed truth."""
    return None


if __name__ == '__main__':
    from run_outcomes import main
    main()
