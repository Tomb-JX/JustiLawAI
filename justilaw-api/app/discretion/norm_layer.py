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

    def contains(self, tier: str, detention_days: int, fine: float) -> bool:
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
        lo, hi = (v.min, v.max) if isinstance(v, AmountRange) else (v, v)
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


def _stake_threshold(lib: NormLibrary, f: Facts) -> dict:
    if f.behavior_type != "参与赌博":
        return {"status": "不适用"}
    prov = lib.provinces.get((f.region or "")[:2] + "0000")
    th = (prov or {}).get("stake_threshold") or {}
    if not th or all(v is None for v in th.values()):
        return {"status": "门槛未知", "reason": "目标省份裁量基准未录入或未核验"}
    stake = f.personal_stake
    limit = th.get("personal_min")
    if stake is None or limit is None:
        return {"status": "无法判断"}
    if stake.min >= limit:
        return {"status": "达到赌资较大", "threshold": limit}
    if stake.max < limit:
        return {"status": "未达到赌资较大", "threshold": limit}
    return {"status": "可能达到", "threshold": limit}


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
    return Assessment(
        law_id=law.law_id, temporal_note="", tiers=tiers, directions=dirs,
        referral=_referral(lib, f), stake_threshold=_stake_threshold(lib, f),
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
    return AmountRange(min=total.min / participants, max=total.max / participants)
