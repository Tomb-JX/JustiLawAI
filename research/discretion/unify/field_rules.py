"""Read engine definitions, preserve all K fields, resolve only approved aliases."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from element_contract import digest

VERSION = "field-registry-1"


def field_catalog(engine):
    from app.discretion.schema import KEY_FIELDS
    path = Path(engine.__file__).resolve().parents[3] / "research/eval/key_field_presence.py"
    markers, marker_hash = {}, None
    if path.is_file():
        spec = importlib.util.spec_from_file_location("_engine_presence_rules", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        markers = module.MARKERS
        marker_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    schema = engine.teacher_output_schema()
    fields = {}
    for name, (description, _) in engine.FIELD_INFO.items():
        g, n = name.split(".")
        value_schema = schema["properties"][g]["properties"][n]["properties"]["value"]
        fields[name] = {"description": description, "value_schema": value_schema,
                        "key_field": name in KEY_FIELDS, "candidate_marker": markers.get(name),
                        "marker_is_semantic_truth": False}
    if not set(KEY_FIELDS) <= fields.keys():
        raise ValueError("engine_K_fields_not_preserved")
    result = {"version": VERSION, "engine_schema_version": engine.SCHEMA_VERSION,
              "fields": fields, "key_fields": list(KEY_FIELDS), "marker_source_sha256": marker_hash}
    return {**result, "hash": digest(result)}


def resolve_enum(path, raw, catalog, *, alias_pack=None):
    schema = catalog["fields"][path]["value_schema"]
    enums = next((s["enum"] for s in schema.get("anyOf", []) if "enum" in s), None)
    if enums is None:
        raise ValueError("not_an_enum_field")
    if raw in enums:
        return {"status": "resolved", "value": raw, "rule": "engine-exact-value"}
    if alias_pack:
        if (not alias_pack.get("approved_by") or not alias_pack.get("version")
                or alias_pack.get("catalog_hash") != catalog["hash"]):
            raise ValueError("alias_pack_not_approved_for_catalog")
        candidate = alias_pack.get("aliases", {}).get(path, {}).get(raw)
        if candidate in enums:
            return {"status": "resolved", "value": candidate, "rule": alias_pack["version"]}
        if candidate is not None:
            raise ValueError("alias_maps_outside_engine_enum")
    return {"status": "unresolved", "value": None, "reason": "no_exact_approved_alias"}
