"""赌博案件要素本体（M1 抽取目标、数据标注格式、M2–M4 的输入）。

原则：
- 只记录**事实**，不记录法律结论。例如记录"上次受治安处罚的日期"，而不是"一年内受过处罚"——
  2012 版是六个月、2025 版是一年，结论由规范层按适用的法律版本推导。
- 每个抽取字段都带原文证据与状态（明确 / 推断 / 未提及），证据必须能在原文中找到。
- 字段的 description 就是标注指南（GoLLIE 的做法：指南写进 schema），
  `python -m app.discretion.schema` 可导出指南表与 JSON Schema。

版本：字段增删或语义变化时提升 SCHEMA_VERSION，并在 docs/04-plan/collab-log.md 登记。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1.2.0"  # 1.2.0：新增 conduct.gambling_form（江苏基准按聚众/赌场与其他赌博活动分两类门槛，collab-log 2026-10-28）； 1.1.0：金额允许无上界；营利目的改为只记原文认定与本人获利事实（collab-log 2026-10-17）

T = TypeVar("T")


class FieldStatus(str, Enum):
    EXPLICIT = "明确"      # 原文直接写明
    INFERRED = "推断"      # 原文没有直接写明，由上下文合理推出（必须仍附证据）
    ABSENT = "未提及"      # 原文没有相关信息；值必须为空


class Evidence(BaseModel):
    quote: str = Field(description="原文中的连续片段，逐字摘录，不得改写")
    start: int | None = Field(default=None, description="片段在原文中的起始字符位置（由证据校验器回填）")
    end: int | None = None


class Extracted(BaseModel, Generic[T]):
    value: T | None = None
    status: FieldStatus = FieldStatus.ABSENT
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1, description="模型置信度；人工标注留空")

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == FieldStatus.ABSENT and self.value is not None:
            raise ValueError("状态为'未提及'时值必须为空")
        if self.status != FieldStatus.ABSENT and self.value is None:
            raise ValueError("状态为'明确'或'推断'时必须给出值")
        if self.status != FieldStatus.ABSENT and not self.evidence:
            raise ValueError("给出值时必须附原文证据")
        return self


class AmountRange(BaseModel):
    """金额（元），闭区间 [min, max]。

    - 确切数额 min=max；"三千余元"记 3000–3999（余 = 末位非零数位上不足一个单位）；
      "约 5 万元"记 45000–55000；其余写法见标注指南 §2。
    - **max 为空表示没有上界**，只用于"以上 / 逾 / 超过 / 至少 / 不低于"这类开口写法：
      "赌资在万元以上"记 min=10000、max=空。不得按数量级替它补一个上界——
      补出来的上界会让规范层把"可能达到入罪门槛"错判成"未达到"。
    """
    min: float = Field(ge=0)
    max: float | None = Field(default=None, ge=0, description="上界；为空表示开口（原文只给了下界）")

    @model_validator(mode="after")
    def _ordered(self):
        if self.max is not None and self.min > self.max:
            raise ValueError("min 不能大于 max")
        return self

    @property
    def upper(self) -> float:
        """比较用的上界：开口时为正无穷。"""
        return float("inf") if self.max is None else self.max

    @property
    def open_upper(self) -> bool:
        return self.max is None


# ---------- 取值枚举 ----------

class BehaviorType(str, Enum):
    PARTICIPATE = "参与赌博"
    PROVIDE_CONDITIONS = "为赌博提供条件"
    GATHER_GAMBLING = "聚众赌博"          # 组织他人赌博并从中获利（可能涉刑）
    OPEN_CASINO = "开设赌场"              # 可能涉刑
    GAMBLING_AS_BUSINESS = "以赌博为业"
    ENTERTAINMENT = "带彩娱乐"            # 少量财物输赢的娱乐，可能不构成违法
    OTHER = "其他"


class GamblingForm(str, Enum):
    GATHERING = "聚众赌博"                # 有人组织、召集他人赌博
    CASINO = "赌场赌博"                   # 专门开设的赌场或以赌博为经营的场所
    OTHER = "其他"                        # 无组织者的自发赌博（如亲友邻里间）


class GamblingMethod(str, Enum):
    MAHJONG = "麻将"
    POKER = "扑克"
    DICE = "骰子"
    MACHINE = "赌博机"
    ONLINE = "网络赌博"
    PRIVATE_LOTTERY = "私彩"
    MARK_SIX = "六合彩"
    SPORTS_BETTING = "赌球"
    OTHER = "其他"


class Role(str, Enum):
    ORGANIZER = "组织者"
    CONDITION_PROVIDER = "提供条件者"     # 提供场所、赌具、资金等
    COMMISSION_TAKER = "抽头者"
    PARTICIPANT = "参赌者"
    LOOKOUT = "望风者"
    LENDER = "放贷者"
    OTHER = "其他"


class VenueType(str, Enum):
    RESIDENCE = "住宅"
    BUSINESS = "经营场所"                 # 茶楼、棋牌室、宾馆等
    PUBLIC = "公共场所"
    VEHICLE = "交通工具"
    ONLINE = "网络"
    ABROAD = "境外"
    OTHER = "其他"


class MinorLevel(str, Enum):
    MINOR = "情节轻微"
    VERY_MINOR = "情节特别轻微"


# ---------- 要素分组 ----------

class Conduct(BaseModel):
    behavior_type: Extracted[BehaviorType] = Field(default_factory=Extracted,
        description="本人的行为类型。只按事实描述判断，拿不准时选最接近的一项并标'推断'；"
                    "多种行为时选最严重的一项（开设赌场>聚众赌博>以赌博为业>为赌博提供条件>参与赌博>带彩娱乐）")
    role: Extracted[Role] = Field(default_factory=Extracted,
        description="本人在赌博活动中的角色。多角色并存时选最能代表本人主要获利方式的一项；"
                    "优先级：组织者>抽头者>提供条件者>参赌者；望风者和放贷者独立标注")
    method: Extracted[GamblingMethod] = Field(default_factory=Extracted,
        description="赌博方式。'打牌'默认记为扑克；同一次查处涉及多种方式时选本人实际参与的方式")
    gambling_form: Extracted[GamblingForm] = Field(default_factory=Extracted,
        description="本人参与的这场赌博的组织形式（不是本人的行为类型）。原文写'聚众赌博'，或写明有人组织、召集他人赌博、"
                    "抽头渔利，记聚众赌博；在专门开设的赌场或以赌博为经营的场所，记赌场赌博；原文完整叙述赌博经过且没有"
                    "组织、召集、抽头、开设赌场的任何表述（如亲友邻里自发打牌），可推断为其他；拿不准记未提及")
    times: Extracted[int] = Field(default_factory=Extracted,
        description="赌博或提供条件的次数（场次）。'多次/数次'等无法确定确切次数时值记 null、状态推断")
    duration_days: Extracted[float] = Field(default_factory=Extracted, description="持续时间（天），如'持续三个月'记 90")
    cheating: Extracted[bool] = Field(default_factory=Extracted, description="是否以作弊手段赢取财物（可能转为诈骗）")


class Amounts(BaseModel):
    personal_stake: Extracted[AmountRange] = Field(default_factory=Extracted,
        description="本人的赌资：本人用作赌注、换取筹码的款物及赢取的款物（元）")
    per_bet: Extracted[AmountRange] = Field(default_factory=Extracted, description="单注或每局输赢的金额（元）")
    onsite_stake_total: Extracted[AmountRange] = Field(default_factory=Extracted,
        description="现场查获的赌资合计（元）")
    cumulative_stake: Extracted[AmountRange] = Field(default_factory=Extracted,
        description="累计赌资（元），多次赌博累计")
    commission: Extracted[AmountRange] = Field(default_factory=Extracted,
        description="抽头渔利、头钱、水钱、台费等从赌博中获取的收入（元）。只有台费、场地费时也记在这里，"
                    "但它本身不证明以营利为目的（见 intent.profit_purpose）")
    illegal_gain: Extracted[AmountRange] = Field(default_factory=Extracted, description="其他违法所得（元）")


class Persons(BaseModel):
    participant_count: Extracted[int] = Field(default_factory=Extracted,
        description="参赌人数（同一场次在场参赌的人数，含本人，不含围观者）。'多人/数人'等无法确定确切人数时值记 null、状态推断")
    cumulative_participants: Extracted[int] = Field(default_factory=Extracted, description="累计参赌人数（多场次合计）")
    minors_involved: Extracted[bool] = Field(default_factory=Extracted, description="是否有未成年人参赌")
    civil_servant: Extracted[bool] = Field(default_factory=Extracted, description="本人是否为国家工作人员")
    relatives_only: Extracted[bool] = Field(default_factory=Extracted, description="参与者是否均为亲属")
    abroad_organized_count: Extracted[int] = Field(default_factory=Extracted,
        description="组织中国公民出境赌博的人数")


class Venue(BaseModel):
    venue_type: Extracted[VenueType] = Field(default_factory=Extracted,
        description="赌博场所类型。多场所时选赌博实际发生的主要场所，不选被抓获的场所")


class Intent(BaseModel):
    profit_purpose: Extracted[bool] = Field(default_factory=Extracted,
        description="是否以营利为目的。只记两类依据：原文对本人写明'以营利为目的'或'营利性赌博'，"
                    "或原文写明本人抽头、渔利、收头钱水钱、坐庄获利——都标'明确'为是；本人是场所或条件提供者、"
                    "原文写了现场有抽头头钱但没说谁收的，标'推断'为是；原文写明'不以营利为目的''娱乐消遣'的标'明确'为否。"
                    "赌资或输赢金额大小、赌博方式、被当场查获、只收台费场地费、平台名里的'娱乐'、"
                    "所引法条原文、'构成赌博'等定性用语都不是依据，此时标'未提及'。"
                    "对其他参赌人的营利事实不算本人的")


class Circumstances(BaseModel):
    """修正情节的事实依据。只记事实，是否构成从轻/从重由规范层按适用法律判断。"""
    last_prior_penalty_date: Extracted[date] = Field(default_factory=Extracted,
        description="本人最近一次受治安管理处罚的决定日期；只写到月份时取该月 1 日并标'推断'")
    surrendered: Extracted[bool] = Field(default_factory=Extracted, description="是否主动投案")
    truthful_statement: Extracted[bool] = Field(default_factory=Extracted, description="是否如实陈述违法事实")
    admits_and_accepts: Extracted[bool] = Field(default_factory=Extracted,
        description="是否承认违法事实并愿意接受处罚（认错认罚）")
    remedied_consequence: Extracted[bool] = Field(default_factory=Extracted, description="是否主动消除或减轻违法后果")
    victim_forgiveness: Extracted[bool] = Field(default_factory=Extracted, description="是否取得被侵害人谅解")
    coerced_or_lured: Extracted[bool] = Field(default_factory=Extracted, description="是否出于他人胁迫或诱骗")
    meritorious: Extracted[bool] = Field(default_factory=Extracted, description="是否有立功表现")
    instigated_others: Extracted[bool] = Field(default_factory=Extracted, description="是否教唆、胁迫、诱骗他人参与")
    retaliation: Extracted[bool] = Field(default_factory=Extracted, description="是否对报案人、举报人、证人打击报复")
    obstructed_police: Extracted[bool] = Field(default_factory=Extracted, description="是否阻碍民警执行职务")
    minor_circumstance: Extracted[MinorLevel] = Field(default_factory=Extracted,
        description="原文明确认定的'情节轻微'或'情节特别轻微'（只记原文认定，不自行判断；"
                    "2012 版减轻条件是'特别轻微'，2025 版是'轻微'）")
    first_offense: Extracted[bool] = Field(default_factory=Extracted,
        description="是否初次违反治安管理：本次是第一次被公安机关发现或查处（公通字〔2007〕1号第五项）。"
                    "曾有仍在追究时效内的违法、曾因不满十六周岁不执行拘留、曾经调解结案、"
                    "曾被收容教养或劳动教养、曾被判处刑罚或免除刑事处罚的，都不算初次")
    violations_last_year: Extracted[int] = Field(default_factory=Extracted,
        description="本次行为前一年内违反治安管理的次数")


class Person(BaseModel):
    age: Extracted[int] = Field(default_factory=Extracted,
        description="行为时的周岁年龄。只有出生年份时按 7 月 1 日估算并标'推断'；"
                    "'三十余岁'等模糊表述值记 null、状态推断")
    pregnant_or_nursing: Extracted[bool] = Field(default_factory=Extracted,
        description="是否怀孕或哺乳自己不满一周岁的婴儿")


class CaseMeta(BaseModel):
    """不由 LLM 抽取：来自案件登记信息或人工填写。"""
    region: str | None = Field(default=None, description="行政区划代码（至少到省级，如 330000）")
    behavior_date: date | None = Field(default=None, description="违法行为发生日期（持续行为取结束日）")
    decision_date: date | None = Field(default=None, description="处罚决定日期；预测时为拟决定日期")


class GamblingElements(BaseModel):
    schema_version: str = SCHEMA_VERSION
    meta: CaseMeta = Field(default_factory=CaseMeta)
    conduct: Conduct = Field(default_factory=Conduct)
    amounts: Amounts = Field(default_factory=Amounts)
    persons: Persons = Field(default_factory=Persons)
    venue: Venue = Field(default_factory=Venue)
    intent: Intent = Field(default_factory=Intent)
    circumstances: Circumstances = Field(default_factory=Circumstances)
    person: Person = Field(default_factory=Person)


# 门禁文档 §3.1 的关键字段集 K（冻结后不得删减）
KEY_FIELDS: tuple[str, ...] = (
    "conduct.behavior_type",
    "conduct.role",
    "conduct.method",
    "amounts.personal_stake",
    "amounts.onsite_stake_total",
    "amounts.commission",
    "persons.participant_count",
    "intent.profit_purpose",
    "circumstances.last_prior_penalty_date",
    "person.age",
)

GROUPS = ("conduct", "amounts", "persons", "venue", "intent", "circumstances", "person")


def iter_fields():
    """按 (路径, 中文说明, 值类型) 遍历所有抽取字段。"""
    for group in GROUPS:
        model = GamblingElements.model_fields[group].annotation
        for name, info in model.model_fields.items():
            inner = info.annotation.model_fields["value"].annotation
            yield f"{group}.{name}", info.description or "", inner


def get_field(elements: GamblingElements, path: str) -> Extracted:
    group, name = path.split(".")
    return getattr(getattr(elements, group), name)


def guideline_markdown() -> str:
    rows = ["| 字段 | 说明 | 关键字段 |", "|---|---|---|"]
    for path, desc, _ in iter_fields():
        rows.append(f"| `{path}` | {desc} | {'是' if path in KEY_FIELDS else ''} |")
    return "\n".join(rows)


def json_schema() -> dict:
    """供受限解码使用（Ollama format / XGrammar）。"""
    return GamblingElements.model_json_schema()


def update_doc(path: str) -> None:
    """把字段表写进标注指南中 <!-- schema:begin --> 与 <!-- schema:end --> 之间。"""
    import re
    from pathlib import Path
    doc = Path(path)
    text = doc.read_text("utf-8")
    block = f"<!-- schema:begin -->\n> 由 `schema.py`（v{SCHEMA_VERSION}）自动生成，请勿手改。\n\n{guideline_markdown()}\n<!-- schema:end -->"
    new, n = re.subn(r"<!-- schema:begin -->.*?<!-- schema:end -->", lambda _: block, text, flags=re.S)
    if n != 1:
        raise SystemExit(f"{path} 中没有找到唯一的 schema 标记")
    doc.write_text(new, "utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--json-schema" in sys.argv:
        print(json.dumps(json_schema(), ensure_ascii=False, indent=1))
    elif "--update-doc" in sys.argv:
        update_doc(sys.argv[sys.argv.index("--update-doc") + 1])
    else:
        print(guideline_markdown())
