"""字段绑定语义定义（引擎侧唯一规范）。

本模块定义每个要素字段的绑定语义：该字段的值是描述"场景级事实"还是"目标本人事实"。
这是语义定义，不是分类实现——怎么从文本判定绑定是后处理线的职责。

分工边界（collab-log 2026-10-18 架构分析）：
- 引擎：定义"什么是正确"（字段绑定语义、验收标准）
- 后处理：实现"怎么做到"（文本分类、别名处理、resolve 策略）

用法：
    from binding_rules import FIELD_BINDING, BindingType

后处理参考：classify_binding 的实现应基于文档结构（事实段 vs 决定段）、
subject_mention 位置、aliases 映射，不应依赖 regex 文本匹配。
"""
from __future__ import annotations

from enum import Enum


class BindingType(str, Enum):
    """字段绑定语义类型。

    - SHARED（场景级）：该字段的值描述的是多人共享的场景事实，
      如"现场查获赌资 3910 元"（在场所有人都适用）、"参赌人数 5 人"。
    - TARGET（个人级）：该字段的值描述的是目标本人的事实，
      如"甲持有赌资 350 元"、"甲系参赌者"。
    """
    SHARED = "shared_fact"
    TARGET = "target_specific"


# --- 字段绑定语义表 ---
# 这是引擎侧唯一权威定义。修改需在 collab-log 登记。
#
# 判定原则：
# - 如果该字段的值对案卷中每个参赌人都相同 → SHARED
# - 如果该字段的值因人而异 → TARGET
# - 如果不确定 → TARGET（默认更安全，因为错误归属 shared 的代价更高）

FIELD_BINDING: dict[str, BindingType] = {
    # ── 场景级（shared）：在场所有人共享 ──
    "amounts.onsite_stake_total": BindingType.SHARED,    # 现场赌资总额
    "amounts.cumulative_stake": BindingType.SHARED,      # 累计赌资（多次合计）
    "persons.participant_count": BindingType.SHARED,     # 参赌人数
    "persons.cumulative_participants": BindingType.SHARED,
    "persons.minors_involved": BindingType.SHARED,       # 是否有未成年人参赌
    "persons.relatives_only": BindingType.SHARED,        # 参与者是否均为亲属
    "venue.venue_type": BindingType.SHARED,              # 赌博场所类型
    "conduct.method": BindingType.SHARED,                # 赌博方式（麻将/扑克等）

    # ── 个人级（target）：因人而异 ──
    "conduct.behavior_type": BindingType.TARGET,         # 本人行为类型
    "conduct.role": BindingType.TARGET,                  # 本人角色
    "conduct.times": BindingType.TARGET,                 # 本人赌博次数
    "conduct.duration_days": BindingType.TARGET,         # 持续时间
    "conduct.cheating": BindingType.TARGET,              # 是否作弊
    "amounts.personal_stake": BindingType.TARGET,        # 本人赌资
    "amounts.per_bet": BindingType.TARGET,               # 单注金额
    "amounts.commission": BindingType.TARGET,            # 抽头渔利
    "amounts.illegal_gain": BindingType.TARGET,          # 其他违法所得
    "persons.civil_servant": BindingType.TARGET,         # 本人是否为国家工作人员
    "persons.abroad_organized_count": BindingType.TARGET, # 本人组织出境赌博人数
    "intent.profit_purpose": BindingType.TARGET,         # 本人是否以营利为目的
    "circumstances.last_prior_penalty_date": BindingType.TARGET,
    "circumstances.surrendered": BindingType.TARGET,
    "circumstances.truthful_statement": BindingType.TARGET,
    "circumstances.admits_and_accepts": BindingType.TARGET,
    "circumstances.remedied_consequence": BindingType.TARGET,
    "circumstances.victim_forgiveness": BindingType.TARGET,
    "circumstances.coerced_or_lured": BindingType.TARGET,
    "circumstances.meritorious": BindingType.TARGET,
    "circumstances.instigated_others": BindingType.TARGET,
    "circumstances.retaliation": BindingType.TARGET,
    "circumstances.obstructed_police": BindingType.TARGET,
    "circumstances.minor_circumstance": BindingType.TARGET,
    "circumstances.first_offense": BindingType.TARGET,
    "circumstances.violations_last_year": BindingType.TARGET,
    "person.age": BindingType.TARGET,
    "person.pregnant_or_nursing": BindingType.TARGET,
}