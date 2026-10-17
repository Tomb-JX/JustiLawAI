"""Check official flagship APIs with synthetic text and ephemeral credentials.

Usage: python research/qa/smoke_flagship.py deepseek qwen

Missing API keys are read from a no-echo terminal prompt. They are kept only in
this process environment and cleared before exit. No source records are sent.
"""
from __future__ import annotations

import getpass
import json
import os
import sys

from flagship_client import MODELS, call_json


def main(argv: list[str]) -> int:
    providers = argv[1:]
    if not providers or len(set(providers)) != len(providers) or any(
        provider not in MODELS for provider in providers
    ):
        print(__doc__)
        return 2
    created: list[str] = []
    try:
        for provider in providers:
            name = MODELS[provider][1]
            if not os.getenv(name):
                os.environ[name] = getpass.getpass(f"{provider} API key: ")
                created.append(name)
        failed = False
        for provider in providers:
            try:
                result = call_json(
                    provider,
                    "Reply with one JSON object and no other text.",
                    'Synthetic connectivity check. Return {"ok": true}.',
                    timeout=45,
                )
                valid = (
                    result["returned_model"] == MODELS[provider][0]
                    and result["answer"].get("ok") is True
                )
                print(json.dumps({
                    "provider": provider,
                    "requested_model": MODELS[provider][0],
                    "returned_model": result["returned_model"],
                    "status": "pass" if valid else "unexpected_response",
                }))
                failed |= not valid
            except Exception as exc:
                print(json.dumps({
                    "provider": provider,
                    "requested_model": MODELS[provider][0],
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc) if isinstance(exc, RuntimeError) else "request_failed",
                }))
                failed = True
        return 1 if failed else 0
    finally:
        for name in created:
            os.environ.pop(name, None)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
