"""Explicit provider protocol claims and secret-free execution freezing."""
from __future__ import annotations

import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from element_contract import digest

VERSION = "provider-capabilities-1"


def capability(provider, declaration=None):
    # Provider.chat implements json_object. Native schema/tool support cannot be
    # inferred from compatibility branding, and is deliberately not emulated.
    result = {"endpoint": provider.base_url, "model": provider.model, "mode": "json_object",
              "validation": "client-jsonschema", "native_schema_verified": False}
    if declaration:
        if any(declaration.get(k) != result[k] for k in ("endpoint", "model", "mode")):
            raise ValueError("unsupported_or_mismatched_provider_capability")
        if not declaration.get("review_record"):
            raise ValueError("provider_capability_requires_review_record")
        result["review_record"] = declaration["review_record"]
    return result


def freeze_execution(out: Path, order, providers, prices):
    selected = order.get("providers") or {"S1": order["provider"]}
    configured = {}
    for tag, name in selected.items():
        p = providers[name]
        if (type(p.max_tokens) is not int or p.max_tokens <= 0
                or type(p.temperature) not in (int, float) or not math.isfinite(p.temperature)):
            raise ValueError('invalid_provider_parameters')
        url = urlsplit(p.base_url)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("credential_or_query_in_provider_endpoint")
        configured[tag] = {"provider": name, **capability(p, (order.get("capabilities") or {}).get(tag)),
                           "temperature": p.temperature, "max_tokens": p.max_tokens, "timeout": p.timeout}
        price = prices.get(p.model)
        if (not price or any(type(price.get(k)) not in (int, float) or not math.isfinite(price[k]) or price[k] < 0
                             for k in ("input", "output"))):
            raise ValueError("missing_or_invalid_registered_price")
    snapshot = {"version": VERSION, "order_hash": digest(order), "providers": configured,
                "prices": {p["model"]: prices[p["model"]] for p in configured.values()}}
    path = out / "execution-manifest.json"
    if path.exists() and json.loads(path.read_text("utf-8")) != snapshot:
        raise ValueError("execution_settings_changed:新工单或价格须换批次")
    if not path.exists():
        with path.open("x", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot
