"""实务参照（RAP 无文本版，ADR-007 / ADR-009）：规则结论 + 结构化要素 → 历史上实际怎么罚的分布。

模型是标准化后的多项逻辑回归，参数由 research/eval/rule_chain/rap_export.py 导出为 JSON，
运行时只做矩阵运算，不依赖 sklearn。线性模型可精确分解：
  某类处罚的对数几率 = 基线（训练集平均案件）+ Σ 系数 × (特征值 − 训练均值) / 标准差
每一项就是该特征对该类处罚的贡献，全部输出，不做黑箱。

特征定义只在这里写一次；导出脚本训练时调用同一个函数，保证线上线下一致。
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .norm_layer import Facts

ORDER = ["不予处罚", "罚款", "拘留", "拘留并处罚款"]
MODEL_PATH = Path(__file__).parent / "data" / "rap-notext-v1.json"
NETWORK, MACHINE, LOTTERY = {"网络赌博"}, {"赌博机"}, {"私彩", "六合彩", "赌球"}
AMOUNTS = (("personal_stake", "本人赌资"), ("onsite_stake_total", "现场赌资合计"), ("commission", "抽头渔利"))


def feature_spec() -> list[dict]:
    """[{name, label, group}]，顺序即特征向量顺序。"""
    spec = []
    for t in ORDER:
        spec += [{"name": f"rule_unique_{t}", "label": f"规则唯一结论为{t}", "group": "规则结论"},
                 {"name": f"rule_candidate_{t}", "label": f"规则候选含{t}", "group": "规则结论"}]
    spec += [{"name": "rule_no_band", "label": "规则无法定档", "group": "规则结论"},
             {"name": "province_hebei", "label": "河北（相对江苏）", "group": "省份"},
             {"name": "provide_conditions", "label": "为赌博提供条件（相对参与赌博）", "group": "行为类型"},
             {"name": "method_network", "label": "网络赌博", "group": "赌博方式"},
             {"name": "method_machine", "label": "赌博机", "group": "赌博方式"},
             {"name": "method_lottery", "label": "私彩/六合彩/赌球", "group": "赌博方式"},
             {"name": "method_unknown", "label": "赌博方式未知", "group": "赌博方式"},
             {"name": "civil_servant_yes", "label": "国家工作人员", "group": "身份"},
             {"name": "civil_servant_unknown", "label": "是否国家工作人员未知", "group": "身份"},
             {"name": "venue_public_yes", "label": "公共场所/交通工具", "group": "场所"},
             {"name": "venue_public_unknown", "label": "场所未知", "group": "场所"}]
    for field, label in AMOUNTS:
        spec += [{"name": f"log_{field}", "label": f"{label}（对数）", "group": "赌资与获利"},
                 {"name": f"missing_{field}", "label": f"{label}未知", "group": "赌资与获利"}]
    spec += [{"name": "log_participants", "label": "参赌人数（对数）", "group": "参赌人数"},
             {"name": "missing_participants", "label": "参赌人数未知", "group": "参赌人数"}]
    return spec


def _tri(v):
    return (1.0, 0.0) if v is True else (0.0, 1.0) if v is None else (0.0, 0.0)


def _amount_mid(a):
    if a is None:
        return None
    d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
    lo, hi = d.get("min"), d.get("max")
    if lo is None and hi is None:
        return None
    return lo if hi is None else hi if lo is None else (lo + hi) / 2


def _venue_public(f: Facts):
    v = f.venue_type
    return None if v is None else v in ("公共场所", "交通工具")


def features(f: Facts, types: list[str], province: str) -> list[float]:
    """types = 省级定档给出的可能处罚种类（decide.band_types）；province = "130000" / "320000"。"""
    x = []
    for t in ORDER:
        x += [float(types == [t]), float(len(types) > 1 and t in types)]
    x += [float(not types), float(province == "130000"), float(f.behavior_type == "为赌博提供条件")]
    m = f.method
    x += [float(m in NETWORK), float(m in MACHINE), float(m in LOTTERY), float(m is None)]
    x += [*_tri(f.civil_servant), *_tri(_venue_public(f))]
    for field, _ in AMOUNTS:
        v = _amount_mid(getattr(f, field))
        x += [math.log10(v + 1) if v is not None else 0.0, float(v is None)]
    n = f.participant_count
    x += [math.log(n) if n else 0.0, float(not n)]
    return x


def _spec_of(m: dict) -> list[dict]:
    if m.get("feature_set") == "rule":
        from . import rule_features
        return list(rule_features.spec())
    return feature_spec()


@lru_cache(maxsize=4)
def load_model(path: str | None = None) -> dict | None:
    """feature_set = manual（v1 手工特征）或 rule（规则生成特征，ADR-011）。规则特征的名单哈希必须与当前规则一致：
    规则改了而模型没重训，返回带 stale 标记的模型，predict 不出结果（由测试在提交前拦住）。"""
    p = Path(path) if path else MODEL_PATH
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("feature_set") == "rule":
        from . import rule_features
        if m.get("spec_hash") != rule_features.spec_hash() or not set(m["features"]) <= {
                s["name"] for s in rule_features.spec()}:
            return {**m, "stale": "规则已变更、实务模型未重训，特征名单不一致"}
        return m
    if m["features"] != [s["name"] for s in feature_spec()]:
        raise RuntimeError(f"RAP 参数文件的特征与代码不一致：{p}")
    return m


def predict(f: Facts, types: list[str], province: str, model: dict | None = None) -> dict | None:
    """返回分布、基线、逐特征贡献与按组汇总；没有参数文件或模型过期时返回 None。"""
    m = model or load_model()
    if m is None or m.get("stale"):
        return None
    if m.get("feature_set") == "rule":           # 规则生成特征，可只取其中一部分（如只用规则结论）
        from . import rule_features
        full = list(rule_features.spec())
        pos = {s["name"]: i for i, s in enumerate(full)}
        xs = rule_features.features(f)
        spec = [full[pos[n]] for n in m["features"]]
        x = [xs[pos[n]] for n in m["features"]]
    else:
        spec, x = feature_spec(), features(f, types, province)
    z = [(xi - mu) / sd for xi, mu, sd in zip(x, m["mean"], m["scale"])]
    classes = m["classes"]
    contrib = {k: [w * zi for w, zi in zip(m["coef"][i], z)] for i, k in enumerate(classes)}
    logits = {k: m["intercept"][i] + sum(contrib[k]) for i, k in enumerate(classes)}
    top = max(logits.values())
    expo = {k: math.exp(v - top) for k, v in logits.items()}
    s = sum(expo.values())
    dist = {t: round(expo[t] / s, 4) if t in expo else 0.0 for t in ORDER}
    pred = max(dist, key=dist.get)
    items = []
    for j, sp in enumerate(spec):
        per = {k: round(contrib[k][j], 4) for k in classes}
        if any(abs(v) >= 1e-4 for v in per.values()):
            items.append({**sp, "value": round(x[j], 4), "train_mean": round(m["mean"][j], 4), "contribution": per})
    groups = {}
    for it in items:
        g = groups.setdefault(it["group"], {k: 0.0 for k in classes})
        for k, v in it["contribution"].items():
            g[k] += v
    # 对预测类的"相对优势"：该类对数几率减其余类的平均，按组拆开，便于一句话说明
    others = [k for k in classes if k != pred]
    margin = {g: round(v[pred] - sum(v[o] for o in others) / len(others), 4) for g, v in groups.items()} if others else {}
    return {"distribution": dist, "predicted": pred,
            "baseline_logits": {k: round(m["intercept"][i], 4) for i, k in enumerate(classes)},
            "logits": {k: round(v, 4) for k, v in logits.items()},
            "contributions": items,
            "groups": {g: {k: round(v, 4) for k, v in d.items()} for g, d in groups.items()},
            "margin_for_predicted": dict(sorted(margin.items(), key=lambda kv: -abs(kv[1]))),
            "model": {k: m[k] for k in ("version", "feature_set", "trained", "training", "evaluation", "limits") if k in m}}
