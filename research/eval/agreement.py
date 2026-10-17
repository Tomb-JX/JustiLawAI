"""标注一致性（门禁 G0.3 试标、G1.2 双人标注的唯一实现）。

各线算一致性都调用这里，不再各写一份。口径改动等同于改门禁，须登记偏离日志。

三种口径（同一字段、同一批记录）：
- **union（门禁口径，D-001）**：只在至少一方给出非"未提及"的记录上算。"未提及"作为一个取值参与比较，
  所以一方有值、一方"未提及"算不一致。双方都"未提及"的记录不计入——否则抽头、前科这类大多没写的字段
  会把一致率抬虚。
- all（对照）：全部记录，双方都"未提及"算一致。数字通常最高，**不能用于判定门禁**。
- valued（对照）：只在双方都有值的记录上算，只看"值是否一样"，看不出"一方漏标"。

另报"未提及"一致率：至少一方"未提及"的记录里，双方都"未提及"的比例。

判定（G0.3）：关键字段集（schema.KEY_FIELDS）中——
- 分类字段（枚举、是否）：各字段 union 口径 κ 的平均值 ≥ 0.80。union 下配对少于 MIN_PAIRS 的字段、
  κ 无定义的字段（双方只用了同一个取值）不进平均，单独列出；
- 数值字段（金额、人数、日期、年龄）：union 口径下所有配对合在一起的完全一致率 ≥ 0.95。
  金额 min、max 都相同才算一致，开口上界（空）只与开口一致。

标注文件格式（JSONL，每行一件）：{"id": ..., "fields": {"conduct.role": {"value", "status", "evidence"}, ...}}；
也接受按 schema 分组嵌套的写法 {"id": ..., "conduct": {"role": {...}}}。

用法：research/.venv/Scripts/python research/eval/agreement.py A.jsonl B.jsonl [--out 目录] [--names A名 B名]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from enum import Enum
from pathlib import Path
from typing import get_args

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "justilaw-api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.discretion.schema import GROUPS, KEY_FIELDS, AmountRange, iter_fields  # noqa: E402
import metrics as m  # noqa: E402

ABSENT = "未提及"
NONE_LABEL = "∅"
KAPPA_MIN, NUMERIC_MIN, MIN_PAIRS = 0.80, 0.95, 5
CHECKER_VERSION = "agreement-1.0"


def _inner(typ):
    return get_args(typ)[0] if get_args(typ) else typ


FIELD_KIND = {}
for _path, _, _typ in iter_fields():
    t = _inner(_typ)
    FIELD_KIND[_path] = "categorical" if t is bool or (isinstance(t, type) and issubclass(t, Enum)) else "numeric"
FIELD_TYPE = {p: _inner(t) for p, _, t in iter_fields()}


def normalize(path: str, value):
    """取值规范化：金额 → (min, max|None)；日期 → 'YYYY-MM-DD'；数值统一成 float 比较；枚举、是否原样。"""
    if value is None:
        return None
    typ = FIELD_TYPE.get(path)
    if typ is AmountRange:
        if isinstance(value, dict):
            lo, hi = value.get("min"), value.get("max")
        else:
            lo, hi = value
        return (round(float(lo), 6), None if hi is None else round(float(hi), 6))
    if typ is date:
        return str(value)[:10]
    if typ in (int, float):
        return round(float(value), 6)
    if isinstance(value, Enum):
        return value.value
    return value


def flatten(rec: dict) -> dict:
    """{"fields": {...}} 或按组嵌套 → {路径: {"status", "value"}}。"""
    if isinstance(rec.get("fields"), dict):
        return rec["fields"]
    out = {}
    for g in GROUPS:
        for name, f in (rec.get(g) or {}).items():
            out[f"{g}.{name}"] = f
    return out


def load(path: Path) -> dict[str, dict]:
    rows = {}
    for line in Path(path).read_text("utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[str(r["id"])] = flatten(r)
    return rows


def _label(fields: dict, path: str):
    f = fields.get(path) or {}
    if f.get("status", ABSENT) == ABSENT or f.get("value") is None:
        return None
    return normalize(path, f["value"])


def field_agreement(a: dict[str, dict], b: dict[str, dict], path: str, ids: list[str]) -> dict:
    pairs = [(_label(a[i], path), _label(b[i], path)) for i in ids]
    union = [(x, y) for x, y in pairs if not (x is None and y is None)]
    valued = [(x, y) for x, y in pairs if x is not None and y is not None]
    one_absent = [(x, y) for x, y in pairs if x is None or y is None]
    kind = FIELD_KIND[path]
    out = {"field": path, "kind": kind, "key": path in KEY_FIELDS, "n_all": len(pairs), "n_union": len(union),
           "n_valued": len(valued),
           "absent_agreement": (sum(x is None and y is None for x, y in one_absent) / len(one_absent))
           if one_absent else None,
           "disagreements": [i for i, (x, y) in zip(ids, pairs) if x != y]}

    def rate(ps):
        return sum(x == y for x, y in ps) / len(ps) if ps else None

    def kappa(ps):
        return m.cohen_kappa([NONE_LABEL if x is None else str(x) for x, _ in ps],
                             [NONE_LABEL if y is None else str(y) for _, y in ps]) if ps else None

    for name, ps in (("union", union), ("all", pairs), ("valued", valued)):
        out[f"agree_{name}"] = rate(ps)
        if kind == "categorical":
            out[f"kappa_{name}"] = kappa(ps)
    return out


def agreement(a: dict[str, dict], b: dict[str, dict], fields: list[str] | None = None) -> dict:
    ids = sorted(set(a) & set(b))
    fields = fields or list(FIELD_KIND)
    per_field = [field_agreement(a, b, p, ids) for p in fields]
    key_cat = [f for f in per_field if f["key"] and f["kind"] == "categorical"]
    used = [f for f in key_cat if f["n_union"] >= MIN_PAIRS and f["kappa_union"] is not None]
    excluded = [{"field": f["field"], "n_union": f["n_union"],
                 "reason": "配对少于 %d" % MIN_PAIRS if f["n_union"] < MIN_PAIRS else "κ 无定义（只出现一个取值）",
                 "agree_union": f["agree_union"]} for f in key_cat if f not in used]
    mean_kappa = sum(f["kappa_union"] for f in used) / len(used) if used else None
    key_num = [f for f in per_field if f["key"] and f["kind"] == "numeric"]
    n_num = sum(f["n_union"] for f in key_num)
    hit_num = sum(round((f["agree_union"] or 0) * f["n_union"]) for f in key_num)
    numeric_rate = hit_num / n_num if n_num else None
    gate = {
        "basis": "union（至少一方非'未提及'），D-001 / 门禁 G0.3",
        "key_categorical_mean_kappa": mean_kappa, "key_categorical_fields_used": [f["field"] for f in used],
        "key_categorical_excluded": excluded,
        "key_numeric_exact_rate": numeric_rate, "key_numeric_pairs": n_num,
        "threshold_kappa": KAPPA_MIN, "threshold_numeric": NUMERIC_MIN,
        "pass": mean_kappa is not None and numeric_rate is not None
                and mean_kappa >= KAPPA_MIN and numeric_rate >= NUMERIC_MIN,
    }
    # 对照口径：同样的字段集，换口径算一遍，只用于说明"口径差多少"，不判定
    contrast = {}
    for name in ("all", "valued"):
        ks = [f[f"kappa_{name}"] for f in key_cat if f[f"kappa_{name}"] is not None]
        ns = [(f[f"agree_{name}"], f[f"n_{name}"]) for f in key_num if f[f"agree_{name}"] is not None]
        contrast[name] = {"key_categorical_mean_kappa": sum(ks) / len(ks) if ks else None,
                          "key_numeric_exact_rate": (sum(r * n for r, n in ns) / sum(n for _, n in ns))
                          if ns and sum(n for _, n in ns) else None}
    return {"checker": CHECKER_VERSION, "records_a": len(a), "records_b": len(b), "records_common": len(ids),
            "only_in_a": sorted(set(a) - set(b)), "only_in_b": sorted(set(b) - set(a)),
            "gate": gate, "contrast": contrast, "fields": per_field}


def _fmt(x, pct=False):
    if x is None:
        return "—"
    return f"{x:.1%}" if pct else f"{x:.3f}"


def render_md(rep: dict, names: tuple[str, str] = ("A", "B")) -> str:
    g = rep["gate"]
    lines = [f"# 标注一致性报告（{rep['checker']}）", "",
             f"- 标注员：{names[0]} × {names[1]}；共同记录 {rep['records_common']} 件"
             f"（只在 A {len(rep['only_in_a'])} 件，只在 B {len(rep['only_in_b'])} 件）",
             f"- 判定口径：{g['basis']}",
             f"- 关键分类字段平均 κ = **{_fmt(g['key_categorical_mean_kappa'])}**（门槛 {g['threshold_kappa']}；"
             f"参与 {', '.join(g['key_categorical_fields_used']) or '无'}）",
             f"- 关键数值字段完全一致率 = **{_fmt(g['key_numeric_exact_rate'], True)}**（{g['key_numeric_pairs']} 对；"
             f"门槛 {g['threshold_numeric']:.0%}）",
             f"- **判定：{'通过' if g['pass'] else '不通过'}**", ""]
    if g["key_categorical_excluded"]:
        lines += ["未进平均的关键分类字段：", ""] + [
            f"- `{e['field']}`：{e['reason']}（union 配对 {e['n_union']}，一致率 {_fmt(e['agree_union'], True)}）"
            for e in g["key_categorical_excluded"]] + [""]
    c = rep["contrast"]
    lines += ["对照口径（只说明口径差异，**不用于判定**）：", "",
              "| 口径 | 关键分类平均 κ | 关键数值一致率 |", "|---|---|---|",
              f"| union（判定） | {_fmt(g['key_categorical_mean_kappa'])} | {_fmt(g['key_numeric_exact_rate'], True)} |",
              f"| all | {_fmt(c['all']['key_categorical_mean_kappa'])} | {_fmt(c['all']['key_numeric_exact_rate'], True)} |",
              f"| valued | {_fmt(c['valued']['key_categorical_mean_kappa'])} | "
              f"{_fmt(c['valued']['key_numeric_exact_rate'], True)} |", "",
              "## 逐字段", "",
              "| 字段 | 类型 | 关键 | union 配对 | κ(union) | 一致率(union) | κ(all) | κ(valued) | 未提及一致率 | 分歧件数 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for f in rep["fields"]:
        if f["n_union"] == 0:
            continue
        lines.append(f"| `{f['field']}` | {'分类' if f['kind'] == 'categorical' else '数值'} | {'★' if f['key'] else ''} | "
                     f"{f['n_union']} | {_fmt(f.get('kappa_union'))} | {_fmt(f['agree_union'], True)} | "
                     f"{_fmt(f.get('kappa_all'))} | {_fmt(f.get('kappa_valued'))} | "
                     f"{_fmt(f['absent_agreement'], True)} | {len(f['disagreements'])} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--out", type=Path, help="报告目录；不给则只打印")
    ap.add_argument("--names", nargs=2, default=("A", "B"), help="标注员名称，如模型 ID")
    x = ap.parse_args(argv)
    rep = agreement(load(x.a), load(x.b))
    rep["annotators"] = list(x.names)
    md = render_md(rep, tuple(x.names))
    if x.out:
        x.out.mkdir(parents=True, exist_ok=True)
        (x.out / "agreement.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
        (x.out / "agreement.md").write_text(md, "utf-8")
    print(md)
    return 0 if rep["gate"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
