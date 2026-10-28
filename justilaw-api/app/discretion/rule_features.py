"""规则生成的实务模型特征（ADR-010 决定 5、ADR-011 决定 3）。

特征名单不手工挑选，而是从规则声明枚举：
- 规则结论：唯一种类 / 候选成员 / 无法定档（× 四种处罚）；省份；
- 每省每类行为的每个计量（rules.<行为>.measures）：档位下界、档位上界、档内位置 log10(值 / 本档下限)、是否缺失，
  以及取值来源（measures[].sources 的每一项，如累计 / 单次 / 人均）；
- 每个分类（categories）：落在哪类门槛；
- 每个升档条件（elevate）、提示条件（floor_hint）：成立 / 未知；
- 国家法修正情节：每个触发项（norm_layer.TRIGGERS 与年龄规则）是否触发。
值从一次 assess 的计算过程（stake_threshold.computation、assessment.directions）读出，不另行计算。
规则改了，名单随之改；参数文件存名单哈希，加载时校验。
"""
from __future__ import annotations

import hashlib
import json
import math

from .decide import band_types
from .norm_layer import TRIGGERS, Facts, assess
from .norm_store import NormLibrary, load

ORDER = ["不予处罚", "罚款", "拘留", "拘留并处罚款"]
AGE_TRIGGERS = ["已满十四周岁不满十八周岁", "不满十四周岁"]


def spec(lib: NormLibrary | None = None) -> tuple[dict, ...]:
    """[{name, label, group}]，顺序即向量顺序。"""
    lib = lib or load()
    out = []
    for t in ORDER:
        out += [{"name": f"rule:unique:{t}", "label": f"规则唯一结论为{t}", "group": "规则结论"},
                {"name": f"rule:candidate:{t}", "label": f"规则候选含{t}", "group": "规则结论"}]
    out.append({"name": "rule:none", "label": "规则无法定档", "group": "规则结论"})
    for code, prov in sorted(lib.provinces.items()):
        out.append({"name": f"prov:{code}", "label": prov.get("name", code), "group": "省份"})
        for bt, rule in (prov.get("rules") or {}).items():
            key = f"{code}:{bt}"
            for m in rule.get("measures") or []:
                base, lab = f"{key}:measure:{m['field']}", m.get("label") or m["field"]
                out += [{"name": f"{base}:band_lo", "label": f"{lab}档位下界", "group": "计量"},
                        {"name": f"{base}:band_hi", "label": f"{lab}档位上界", "group": "计量"},
                        {"name": f"{base}:position", "label": f"{lab}档内位置（对数）", "group": "计量"},
                        {"name": f"{base}:missing", "label": f"{lab}未知", "group": "计量"}]
                for s in m.get("sources") or []:
                    out.append({"name": f"{base}:source:{s['use']}", "label": f"取值来源：{s['label']}", "group": "计量"})
                for c in m.get("categories") or []:
                    out.append({"name": f"{base}:category:{c['id']}", "label": f"门槛类别：{c.get('label', c['id'])}",
                                "group": "计量"})
            for kind in ("elevate", "floor_hint"):
                for e in rule.get(kind) or []:
                    n = f"{key}:{kind}:{e['when']}"
                    out += [{"name": f"{n}:true", "label": f"{e['text']}（成立）", "group": "升档与提示"},
                            {"name": f"{n}:unknown", "label": f"{e['text']}（未知）", "group": "升档与提示"}]
    for trig in [*TRIGGERS, *AGE_TRIGGERS]:
        out.append({"name": f"nat:{trig}", "label": f"国家法修正情节：{trig}", "group": "法定修正情节"})
    return tuple(out)


def spec_hash(lib: NormLibrary | None = None) -> str:
    return hashlib.sha256(json.dumps([s["name"] for s in spec(lib=lib)], ensure_ascii=False).encode()).hexdigest()


def _mid(v):
    a, b = v
    return a if b is None else (a + b) / 2


def features(f: Facts, lib: NormLibrary | None = None) -> list[float]:
    lib = lib or load()
    names = [s["name"] for s in spec(lib=lib)]
    idx = {n: i for i, n in enumerate(names)}
    x = [0.0] * len(names)

    def put(name, value=1.0):
        if name in idx:
            x[idx[name]] = value

    a = assess(f, lib)
    st = a.stake_threshold
    types = band_types(st)
    for t in ORDER:
        put(f"rule:unique:{t}", float(types == [t]))
        put(f"rule:candidate:{t}", float(len(types) > 1 and t in types))
    put("rule:none", float(not types))
    code = (f.region or "")[:2] + "0000"
    put(f"prov:{code}")
    prov = lib.provinces.get(code) or {}
    rule = (prov.get("rules") or {}).get(f.behavior_type or "") or {}
    key = f"{code}:{f.behavior_type}"
    measures = {m["field"]: m for m in rule.get("measures") or []}
    seen = set()
    for c in st.get("computation") or []:
        if c.get("step") == "measure":
            base = f"{key}:measure:{c['field']}"
            seen.add(c["field"])
            if c.get("value") is None:
                put(f"{base}:missing")
                continue
            bands = c.get("result") or [0]
            put(f"{base}:band_lo", float(min(bands)))
            put(f"{base}:band_hi", float(max(bands)))
            th = (c.get("thresholds") or [{}])
            if len(th) == 1 and len(bands) == 1:
                bounds, k = th[0].get("lower_bounds") or [], bands[0]
                ref = bounds[k - 1] if k >= 1 else (bounds[0] if bounds else None)
                v = _mid(c["value"])
                if ref and v and v > 0:
                    put(f"{base}:position", math.log10(v / ref))
                if th[0].get("category"):
                    put(f"{base}:category:{th[0]['category']}")
            for s in measures.get(c["field"], {}).get("sources") or []:
                if c.get("basis_of_value") == s.get("label"):
                    put(f"{base}:source:{s['use']}")
        elif c.get("step") == "elevate":
            put(f"{key}:elevate:{c['condition']}:true")
    for fld in measures:
        if fld not in seen:
            put(f"{key}:measure:{fld}:missing")
    unknown = set(st.get("unknown_conditions") or [])
    for kind in ("elevate", "floor_hint"):
        for e in rule.get(kind) or []:
            if e["when"] in unknown:
                put(f"{key}:{kind}:{e['when']}:unknown")
    notes = " ".join(st.get("notes") or [])
    for e in rule.get("floor_hint") or []:
        if e["text"] in notes:
            put(f"{key}:floor_hint:{e['when']}:true")
    for d in a.directions:
        put(f"nat:{d.trigger}")
    return x
