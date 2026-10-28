"""规范层（M2）：时间效力、合法处罚空间 Ω、修正情节、涉刑提示。

这里只做法律本身规定的确定性推导，不做任何经验打分：
- 选哪部法律（行政处罚法第三十七条"从旧兼从轻"）
- 每个档次合法的处罚组合有哪些（含减轻、不予处罚）
- 哪些修正情节成立、是否不执行拘留
开放性判断（"情节严重""影响恶劣"）和档内裁量位置留给 M3/M4，从数据学习。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .norm_store import Law, NormLibrary, Tier, load
from .schema import AmountRange, GamblingElements, MinorLevel

NO_PENALTY = "不予处罚"


# ---------- 事实（规范层只读值，不关心证据） ----------

@dataclass
class Facts:
    behavior_date: date | None = None
    decision_date: date | None = None
    region: str | None = None
    behavior_type: str | None = None
    age: int | None = None
    pregnant_or_nursing: bool | None = None
    first_offense: bool | None = None
    violations_last_year: int | None = None
    last_prior_penalty_date: date | None = None
    surrendered: bool | None = None
    truthful_statement: bool | None = None
    admits_and_accepts: bool | None = None
    remedied_consequence: bool | None = None
    victim_forgiveness: bool | None = None
    coerced_or_lured: bool | None = None
    meritorious: bool | None = None
    instigated_others: bool | None = None
    retaliation: bool | None = None
    minor_circumstance: str | None = None
    personal_stake: AmountRange | None = None
    onsite_stake_total: AmountRange | None = None
    commission: AmountRange | None = None
    cumulative_stake: AmountRange | None = None
    participant_count: int | None = None
    cumulative_participants: int | None = None
    abroad_organized_count: int | None = None
    # 省级裁量基准分档用（2026-10-17 江苏、河北录入后加）
    method: str | None = None
    gambling_form: str | None = None
    venue_type: str | None = None
    civil_servant: bool | None = None
    minors_involved: bool | None = None
    profit_purpose: bool | None = None
    times: int | None = None

    @classmethod
    def from_elements(cls, e: GamblingElements) -> "Facts":
        def v(x):
            val = x.value
            return val.value if hasattr(val, "value") and not isinstance(val, AmountRange) else val
        c, a, p = e.circumstances, e.amounts, e.persons
        return cls(
            behavior_date=e.meta.behavior_date, decision_date=e.meta.decision_date, region=e.meta.region,
            behavior_type=v(e.conduct.behavior_type), age=v(e.person.age),
            pregnant_or_nursing=v(e.person.pregnant_or_nursing), first_offense=v(c.first_offense),
            violations_last_year=v(c.violations_last_year), last_prior_penalty_date=v(c.last_prior_penalty_date),
            surrendered=v(c.surrendered), truthful_statement=v(c.truthful_statement),
            admits_and_accepts=v(c.admits_and_accepts), remedied_consequence=v(c.remedied_consequence),
            victim_forgiveness=v(c.victim_forgiveness), coerced_or_lured=v(c.coerced_or_lured),
            meritorious=v(c.meritorious), instigated_others=v(c.instigated_others), retaliation=v(c.retaliation),
            minor_circumstance=v(c.minor_circumstance),
            personal_stake=v(a.personal_stake), onsite_stake_total=v(a.onsite_stake_total),
            commission=v(a.commission), cumulative_stake=v(a.cumulative_stake),
            participant_count=v(p.participant_count), cumulative_participants=v(p.cumulative_participants),
            abroad_organized_count=v(p.abroad_organized_count),
            method=v(e.conduct.method), gambling_form=v(e.conduct.gambling_form), venue_type=v(e.venue.venue_type), civil_servant=v(p.civil_servant),
            minors_involved=v(p.minors_involved), profit_purpose=v(e.intent.profit_purpose), times=v(e.conduct.times),
        )


def _all(*xs):
    """三值逻辑与：任一为 False → False；全为 True → True；否则未知（None）。"""
    if any(x is False for x in xs):
        return False
    return True if all(x is True for x in xs) else None


def _months_between(earlier: date, later: date) -> float:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month) + (later.day - earlier.day) / 31


def _prior_within(f: Facts, law: Law) -> bool | None:
    window = law.modifiers.get("aggravation", {}).get("prior_penalty_window_months")
    if window is None or f.behavior_date is None:
        return None
    if f.last_prior_penalty_date is None:
        return None
    return 0 <= _months_between(f.last_prior_penalty_date, f.behavior_date) <= window


# 触发项名称 → 判定函数。哪部法律启用哪些触发项写在规范库 YAML 里。
TRIGGERS = {
    "情节轻微": lambda f, law: None if f.minor_circumstance is None
        else f.minor_circumstance in (MinorLevel.MINOR.value, MinorLevel.VERY_MINOR.value),
    "情节特别轻微": lambda f, law: None if f.minor_circumstance is None
        else f.minor_circumstance == MinorLevel.VERY_MINOR.value,
    "主动消除或者减轻违法后果": lambda f, law: f.remedied_consequence,
    "取得被侵害人谅解": lambda f, law: f.victim_forgiveness,
    "主动消除后果并取得谅解": lambda f, law: _all(f.remedied_consequence, f.victim_forgiveness),
    "出于他人胁迫或者诱骗": lambda f, law: f.coerced_or_lured,
    "主动投案如实陈述": lambda f, law: _all(f.surrendered, f.truthful_statement),
    "立功": lambda f, law: f.meritorious,
    "认错认罚": lambda f, law: _all(f.truthful_statement, f.admits_and_accepts),
    "教唆胁迫诱骗他人": lambda f, law: f.instigated_others,
    "打击报复": lambda f, law: f.retaliation,
    "前次处罚在期限内": _prior_within,
}


# ---------- Ω：合法处罚空间 ----------

@dataclass(frozen=True)
class Option:
    """一种合法的处罚组合。detention/fine 为闭区间，None 表示不处该种处罚。"""
    detention: tuple[int, int] | None
    fine: tuple[float, float] | None
    via: str                                  # 法定幅度 / 减轻 / 不予处罚
    basis: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        if self.detention and self.fine:
            return "拘留并处罚款"
        if self.detention:
            return "拘留"
        return "罚款" if self.fine else NO_PENALTY

    def contains(self, detention_days: int, fine: float) -> bool:
        def ok(rng, x):
            return x == 0 if rng is None else rng[0] <= x <= rng[1]
        return ok(self.detention, detention_days) and ok(self.fine, fine)


@dataclass
class Direction:
    effect: str                               # 从轻 / 减轻 / 不予处罚 / 从宽 / 从重
    trigger: str
    basis: str                                # 如 psal-2025#20


@dataclass
class TierResult:
    options: list[Option]
    detention_executable: bool | None = True  # False = 依法不执行拘留；None = 需人工判断
    not_executed_reason: str | None = None


@dataclass
class Assessment:
    law_id: str
    temporal_note: str
    tiers: dict[str, TierResult]
    directions: list[Direction] = field(default_factory=list)
    referral: list[dict] = field(default_factory=list)
    stake_threshold: dict = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)
    basis_verified: bool = False
    # tiers 逐档枚举按已知事实展开的选项；不表示某档已被事实证明。
    option_scope: str = "各预设档次下按已知事实展开的法定选项"
    exhaustive_for_case: bool = False

    def contains(self, tier: str, detention_days: int, fine: float) -> bool:
        """仅检查所选档次内已列出的选项，不证明档次选择或个案事实已穷尽。"""
        return any(o.contains(detention_days, fine) for o in self.tiers[tier].options)


def _statutory(law: Law, tier: Tier) -> list[Option]:
    basis = (f"{law.law_id}#{law.penalty_article}",)
    if tier.combination == "或":
        return [Option(tier.detention, None, "法定幅度", basis), Option(None, tier.fine, "法定幅度", basis)]
    if tier.combination == "并处":
        return [Option(tier.detention, tier.fine, "法定幅度", basis)]
    if tier.combination == "可以并处":
        return [Option(tier.detention, None, "法定幅度", basis), Option(tier.detention, tier.fine, "法定幅度", basis)]
    raise ValueError(f"未知的处罚组合方式：{tier.combination}")


def _mitigated(lib: NormLibrary, law: Law, tier: Tier, notes: list[str]) -> list[Option]:
    """按公通字〔2007〕1号第四条展开减轻处罚；未覆盖的组合方式只给不予处罚并要求人工复核。"""
    rules = lib.mitigation_rules
    basis = (f"{law.law_id}#{law.penalty_article}", rules.get("basis", ""))
    det_lo, det_hi = tier.detention
    fine_lo, fine_hi = tier.fine
    below_det = (1, det_lo - 1) if det_lo > 1 else None
    below_fine = (1, fine_lo - 1) if fine_lo > 1 else None
    if tier.combination == "并处":
        out = []
        for r in rules.get("并处", []):
            det = {"below": below_det, "within": tier.detention}.get(r["detention"])
            fine = {"below": below_fine, "within": tier.fine, "none": None}.get(r["fine"])
            if r["detention"] == "below" and det is None or r["fine"] == "below" and fine is None:
                continue
            out.append(Option(det, fine, "减轻", basis))
        return out
    notes.append(f"'{tier.combination}'的减轻方式不在{rules.get('basis', '解释性文件')}覆盖范围内，"
                 "减轻时只列出不予处罚，需人工确认")
    return []


def _active(lib: NormLibrary, law: Law, f: Facts, notes: list[str]) -> list[Direction]:
    dirs = []
    for key in ("mitigation", "leniency", "aggravation"):
        mod = law.modifiers.get(key)
        if not mod:
            continue
        for trig in mod["triggers"]:
            hit = TRIGGERS[trig](f, law)
            if hit:
                dirs += [Direction(e, trig, f"{law.law_id}#{mod['article']}") for e in mod["effect"]]
            elif hit is None and key == "aggravation" and trig == "前次处罚在期限内" and f.last_prior_penalty_date:
                notes.append("缺少行为日期，无法判断前次处罚是否在从重期限内")
    age = f.age
    under, minor = law.modifiers.get("under_age"), law.modifiers.get("minor")
    if age is not None and minor and minor["age_from"] <= age < minor["age_below"]:
        dirs += [Direction(e, "已满十四周岁不满十八周岁", f"{law.law_id}#{minor['article']}") for e in minor["effect"]]
    if age is not None and under and age < under["age_below"]:
        dirs.append(Direction(NO_PENALTY, "不满十四周岁", f"{law.law_id}#{under['article']}"))
    return dirs


def _not_executed(law: Law, f: Facts, tier_name: str) -> tuple[bool | None, str | None, list[str]]:
    mod = law.modifiers.get("detention_not_executed")
    if not mod:
        return True, None, []
    notes, cats = [], []
    if f.age is not None:
        if 14 <= f.age < 16:
            cats.append("已满十四不满十六")
        if 16 <= f.age < 18:
            if f.first_offense is True:
                cats.append("十六至十八初次")
            elif f.first_offense is None:
                notes.append("已满十六不满十八周岁但不清楚是否初次违反治安管理，不执行拘留与否需确认")
        if f.age >= 70:
            cats.append("七十周岁以上")
    if f.pregnant_or_nursing:
        cats.append("孕期或哺乳")
    cats = [c for c in cats if c in mod["categories"]]
    if not cats:
        return (None if notes else True), None, notes
    basis = f"{law.law_id}#{mod['article']}"
    remaining = []
    for cat in cats:
        blocked: bool | None = False      # True = 例外成立仍执行；None = 例外是否成立需人工判断
        for ex in mod.get("exceptions", []):
            if cat not in ex["categories"]:
                continue
            if ex["condition"] == "一年内二次以上违反治安管理" and (f.violations_last_year or 0) >= 2:
                blocked = True
            elif ex["condition"] == "情节严重且影响恶劣" and tier_name == "情节严重":
                if blocked is False:
                    blocked = None
                notes.append(f"{cat}：情节严重时若影响恶劣则仍执行拘留（{basis}第二款），需人工判断")
        if blocked is not True:
            remaining.append((cat, blocked))
    if not remaining:
        return True, None, notes
    # 只要有一个类别明确不执行，结论就是不执行；否则需人工判断
    cat, blocked = next(((c, b) for c, b in remaining if b is False), remaining[0])
    return (None if blocked is None else False), f"{cat}（{basis}）", notes


def _referral(lib: NormLibrary, f: Facts) -> list[dict]:
    th = lib.criminal_thresholds
    if not th:
        return []
    out = []
    values = {"commission": f.commission, "cumulative_stake": f.cumulative_stake,
              "cumulative_participants": f.cumulative_participants, "abroad_organized_count": f.abroad_organized_count}
    for key, limit in th["any_of"].items():
        v = values.get(key)
        if v is None:
            continue
        lo, hi = (v.min, v.upper) if isinstance(v, AmountRange) else (v, v)  # 开口上界按正无穷：只能"可能达到"
        if lo >= limit:
            out.append({"item": key, "threshold": limit, "status": "达到"})
        elif hi >= limit:
            out.append({"item": key, "threshold": limit, "status": "可能达到"})
    if f.behavior_type in ("开设赌场", "以赌博为业", "聚众赌博"):
        out.append({"item": "behavior_type", "threshold": None, "status": f"行为类型为{f.behavior_type}"})
    for r in out:
        r["basis"] = th.get("basis")
        r["verified"] = th.get("verification") == "已核验"
    return out


# ---------- 省级裁量基准分档（norms/provinces/<区划>.yaml 的 rules） ----------
# 省级基准把同一法定档次再细分成几档（如江苏：赌资 100 元起罚款、500 元起拘留、1000 元起情节严重）。
# 这里只按原文数额做确定性分档，并对区间值、归类不明做三值处理；它是"裁量建议"，不改变合法空间 Ω。

def _measure_interval(f: Facts, field_name: str, sources: list[dict] | None = None
                      ) -> tuple[tuple[float, float], str] | None:
    """计量 → ([下界, 上界], 说明)。上界开口时为正无穷。

    sources：省级 YAML 声明的取值顺序（每项 {use, label}，label 写明基准条款），按顺序取第一个已知的；
    没有声明时沿用内置口径。"""
    def rng(a: AmountRange | None):
        return (a.min, a.upper) if a is not None else None
    if sources:
        for s in sources:
            got = _measure_interval(f, s["use"])
            if got is not None:
                return got[0], s.get("label") or got[1]
        return None
    if field_name == "per_capita":
        if f.onsite_stake_total is not None and f.participant_count:
            return rng(per_capita_stake(f.onsite_stake_total, f.participant_count)), "人均赌资（现场赌资 ÷ 参赌人数）"
        return None
    if field_name == "personal_or_per_capita":
        if f.personal_stake is not None:
            return rng(f.personal_stake), "个人赌资"
        if f.onsite_stake_total is not None and f.participant_count:
            return rng(per_capita_stake(f.onsite_stake_total, f.participant_count)), "人均赌资（现场赌资 ÷ 参赌人数）"
        return None
    if field_name in ("personal_stake", "onsite_stake_total", "commission", "cumulative_stake"):
        r = rng(getattr(f, field_name))
        return (r, field_name) if r else None
    v = getattr(f, field_name, None)
    return ((v, v), field_name) if v is not None else None


def _band_index(x: float, bounds: list[float]) -> int:
    """落在第几档：x ≥ 第 k 个下限即至少第 k 档；0 表示未达第一档。"""
    return sum(x >= b for b in bounds)


def _flag(f: Facts, key: str) -> bool | None:
    public = None if f.venue_type is None else f.venue_type in ("公共场所", "交通工具")
    online = True if f.method == "网络赌博" or f.venue_type == "网络" else (None if f.method is None else False)
    prior = None
    if f.last_prior_penalty_date and f.behavior_date:
        prior = 0 <= _months_between(f.last_prior_penalty_date, f.behavior_date) <= 12
    return {"civil_servant": f.civil_servant, "minors_involved": f.minors_involved, "venue_public": public,
            "method_online": online, "venue_public_for_profit": _all(public, f.profit_purpose),
            "prior_within_year": prior}.get(key)


def _date_value(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _stake_unavailable(status: str, reason: str, *, basis: str | None = None,
                       verified: bool = False, notes: list[str] | None = None) -> dict:
    """无可用省级分档时保持同形返回，避免调用方误用旧档位。"""
    return {"status": status, "applicability": "unavailable", "reason": reason,
            "bands": [], "band_penalty": [], "measures_used": [],
            "basis": basis, "verified": verified, "notes": notes or [],
            "scope": "已知要素的省级建议，不是最终处罚结论",
            "observed_band_indices": [],
            "unknown_conditions": [], "final_band_determinable": False,
            "hard_filter_allowed": False, "computation": []}


def _stake_threshold(lib: NormLibrary, f: Facts, law: Law | None = None) -> dict:
    if f.behavior_type not in ("参与赌博", "为赌博提供条件"):
        return _stake_unavailable("不适用", "行为类型不属于已建模的省级分档")
    prov = lib.provinces.get((f.region or "")[:2] + "0000")
    rules = (prov or {}).get("rules") or {}
    if f.behavior_type not in rules:
        return _stake_unavailable("门槛未知", "目标省份裁量基准未录入或未核验")
    rule, bands = rules[f.behavior_type], prov["bands"]
    doc = (prov.get("documents") or [{}])[0]
    basis = doc.get("number") or doc.get("title")
    verified = (doc.get("verification") or {}).get("status") == "已核验"
    decision = f.decision_date or f.behavior_date
    start, end = _date_value(doc.get("effective_from")), _date_value(doc.get("effective_to"))
    if ((start and f.behavior_date and f.behavior_date < start)
            or (end and decision and decision > end)):
        return _stake_unavailable("基准未生效", "省级基准不适用于本案行为或决定日期",
                                  basis=basis, verified=verified)
    if not verified:
        return _stake_unavailable("基准待核验", "省级基准尚未核验", basis=basis)
    notes, used, unknown = [], [], []
    comp = []                       # 计算过程（追踪用）：每个计量 / 托底 / 升档一条，只记录已发生的比较
    # 新法施行后省级基准未更新（法宝 2026-10-28 核：两省及公安部均无新法版本，旧版仍标现行有效）。
    # 新法第八十二条档次结构不变（一般：拘留或罚款；情节严重：拘留并处罚款），只提高了罚款数额，
    # 故推定沿用省级门槛与档次判断处罚种类；档位原文中的罚款数额是旧法数额，本案数额以新法法定幅度为准。
    alignment = None
    if ((decision and decision >= date(2026, 1, 1) and doc.get("new_law_alignment") == "未更新-旧法数额")
            or (law is not None and doc.get("law_basis") and doc["law_basis"] != law.law_id)):
        alignment = (f"省级基准依据 {doc.get('law_basis')} 制定，本案适用 {law.law_id if law else '新法'}：推定沿用其"
                     "赌资门槛与档次判断处罚种类；档位原文中的罚款数额为旧法数额，本案数额以新法法定幅度为准")
        notes.append(alignment)
    possible = {0}                  # 已知计量下可能的档次索引；0 = 未达第一档
    has_signal = measure_found = False
    if f.decision_date is None:
        notes.append("未提供决定日期，省级基准时间判断暂以行为日期代替")
    measures = rule["measures"]
    if rule.get("combine") == "personal_first" and _measure_interval(f, "personal_stake") is not None:
        # 个人赌资查明时只按个人定档；其余计量（一场赌资）仅经 entry_floor 判断是否达到起罚线
        measures = [m for m in measures if m["field"] == "personal_stake"]
        notes.append(rule.get("combine_note") or "个人赌资已查明，按个人赌资定档")
    for m in measures:
        got = _measure_interval(f, m["field"], m.get("sources"))
        if got is None:
            unknown.append(m["field"])
            comp.append({"step": "measure", "field": m["field"], "label": m.get("label"), "value": None,
                         "result": "未知"})
            continue
        has_signal = True
        measure_found = True
        (a, b), how = got
        if "categories" in m:
            cats = m["categories"]
            # 方式（网络、赌博机、私彩等）可直接归类；其余看本场赌博的组织形式（聚众、赌场 / 其他）
            options = ([c for c in cats if f.method in (c.get("methods") or [])]
                       or [c for c in cats if f.gambling_form in (c.get("forms") or [])] or cats)
            if len(options) > 1:
                unknown.append("赌博方式的省级法定类别")
                notes.append("赌博方式归类不能从要素确定（如是否属聚众、赌场赌博），按"
                             + "、".join(c["id"] for c in options) + "分别计算，档次取并集")
            measure_possible = {k for c in options for k in range(
                _band_index(a, c["lower_bounds"]), _band_index(b, c["lower_bounds"]) + 1)}
            thresholds = [{"category": c["id"], "label": c.get("label"), "lower_bounds": c["lower_bounds"],
                           "bands": sorted(range(_band_index(a, c["lower_bounds"]),
                                                 _band_index(b, c["lower_bounds"]) + 1))} for c in options]
        else:
            measure_possible = set(range(_band_index(a, m["lower_bounds"]),
                                         _band_index(b, m["lower_bounds"]) + 1))
            thresholds = [{"category": None, "label": None, "lower_bounds": m["lower_bounds"],
                           "bands": sorted(measure_possible)}]
        comp.append({"step": "measure", "field": m["field"], "label": m.get("label") or how, "basis_of_value": how,
                     "value": [a, None if b == float("inf") else b], "thresholds": thresholds,
                     "result": sorted(measure_possible)})
        possible = {max(previous, current) for previous in possible for current in measure_possible}
        used.append(m.get("label") or how)
    floor = rule.get("entry_floor")
    if floor and 0 in possible:
        got = _measure_interval(f, floor["field"])
        if got is not None and got[0][1] >= floor["min"]:
            lifted = {max(k, floor["to"]) for k in possible}
            possible = lifted if got[0][0] >= floor["min"] else possible | lifted
            comp.append({"step": "entry_floor", "field": floor["field"], "value": [got[0][0], None if got[0][1] == float("inf") else got[0][1]],
                         "min": floor["min"], "text": floor["text"], "result": sorted(possible)})
            measure_found = has_signal = True
            used.append(floor["text"])
    amount_possible = set(possible)
    elevated = False
    for e in rule.get("elevate") or []:
        hit = _flag(f, e["when"])
        if hit is True:
            if f.behavior_type == "参与赌博" and not measure_found:
                # 第七十条以"赌资较大"为参与赌博的处罚前提：赌资不明时，未达则不予处罚，达到才按升档条件定档
                # Q-10（新数据检验，2026-10-28）：赌资不明时升档条件不足以定到该档，历史只有 48% 到第三档 → 各档都保留为候选
                possible = possible | set(range(1, e["to"] + 1))
                notes.append(f"赌资是否达到起罚标准未知：未达则不予处罚；达到则依“{e['text']}”定为"
                             f"{bands['names'][e['to'] - 1]}")
            else:
                possible = {max(k, e["to"]) for k in possible}
            comp.append({"step": "elevate", "condition": e["when"], "text": e["text"], "to": e["to"],
                         "stake_known": measure_found, "result": sorted(possible)})
            elevated = True
            has_signal = True
            used.append(e["text"])
        elif hit is None:
            unknown.append(e["when"])
    for e in rule.get("floor_hint") or []:
        hit = _flag(f, e["when"])
        if hit is True:
            notes.append(f"可能至少落入{bands['names'][e['to'] - 1]}：{e['text']}")
        elif hit is None:
            unknown.append(e["when"])
    if not has_signal:
        out = _stake_unavailable("无法判断", "缺少分档所需的数额或情节", basis=basis, verified=verified)
        out["unknown_conditions"] = list(dict.fromkeys(unknown))
        out["notes"] = notes
        out["law_alignment"] = "新法推定沿用" if alignment else None
        return out
    lo, hi = min(possible), max(possible)
    names = ["未达起罚标准" if k == 0 else bands["names"][k - 1] for k in sorted(possible)]
    out = {"bands": names, "band_penalty": [bands["penalty"][k - 1] for k in sorted(possible) if k > 0],
           "measures_used": used, "basis": basis, "verified": verified,
           "applicability": "applicable" if f.decision_date is not None and alignment is None else "provisional",
           "law_alignment": "新法推定沿用" if alignment else None,
           "scope": "已知要素的省级建议，不是最终处罚结论",
           "observed_band_indices": sorted(possible), "computation": comp,
           "unknown_conditions": list(dict.fromkeys(unknown)),
           "final_band_determinable": False, "hard_filter_allowed": False}
    if f.behavior_type == "参与赌博":
        out["status"] = ("明确情节升档、赌资门槛未知" if not measure_found
                         else "情节升档、已知赌资未达数额门槛" if elevated and max(amount_possible) == 0
                         else "已知赌资未达、其他条件待核" if hi == 0 and unknown
                         else "未达到赌资较大" if hi == 0
                         else "达到赌资较大" if min(amount_possible) >= 1 else "可能达到")
        if lo == 0 and rule.get("below_min"):
            notes.append(rule["below_min"])
            if rule.get("below_min_review"):
                notes.append(rule["below_min_review"])
    else:
        out["status"] = "未达第一档" if hi == 0 else ("已知要素档次确定" if lo == hi else "已知要素档次待定")
    if any("近似" in u for u in used):
        notes.append("'一场赌资'以现场查获赌资合计近似，两者口径不完全相同")
    out["notes"] = notes
    return out


def _assess_with(lib: NormLibrary, law: Law, f: Facts) -> Assessment:
    notes: list[str] = []
    dirs = _active(lib, law, f, notes)
    effects = {d.effect for d in dirs}
    tiers = {}
    for name, tier in law.tiers.items():
        if NO_PENALTY in effects and any(d.trigger == "不满十四周岁" for d in dirs):
            tiers[name] = TierResult([Option(None, None, NO_PENALTY, (f"{law.law_id}#12",))], True, None)
            continue
        opts = _statutory(law, tier)
        if "减轻" in effects:
            opts += _mitigated(lib, law, tier, notes)
        if NO_PENALTY in effects or ("减轻" in effects and tier.combination == "或"):
            basis = tuple(sorted({d.basis for d in dirs if d.effect in (NO_PENALTY, "减轻")}))
            opts.append(Option(None, None, NO_PENALTY, basis))
        executable, reason, ne_notes = _not_executed(law, f, name)
        notes += ne_notes
        tiers[name] = TierResult(opts, executable, reason)
    if any(d.effect == "从宽" for d in dirs):
        notes.append("认错认罚'可以依法从宽'：从宽幅度由裁量模型学习，规范层不改变处罚空间")
    used = {law.law_id, lib.mitigation_rules.get("basis", "").split("#")[0]} if "减轻" in effects else {law.law_id}
    stake = _stake_threshold(lib, f, law)
    if stake["status"] in ("基准未生效", "基准待核验"):
        notes.append(stake["reason"])
        notes.extend(stake["notes"])
    elif stake.get("law_alignment"):
        notes.extend(n for n in stake["notes"] if "推定沿用" in n)
    notes.extend(n for n in stake.get("notes") or [] if n.startswith("请核实"))   # 输入口径提示（如江苏低额赌资口径，Q-02）
    return Assessment(
        law_id=law.law_id, temporal_note="", tiers=tiers, directions=dirs,
        referral=_referral(lib, f), stake_threshold=stake,
        needs_review=list(dict.fromkeys(notes)),
        basis_verified=all(lib.is_verified(d) for d in used if d),
    )


def _severity(a: Assessment) -> list[tuple[float, float, float, float]]:
    """每档 (最重拘留, 最高罚款, 最轻拘留, 最低罚款)；不处某种处罚记 0。"""
    out = []
    for name in sorted(a.tiers):
        opts = a.tiers[name].options
        out.append((
            max((o.detention[1] if o.detention else 0) for o in opts),
            max((o.fine[1] if o.fine else 0) for o in opts),
            min((o.detention[0] if o.detention else 0) for o in opts),
            min((o.fine[0] if o.fine else 0) for o in opts),
        ))
    return out


def assess(f: Facts, lib: NormLibrary | None = None) -> Assessment:
    """按行政处罚法第三十七条选择适用法律，并给出各档次的合法处罚空间与修正情节。"""
    lib = lib or load()
    if f.behavior_date is None:
        raise ValueError("缺少违法行为发生日期，无法确定适用法律")
    decision = f.decision_date or f.behavior_date
    if decision < f.behavior_date:
        raise ValueError("处罚决定日期早于违法行为日期，无法确定适用法律")
    old, new = lib.law_in_force(f.behavior_date), lib.law_in_force(decision)
    if old is None or new is None:
        raise ValueError("行为日期或决定日期不在规范库覆盖的施行期间内")
    old_a = _assess_with(lib, old, f)
    if old.law_id == new.law_id:
        old_a.temporal_note = f"行为时与决定时均适用{old.title}"
        return old_a
    new_a = _assess_with(lib, new, f)
    sev_old, sev_new = _severity(old_a), _severity(new_a)
    pairs = [(n, o) for tn, to in zip(sev_new, sev_old) for n, o in zip(tn, to)]
    new_lighter = all(n <= o for n, o in pairs) and any(n < o for n, o in pairs)
    old_not_heavier = all(o <= n for n, o in pairs)
    ref = "apl-2021#37"
    if new_lighter:
        new_a.temporal_note = f"行为时适用{old.title}，决定时{new.title}处罚较轻，依{ref}适用新法"
        return new_a
    old_a.temporal_note = f"行为时适用{old.title}；{new.title}处罚不轻于旧法，依{ref}适用行为时法"
    if not old_not_heavier:
        old_a.needs_review.append(f"新旧法轻重互有高低（{new.title}在部分方面较轻），"
                                  "默认适用行为时法，请人工确认是否适用新法")
    return old_a


def merge_detention(days: list[int], law: Law) -> int:
    """数个违法行为分别决定、合并执行的拘留天数（第十六条上限）。"""
    cap = law.modifiers.get("merge_cap", {}).get("max_detention_days")
    total = sum(days)
    return min(total, cap) if cap else total


def per_capita_stake(total: AmountRange, participants: int) -> AmountRange:
    """个人投注额无法确定时按人均计算（公通字〔2005〕30号第六条，待核验）。"""
    if participants <= 0:
        raise ValueError("参赌人数必须为正数")
    return AmountRange(min=total.min / participants, max=None if total.max is None else total.max / participants)
