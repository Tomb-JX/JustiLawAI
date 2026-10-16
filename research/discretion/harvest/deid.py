"""行政案例脱敏（文本处理规范 docs/04-plan/text-processing-spec.md §4.2；D1–D5 按规范 §5 的建议执行，周会结论不同再改）。

做法：在正本 text_full 上找出全部待替换片段（类别有优先级，重叠时保留优先级高的），一次替换并记录位置映射，
把各段（text_facts 等）的起止位置投影到脱敏后的正本上——段落仍是正本的连续子串，标注证据位置可用。
在 text_full 里找不到原样的段（字段式公示拼出来的决定段等）单独脱敏，沿用同一份人名代号表。

人名（D5）：本人 = 甲；其他人按首次出现顺序 乙 丙 丁 戊 己 庚 壬 癸（跳过"辛"，免得和姓氏混淆），第 10 人起"人员10"……
  - 已遮挡写法（李xx、韦*林、王某某）在任何上下文都算人名，但必须以姓氏开头，后面不能紧跟地名用字（"xx村""路*巷"不算）；
  - 真名只在三种语境里认：当事人称谓之后（违法行为人××）、"伙同/纠集××"之后、与已认出的人名并列（"××、××"）；
    以及"××等人赌博案"这类案件名。其余残留交给 R6 扫描（r6_scan.py）的姓名候选人工复核；
  - 同一写法视为同一人；同一列举里出现两次同样的遮挡写法（"蒙**、……、蒙**"）无法区分，标 ambiguous_persons；
  - 当事人称谓之后、与本人同姓的遮挡写法视为本人（清河"被处罚人张xxx"与"违法嫌疑人张xx"）。
年龄（D1，规格 v0.2 §1.6）：明文出生日期 → "行为时N周岁"（按行为日期算；出生或行为日期不到日、算不准是否已过生日的取较小值，
  标 age_uncertain）；已遮挡的出生信息删除。
日期（D2）：正文到月、去掉时分；元数据（behavior_date、decision_date）保留到日。
文号（D3）：正文里的文号换成"〔文号 h:6 位哈希〕"，与交付字段 doc_no_hash（规范化文号 SHA-256 前 16 位）同源；交付文件不写 URL。
不保存原名：deid_map 只记"代号 → 原文位置与长度"，存仓库外。
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "discover"))
from triage import DOC_NO  # noqa: E402

# ---------- 词表 ----------

SURNAMES = set(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭"
    "赖傅洪丘宇糜竺习汝鄂濮钮萧阎庹禤甯隗雒逄邴荀於磨凤郦贝鄞仉滑"
    "陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施文牛樊葛邢安齐易"
    "乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符舒阮柯纪梅童凌毕单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳管柴"
    "蒙鲍华喻祁蒲房滕屈饶解牟艾尤阳穆农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷晏席卫米柏宗瞿桂全佟应臧闵苟邬边卞"
    "姬师仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖巩明佘池查麻苑迟邝官封谈匡鞠惠荆乐冀郁胥南班储原栗燕楚鄢劳谌奚皮粟冼蔺楼盘满"
    "闻位厉伊仝区郜海阚花权强帅屠豆朴盖练廉禹井祖漆巴丰支卿狄计索宣晋相初门云容敬扈晁芮普阙浦戈伏鹿薄邸雍辜羊阿乌母裘"
    "亓修邰赫杭况宿鲜印逯隆茹诸战慕危玉银亢嵇哈湛宾戎勾茅揭干尉冶斯束檀衣展昝智幸奉植衡富尧闭者"
)
COMPOUND_SURNAMES = ("欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙", "慕容", "长孙", "宇文", "司徒", "夏侯",
                     "令狐", "端木", "轩辕", "呼延", "南宫")
ALIASES = ["乙", "丙", "丁", "戊", "己", "庚", "壬", "癸"]
MASK_CH = "xX×＊*ｘＸ"
MASK = r"[xX×＊*ｘＸ]"
# 虚词与称谓用字：不会出现在名字里，用来卡住人名的右边界
FUNC = "在于与和及因被将从到对向为以等的了是系所称均已又也就并而或不其该此之经由把给让已曾自还"
# 地名、机构用字：遮挡写法后面紧跟这些字时是地名（"xx村""区**小区""路*巷"），不是人名
PLACE_AFTER = "省市县区镇乡村屯组街路道巷号楼栋幢单期弄室房小社旗州盟厂店场园部局所院校队"
PLACE_NEXT = "(?:[" + PLACE_AFTER.replace("组", "") + "]|组(?!织|成|长|合))"   # "史某组织"的"组"不是村民小组
SUR = "(?:" + "|".join(COMPOUND_SURNAMES) + "|[" + "".join(sorted(SURNAMES)) + "])"
# 名字用字不收常见动词、公文用字："对姚x行政拘留"里的"行"不是名字
NOT_GIVEN = "行处罚拘给予进参组提开聚利用通使伙纠邀召约违持赢输赌打玩麻牌家"
GIVEN = rf"(?:(?![{FUNC}{PLACE_AFTER}{NOT_GIVEN}])[一-龥])"
# 遮挡写法后接一个名字用字（韦*林、黄*森）时，名字用字后面必须是边界或常见后续字，否则按"姓+遮挡"处理（"戴x询问"）；
# 前面是数字（"三楼xxx"）时不算人名
NAME_END = r"[、，,。；;（(\s和与及等在于因被将从到对向为以的已均也都持赢输家提参共各分先主自又再处罚行给予\d]"
# 真名用字：只排除虚词、紧跟人名的公文动词首字（行政、处以、罚款、拘留、给予）和地名用字；可含"小""华""道""进"
VERB_HEAD = "行处罚拘给予"
GIVEN_REAL = rf"(?:(?![{FUNC}{VERB_HEAD}某省市县区镇乡村屯组街路巷号楼栋室局所院校队部厂店])[一-龥])"
SURCH = "[" + "".join(sorted(SURNAMES)) + "]"
# "姓+名+遮挡"（常文x、莫向*、张纪x）：名字用字也是姓时（"查明覃**"里的"明覃"）只在前面是边界、且只遮一个字时才算三字写法
BOUND = "、，,。；;：:和与及同伙对给由将被人的在是为向把村屯组镇乡家民众犯"
MASKED = (rf"(?<![\d一二三四五六七八九十两])(?:"
          rf"{SUR}{MASK}{GIVEN}(?!{MASK})(?={NAME_END}|$)"
          rf"|{SUR}{MASK}{{1,4}}(?!{MASK})(?!{PLACE_NEXT})"
          rf"|{SUR}(?!{SURCH})(?!{PLACE_NEXT})[一-龥]{MASK}{{1,2}}(?!{MASK})(?!{PLACE_NEXT})"
          rf"|(?:(?<![一-龥])|(?<=[{BOUND}])){SUR}{SURCH}{MASK}(?!{MASK})(?!{PLACE_NEXT})"
          rf"|(?:(?<![市县省镇乡村某])|(?!区)){SUR}某{GIVEN_REAL}(?={NAME_END}|$)|{SUR}(?!{SURCH}){GIVEN_REAL}某(?!某)(?={NAME_END}|$)"
          rf"|(?:(?<![一-龥])|(?<=[{BOUND}])){SUR}{SURCH}某(?!某)(?={NAME_END}|$)"
          # "于某处""在某地"不是人名；"覃某某处以"是
          rf"|(?:(?<![市县省镇乡村某])|(?!区)){SUR}某{{1,2}}(?![日月年时天地些种个人]|{PLACE_NEXT}|处(?![以罚理])|司法|公司|单位|机关|医院|学校|中心))")
REAL = rf"{SUR}{GIVEN_REAL}{{1,2}}"
NAME = rf"(?:{MASKED}|[一-龥]{{1,6}}·[一-龥]{{1,6}}|{REAL})"
SUBJECT_ROLES = ("违法行为人", "违法嫌疑人", "被处罚人", "违法人")
ROLES = (r"违法行为人|违法嫌疑人|被处罚人|违法人|行政处罚对象|处罚对象|行政相对人名称|行政相对人|当事人|同案人|申请人"
         r"|受害人|被害人|被侵害人|证人|报案人|举报人|旅客")
AFTER_NAME = r"(?=\s*(?:[，,。；;（(\s、男女于因等不和与及对在系的将从被为:：已均也都共各分先一\d]|给予|处以|行政拘留|罚款|警告|$))"
# 称谓后：遮挡写法自带边界，直接认；真名要后面跟边界；其余写法（少数民族姓等）只在逗号、括号或处罚动词前认
ROLE_NAME = re.compile(rf"(?<!被)(?:{ROLES})\s*[:：]?\s*(?:(?P<name>{MASKED})|(?P<real>[一-龥]{{1,6}}·[一-龥]{{1,6}}|{REAL}){AFTER_NAME}"
                       rf"|(?P<other>[一-龥]{{2,4}}?)(?=[，,（(]|处以|处行政|行政拘留|罚款|给予))")
CASE_LINE_NAME = re.compile(rf"\n[^\n]{{2,30}}案\s*\n\s*(?P<name>{NAME})\s*\n")
PERSON_LINE = re.compile(rf"(?:^|\n)\s*(?P<name>{NAME})\s*[,，]\s*[男女]\s*[,，]")
CUE_NAME = re.compile(rf"(?:伙同|纠集|邀约|召集|约同|邀请|联系)\s*(?P<name>{NAME}){AFTER_NAME}")
CASE_NAME = re.compile(rf"(?:^|(?<=[\s：:\d.、]))(?P<name>{NAME})(?=(?:、[^\s，。、]{{1,6}}){{0,5}}(?:等人|等[\d一二三四五六七八九十]+人)?"
                       r"(?:涉嫌)?(?:为赌博提供条件|参与赌博|聚众赌博|赌博|开设赌场))")
EVID_NAME = re.compile(rf"(?:(?<=^)|(?<=[、，,和与及有：:.．\s\d]))(?P<name>{REAL})(?=(?:等人?)?(?:的+|在其)?(?:陈述|供述|询问|笔录|申辩|辨认|证言|证实|证人|身份证|身份信息))")
TIME_NAME = re.compile(rf"(?<=[午上晚间许日月]，)(?P<name>{REAL})(?=在|于|伙同|与|和|、|等|驾驶|通过|利用|以)")  # "2022年10月下午，奚少俊在……"
KIN_NAME = re.compile(rf"(?P<name>{REAL})(?=的?(?:女儿|儿子|妻子|丈夫|父亲|母亲|哥哥|弟弟|姐姐|妹妹|侄子|家中|家里|家))")
DOTTED = re.compile(r"(?<![一-龥])?[一-龥]{2,5}·[一-龥]{2,6}")  # 少数民族姓名（艾某·某某）
ROLE_VERB_NAME = re.compile(rf"(?<=由)(?P<name>{REAL})(?=提供|组织|负责|召集|经营|出资|开设|望风|放哨)")  # "由房友明提供的"
PAREN_NAME = re.compile(rf"(?:笔录|传唤证|回执|告知书|通知书|证明|辨认)[（(](?P<name>{REAL})[)）]")
LINE_NAME = re.compile(rf"(?m)^\s*(?P<name>{REAL})\s*$")      # 按列排版的公开表：姓名独占一行
OBJ_NAME = re.compile(rf"(?<=对)(?P<name>{REAL})(?=的)")       # "对韩宗红的违法所得""对陶明的行为"
VERB_NAME = re.compile(rf"(?:(?<=决定对)|(?<=现对)|(?<=给予)|(?<=予以)|(?<=决定给予)|(?<=[、，,；;对]))\s*(?P<name>{NAME}|[一-龥]{{3}})"
                       r"(?=处以|行政拘留|罚款|警告|给予|作出|予以|进行)")
SEP = r"\s*[、，,和与及]\s*"
STATION_STOP = "到去回至往送赴在于向从被由将对把给让经"   # 派出所名前的动词、介词（"传唤至派出所""到栎社机场派出所"）
CHAIN_SEP = r"\s*[、和与及]\s*"   # 并列扩展只认顿号和连词（逗号后面常是别的成分，"23时18分左右，严某某"）
STOP_WORDS = {
    "陈述", "申辩", "申请", "于是", "向其", "高额", "金额", "金钱", "万元", "方式", "方法", "明知", "明确", "安排", "车辆", "房间",
    "包房", "包间", "包厢", "门口", "门前", "关于", "任何", "程序", "成员", "白天", "常住", "平台", "全部", "应当", "原处", "计算",
    "支付", "付款", "余额", "时间", "华为", "文化", "江湖", "林地", "马上", "龙虎", "黄赌", "牛牛", "苏州", "云南", "海南", "宁夏",
    "广西", "山东", "江苏", "毛南", "罗列", "单位", "单独", "司法", "公安", "公民", "民警", "群众", "他人", "家中", "本人", "同案",
    "朋友", "亲属", "夫妻", "兄弟", "村民", "老板", "店主", "房主", "组长", "参赌", "赌博", "麻将", "扑克", "人员", "罚款", "拘留",
    "收缴", "赌资", "以下", "以上", "当日", "次日", "同日", "期间", "等人", "该处", "此处", "一起", "共同", "伙同", "笔录", "供述",
    "证言", "家属", "其他", "其中", "上述", "现场", "网络", "手机", "微信", "金花", "牌九", "斗牛", "三公", "推筒", "百家",
    "鲁莽", "毕业", "党员", "严重", "从轻", "从重", "减轻", "宣告", "解除", "管理", "管辖", "简易", "查获", "查明", "查处", "查实",
    "温州", "武汉", "长沙", "南宁", "南京", "合肥", "昆明", "贵阳", "成都", "石家", "保定", "邯郸", "邢台", "沧州", "衡水", "廊坊",
    "钱款", "钱财", "储蓄", "祁门", "相关", "相应", "相同", "初次", "初中", "高中", "小学", "大学", "曾经", "曾因", "强制", "强行",
    "通过", "通知", "方便", "安全", "安装", "习惯", "苗族", "汉族", "回族", "壮族", "满族", "瑶族", "彝族", "侗族", "傣族", "白族",
}


@dataclass
class Span:
    start: int
    end: int
    repl: str
    cat: str
    prio: int


@dataclass
class DeidResult:
    text: str
    spans: list[Span]
    persons: dict[str, str]          # 原写法 → 代号（只在内存里，不落盘）
    ambiguous_persons: bool
    subject: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    cleanup: list[Span] = field(default_factory=list)   # 第二步：删掉替换后留下的"，，""， 。"（位置相对第一步结果）
    age_uncertain: bool = False                          # 出生或行为日期不到日、算不准是否已过生日（取较小值）
    subject_variants: int = 0                            # 推断为本人的其他写法个数（>0 时复核看一眼）

    @staticmethod
    def _shift(spans: list[Span], pos: int, is_end: bool) -> int:
        delta = 0
        for s in spans:
            if s.end <= pos:
                delta += len(s.repl) - (s.end - s.start)
            elif s.start < pos < s.end:
                return s.start + delta + (len(s.repl) if is_end else 0)
            else:
                break
        return pos + delta

    def project(self, pos: int, *, is_end: bool) -> int:
        """原文位置 → 脱敏后位置。落在替换片段内部时，起点映射到片段新起点、终点映射到片段新终点。"""
        return self._shift(self.cleanup, self._shift(self.spans, pos, is_end), is_end)

    def deid_map(self) -> list[list]:
        """代号 → 原文位置与长度（不含原名），供复核。"""
        return [[s.repl, s.start, s.end - s.start] for s in self.spans if s.cat == "person"]


# ---------- 工具 ----------

def doc_no_norm(doc_no: str) -> str:
    """规格 v0.2 §1.1：去空白、统一括号（年份括号一律"〔〕"，其余圆括号一律"（）"）。"""
    s = re.sub(r"\s", "", doc_no or "")
    s = re.sub(r"[〔\[［【(（](20\d{2})[〕\]］】)）]", r"〔\1〕", s)
    return s.translate(str.maketrans({"(": "（", ")": "）", "[": "〔", "]": "〕", "［": "〔", "］": "〕", "【": "〔", "】": "〕"}))


def doc_no_hash(doc_no: str) -> str:
    """交付字段 doc_no_hash：规范化文号的 SHA-256 前 16 位。"""
    return hashlib.sha256(doc_no_norm(doc_no).encode("utf-8")).hexdigest()[:16]


def doc_hash(doc_no: str) -> str:
    """正文占位"〔文号 h:××××××〕"用的 6 位：与 doc_no_hash 同源，取前 6 位。"""
    return doc_no_hash(doc_no)[:6]


def age_at(birth: date, when: date) -> int:
    return when.year - birth.year - ((when.month, when.day) < (birth.month, birth.day))


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1) - date.resolution) if 1 <= m <= 12 else date(y, 12, 31)


def age_range(y: int, m: int | None, d: int | None, behavior: date, behavior_has_day: bool) -> tuple[int, int]:
    """出生日期与行为日期不到日时可能的周岁范围（最小, 最大）。"""
    births = [date(y, m, d)] if m and d else ([date(y, m, 1), _month_end(y, m)] if m else [date(y, 1, 1), date(y, 12, 31)])
    whens = [behavior] if behavior_has_day else [date(behavior.year, behavior.month, 1), _month_end(behavior.year, behavior.month)]
    ages = [age_at(b, w) for b in births for w in whens]
    return min(ages), max(ages)


def parse_meta_date(s: str) -> date | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def is_masked(tok: str) -> bool:
    return bool(re.fullmatch(MASKED, tok))


def looks_like_name(tok: str, *, lenient: bool = False) -> bool:
    """lenient：紧跟在当事人称谓后面的写法，不要求以常见姓氏开头（少数民族姓"者""阿"等）。"""
    tok = re.sub(r"\s", "", tok or "")
    if not tok or tok in STOP_WORDS or tok[:2] in STOP_WORDS:
        return False
    if is_masked(tok) or "·" in tok:
        return True
    if re.search(rf"某|{MASK}", tok):
        return False
    # 称谓后的写法只排除虚词（真名可能含"镇""村"等字，如"谢镇文"）；其余语境还要排除地名、公文用字
    bad = rf"[{FUNC}人员元款月年]" if lenient else rf"[{FUNC}{VERB_HEAD}省市县区镇乡村屯组街路巷号楼栋室局所院校队部厂店旗盟州警机人员元款月年]"
    if not re.fullmatch(r"[一-龥]{2,4}", tok) or re.search(bad, tok[1:]):
        return False
    if any(tok.startswith(c) for c in COMPOUND_SURNAMES):
        return 3 <= len(tok) <= 4
    if len(tok) == 4:
        return False
    return tok[0] in SURNAMES or (lenient and tok[0] not in FUNC)


NON_NAME = "证言资表记录赌罚款元笔书物具据单照片场博牌机钱币局所员警"


def lenient_ok(tok: str) -> bool:
    """顿号列举里的三字写法（"摆文清""谢镇华"）：不要求常见姓开头，但不能含公文、赌博用字。"""
    return looks_like_name(tok, lenient=True) and not re.search(rf"[{NON_NAME}某]|{MASK}", tok)


# ---------- 识别各类片段 ----------

def _strip_lead(prefix: str) -> tuple[str, str]:
    """场所、地名前面带的虚词（"在""到""被"）不替换。"""
    core = re.sub(rf"^(?:位于|住在|前往|来到|回到|到达|[{FUNC}到去回至往送赴])+", "", prefix)
    return prefix[: len(prefix) - len(core)], core


GENERIC = {"该", "此", "其", "本", "一", "这", "那", "某", "无名", "自家", "自己", "小型", "一家", "一间", "辖区", "当地", "属地",
           "所在地", "我", "各", "附近", "就近", "管辖", "农", "山", "城", "乡", "同", "邻", "全", "外", "道", "公", "思", "网",
           "线", "套", "出", "门", "马", "铁", "上", "逛", "大", "小", "新", "老", "大型", "临时", "流动", "地下", "隐蔽", "上述",
           "涉案", "涉赌", "多个", "多家", "附近的", "周边", "镇上", "村里"}
STOP_WORDS |= {"左右", "周边", "房屋", "房内", "车内", "车上", "门店", "门市", "前后", "上下", "高低", "多少", "早晚", "东西", "南北",
               "江边", "海边", "山上", "田间", "林间", "路边", "路上", "街边", "曾因", "宋体", "黑体", "楷体", "解读", "母亲",
               "母女", "岳父", "岳母", "房东", "师傅", "师父", "阿姨", "阿婆", "阿公", "许多", "明显", "原告", "被告", "印送", "全家",
               "农家", "邻居", "商户", "党员", "干部", "成年", "未成", "孙子", "孙女", "其父", "其母", "众多", "印证", "幸福",
               "何来", "关切", "解释", "常委", "关心", "关注", "关系", "明白", "明天", "明日", "高兴", "方面", "左边", "右边",
               "宣布", "申诉", "相当", "原物", "原件", "原则", "原因", "原来", "原本", "原审", "原告", "车主", "房主", "意见",
               "作出", "况且", "储存", "周岁", "张半", "张筹", "毛钱", "米东", "农民", "项规"}


def _place(kind_group: int = 2):
    def f(m):
        lead, core = _strip_lead(m.group(1))
        if not core or core in GENERIC or core.endswith(("的", "个", "农")):
            return None
        # 名称里带遮挡（"知麻x麻将馆"）时地点优先于人名，免得"麻x"被当成人
        return (lead + "某" + m.group(kind_group), 9) if re.search(rf"{MASK}|某", core) else lead + "某" + m.group(kind_group)
    return f


def find_spans(text: str, *, behavior: date | None, behavior_has_day: bool = True,
               flags: dict | None = None) -> list[Span]:
    spans: list[Span] = []
    flags = flags if flags is not None else {}

    def add(pattern: str, repl, cat: str, prio: int, flags=0):
        for m in re.finditer(pattern, text, flags):
            r = repl(m) if callable(repl) else repl
            if isinstance(r, tuple):
                r, p = r
            else:
                p = prio
            if r is not None:
                spans.append(Span(m.start(), m.end(), r, cat, p))

    clause = r"(?:(?<=^)|(?<=[，,。；;\n：:\s]))"
    # 1 证件号、电话、银行卡、账号、车牌、邮箱（连同标签一起删）
    add(r"(居民身份证(?:号码|编号|号)?|公民身份号码|身份证(?:号码|编号|号)?|证件号码?|证件编号)\s*[:：为是]?\s*[0-9Xx*×＊]{6,18}",
        "", "id", 10)
    add(rf"(?<![\dA-Za-z])\d{{17}}[\dXx](?![\dA-Za-z])|(?<![\dA-Za-z])\d{{15}}(?![\dA-Za-z])"
        rf"|(?<![\dA-Za-z]){{0}}\d{{1,6}}{MASK}{{3,14}}\d{{1,4}}[Xx]?(?![\dA-Za-z])|(?<![\dA-Za-z])\d{{2,6}}{MASK}{{6,}}"
        rf"|{MASK}{{6,}}", "", "id", 10)
    add(r"(联系电话|电话|手机号?码?)\s*[:：为是]?\s*1[3-9]\d{9}|(?<!\d)1[3-9]\d{9}(?!\d)", "", "phone", 10)
    add(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)", "", "phone", 10)
    add(rf"(?:[（(]\s*)?(银行卡号?|银行账号|卡号|卡{MASK}|账号|帐号|微信号|支付宝账?号|QQ号?|附言|缴款码|缴款编号|交易流水号|流水号|订单号)\s*[:：为是]?\s*[（(]?[\w*×＊]{{3,}}[)）]?(?:\s*[)）])?",
        "", "bank", 10)
    add(r"(?<!\d)\d{16,19}(?!\d)", "", "bank", 10)
    add(rf"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][·\s]?[A-Z0-9{MASK_CH}]{{5,6}}", "", "plate", 10)
    add(r"[\w.-]+@[\w-]+\.[\w.]+", "", "email", 10)

    # 2 户籍、住址、工作单位、民族、文化程度（整项删；工作单位里有公职身份的保留类别）
    add(clause + r"(户籍所在地|户籍地址?|户籍|户口所在地|籍贯|出生地|现住址|现住地|现住|现居住地|居住地|住址|住所地|住所|家住|地址)"
        r"\s*[:：为是在]?(?:(?!违法行为人|被处罚人|违法嫌疑人)[^，,。；;\n]){0,60}", "", "address", 10)
    add(r"(?<![\d-])\d{1,4}-\d{1,4}-\d{1,4}(?![\d-])", "", "house", 10)  # 楼栋-单元-房号（"2-1-2"）

    def work(m):
        if re.search(r"国家机关|机关|政府|公务员|公职|事业单位|公安|派出所|法院|检察院", m.group(0)):
            return "身份：公职人员"
        return ""
    add(clause + r"(工作单位|单位)\s*[:：为是]?[^，,。；;\n]{0,30}", work, "work", 10)
    add(clause + r"(民族|文化程度)\s*[:：为是]?[^，,。；;\n]{0,10}", "", "ethnic", 10)
    add(r"(?<=[，,])\s*[一-龥xX×*]{1,4}族(?=[，,。])", "", "ethnic", 10)
    add(r"(?<=[，,])\s*[一-龥xX×*]{1,4}文化(程度)?(?=[，,。])", "", "edu", 10)
    add(rf"(?<=[，,])\s*{MASK}{{1,5}}(?=[，,。；;])", "", "mask", 10)  # 整项遮挡的残片（"，xx。"）

    # 3 出生日期（D1）、遮挡的年龄
    def birth(m):
        if not behavior:
            return ""
        # 规格 v0.2 §1.6：出生或行为日期不到日、算不准是否已过生日的，取较小值并标 age_uncertain
        g = m.groupdict()
        try:
            lo, hi = age_range(int(g["y"]), int(g["m"]) if g.get("m") else None, int(g["d"]) if g.get("d") else None,
                               behavior, behavior_has_day)
        except ValueError:
            return ""
        if lo != hi:
            flags["age_uncertain"] = True
        return f"行为时{lo}周岁"
    add(r"(?:出生(?:日期|年月)\s*[:：为是]?\s*)?(?P<y>(?:19|20)\d{2})\s*年\s*(?:(?P<m>\d{1,2})\s*月\s*(?:(?P<d>\d{1,2})\s*日)?)?"
        r"\s*(?:出生|生)(?![活产效意])", birth, "birth", 9)
    add(r"出生(?:日期|年月)\s*[:：为是]?\s*(?P<y>(?:19|20)\d{2})\s*年\s*(?:(?P<m>\d{1,2})\s*月\s*(?:(?P<d>\d{1,2})\s*日)?)?",
        birth, "birth", 9)
    add(rf"[\d{MASK_CH}]{{2,4}}\s*年\s*[\d{MASK_CH}]{{1,2}}\s*月\s*(?:[\d{MASK_CH}]{{1,2}}\s*日)?\s*(?:出生|生)(?![活产效意])",
        lambda m: "" if re.search(MASK, m.group(0)) else None, "birth", 9)
    add(rf"(?P<y>(?:19|20)\d{{2}})\s*年\s*{MASK}+(?:\s*月\s*{MASK}*\s*日?)?\s*(?:出生|生)(?![活产效意])", birth, "birth", 10)
    add(rf"(年龄\s*[:：]?\s*)?{MASK}{{1,3}}\s*岁", "", "birth", 9)

    # 4 民警、执法人员姓名与警号；派出所名（多含乡镇名）
    def officer(m):
        names = re.split(r"[、和]", m.group("names"))
        return m.group(1) if all(looks_like_name(n) for n in names) else None
    add(rf"(民警|警官|辅警|执法人员|办案人员|办案民警|承办人)\s*[:：]?\s*(?P<names>{NAME}(?:[、和]{NAME})*)"
        r"(?:\s*[（(]?\s*(?:警号|执法证号|执法证)?\s*[:：]?\s*\d{4,}\s*[)）]?)?(?=[、，,。在于对到将向从并送押带执前赶依现当立]|$)", officer, "officer", 9)
    add(r"(警号|执法证号|执法证编号)\s*[:：]?\s*\d+", "", "officer", 9)
    add(clause + r"(法定代表人|负责人|委托代理人|代理人|委托人)\s*[:：]\s*[^，,。；;\n]{0,20}(?:[，,]\s*[^，,。；;\n]{0,10})?",
        "", "officer", 9)
    add(rf"([^\s，,。；;、：:（）()“”\"\d局旗县省{STATION_STOP}]{{1,8}}?)派出所",
        lambda m: _place()(re.match(r"(.*)(派出所)", m.group(0))),
        "station", 9)

    # 5 文号（D3）：所有文号都换（引用的原处罚文号也换，便于跨案例关联而不暴露原号）
    for m in DOC_NO.finditer(text):
        spans.append(Span(m.start(1), m.end(1), f"〔文号 h:{doc_hash(m.group(1))}〕", "docno", 7))
    add(rf"[（(〔\[［【]\s*20\d{{2}}\s*[)）〕\]］】]\s*(?:第\s*)?[\d{MASK_CH}]{{1,6}}\s*号"
        rf"|[（(]\s*20\d{{2}}\s*[)）][一-龥]{{1,2}}\d{{0,4}}[一-龥]{{1,4}}\d+号",
        lambda m: f"〔文号 h:{doc_hash(m.group(0))}〕", "docno", 6)
    add(rf"(?:(?![的了在于对为由经依据之是向及与和号作出])[一-龥（）()]){{0,12}}[〔\[［【]\s*20\d{{2}}\s*[〕\]］】]\s*[\d{MASK_CH}]{{2,8}}"
        rf"(?![\d{MASK_CH}]|\s*号)",
        lambda m: f"〔文号 h:{doc_hash(m.group(0))}〕", "docno", 6)
    add(rf"(?<![\dA-Za-z])\d{{1,6}}{MASK}{{3,5}}(?![\d{MASK_CH}.]*[元.\d])", "", "id", 10)

    # 6 地点：乡镇村以下、门牌、店名、路名
    venue = (r"棋牌娱乐室|棋牌娱乐|棋牌社|棋牌室|棋牌馆|麻将馆|麻将室|茶楼|茶馆|茶室|宾馆|酒店|旅馆|旅社|商店|超市|饭店|餐馆|网吧|足浴店|游戏厅|电玩城|商行|养殖场"
             r"|厂房|台球厅|台球室|KTV|歌厅|会所|娱乐城|娱乐室|活动室|烧烤店|小卖部|便利店|理发店|洗车店|加工厂|民宿|农家乐"
             r"|鱼塘|服务部|经营部|副食店|水果店|五金店|小吃店|酒吧|洗浴中心|浴池|厂")
    nop = r"\s，,。；;、：:（）()“”\"\d的日月年时分内外到至往向从在于和与及被将为对等局"
    add(rf"([^{nop}县市区省镇乡村街路号旗]{{1,10}}?)({venue})", _place(), "venue", 5)
    add(rf"([^{nop}县市区省镇乡村街路号旗州盟组]{{1,8}}?)"
        r"(乡|镇|街道|社区|小区|村委会|村民委员会|行政村|村|嘎查|苏木|屯|农场|林场)(?![民委商信合])", _place(), "place", 5)
    add(rf"([^{nop}县市区省镇乡村号旗]{{1,8}}?)(大道|大街|路|街|巷|胡同)(?![费过人线程径道头面上坊])",
        _place(), "road", 5)

    def house(m):
        before = text[max(0, m.start() - 1): m.start()]
        after = text[m.end(): m.end() + 2]
        if before == "第" or re.match(r"令|文件|公告|文|决定", after):
            return None
        return "某" + m.group(1)
    add(rf"[\d{MASK_CH}]+\s*(号楼|号院|号|栋|幢|单元|室|组)", house, "house", 5)

    # 7 日期与时分（D2）
    def ymd(m):
        mo = m.group(2)
        return f"{m.group(1)}年{int(mo)}月" if mo.isdigit() else f"{m.group(1)}年"
    add(rf"(\d{{4}})\s*年\s*(\d{{1,2}}|{MASK}{{1,2}})\s*月\s*(?:\d{{1,2}}|{MASK}{{1,2}})\s*日", ymd, "date", 4)
    add(r"([〇○零一二三四五六七八九]{4})年([一二三四五六七八九十]{1,2})月[一二三四五六七八九十]{1,3}日",
        lambda m: f"{m.group(1)}年{m.group(2)}月", "date", 4)
    add(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?(?!\d)",
        lambda m: f"{m.group(1)}年{int(m.group(2))}月", "date", 4)
    add(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)", lambda m: f"{m.group(3)}年{int(m.group(1))}月", "date", 4)
    add(r"(?<!\d)(\d{1,2})\s*月\s*\d{1,2}\s*日", lambda m: f"{int(m.group(1))}月", "date", 4)  # "同年5月9日"也要到月
    add(rf"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜间)?\s*(?:\d{{1,2}}|{MASK}{{1,2}})\s*[时点](\s*(?:\d{{1,2}}|{MASK}{{1,2}})\s*分)?"
        rf"(许|左右|{MASK}{{1,2}})?", lambda m: m.group(1) or "", "time", 3)
    add(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)", "", "time", 3)
    add(r"([零一二三四五六七八九十]{1,3})时(许|左右)", "", "time", 3)
    return spans


# ---------- 人名 ----------

def find_subject(text: str) -> str | None:
    for m in ROLE_NAME.finditer(text):
        tok = re.sub(r"\s", "", m.group("name") or m.group("real") or m.group("other"))
        if looks_like_name(tok, lenient=True):
            return tok
    for rx in (PERSON_LINE, CASE_LINE_NAME, CASE_NAME):  # "许某某,女,"；列表"××等人赌博案"下一行的姓名；结果表只有案件名
        m = rx.search(text)
        if m and looks_like_name(m.group("name")):
            return m.group("name")
    return None


def person_candidates(text: str, subject: str | None, seed: dict[str, str] | None = None
                      ) -> tuple[list[tuple[int, int, str]], set[str]]:
    """人名候选位置 (起, 止, 写法) 与视为本人的其他写法。代号在去重叠之后再按出现顺序编。"""
    tokens: set[str] = set(seed or {})
    if subject:
        tokens.add(subject)
    same_as_subject: set[str] = set()
    pure = rf"{SUR}(?:{MASK}+|某+)"
    same_sur = {m.group(0) for m in re.finditer(pure, text)} if subject else set()
    role_toks = {re.sub(r"\s", "", m.group("name") or m.group("real") or m.group("other")) for m in ROLE_NAME.finditer(text)
                 if m.group(0).startswith(SUBJECT_ROLES)}
    for m in ROLE_NAME.finditer(text):
        tok = re.sub(r"\s", "", m.group("name") or m.group("real") or m.group("other"))
        if looks_like_name(tok, lenient=True):
            tokens.add(tok)
            # 本人称谓后、与本人同姓的另一种纯遮挡写法（"被处罚人张xxx"与"违法嫌疑人张xx"）视为本人；
            # 文中同姓的纯遮挡写法超过两种（环江一案多人同姓"韦*""韦**"）就不合并
            if (subject and tok != subject and re.fullmatch(pure, tok) and re.fullmatch(pure, subject)
                    and tok[0] == subject[0] and m.group(0).startswith(SUBJECT_ROLES)
                    and len({t for t in same_sur if t[0] == subject[0]}) <= 2 and len(role_toks) <= 2):
                same_as_subject.add(tok)
    rxs = [PERSON_LINE, CUE_NAME, CASE_NAME, VERB_NAME, OBJ_NAME, EVID_NAME, KIN_NAME, TIME_NAME, PAREN_NAME, ROLE_VERB_NAME]
    if "姓名" in text:
        rxs.append(LINE_NAME)
    for rx in rxs:
        for m in rx.finditer(text):
            tok = m.group("name")
            # 处罚列举里"、谢镇华行政拘留"：三字写法可含地名用字
            if looks_like_name(tok) or (rx is VERB_NAME and len(tok) == 3 and text[m.start() - 1: m.start()] in ("、", "；", ";")
                                        and lenient_ok(tok)):
                tokens.add(tok)
    tokens |= {m.group(0) for m in DOTTED.finditer(text) if not re.search(r"[县市省区委政府局院所厅部]", m.group(0))}
    # 本人是遮挡写法、正文里又漏出同姓真名（"尹某某"与"尹大明在……"）：视为本人
    if subject and re.fullmatch(pure, subject):
        leak = {m.group(0) for m in re.finditer(rf"{re.escape(subject[0])}{GIVEN_REAL}{{1,2}}(?=[在于因与和、，,等伙被的])", text)
                if looks_like_name(m.group(0)) and m.group(0) not in tokens}
        tokens |= leak
    # 遮挡写法逐位置尝试（允许重叠："张纪x"与"纪x"、"区丁**"与"丁**"都留作候选，去重叠时按优先级与长度取舍）
    masked_rx = re.compile(MASKED)
    masked_hits = [(m.start(), m.end(), m.group(0)) for i, ch in enumerate(text)
                   if ch in SURNAMES or text.startswith(COMPOUND_SURNAMES, i)
                   for m in [masked_rx.match(text, i)] if m]
    tokens |= {t for _, _, t in masked_hits}
    # 与已认出的人名并列的名字（"王五、李四"），反复扩展到不再增加；顿号列举里的三字写法可不以常见姓开头（"摆文清"）
    nxt_rx = re.compile(rf"{CHAIN_SEP}(?P<name>{REAL}|[一-龥]{{3}}){AFTER_NAME}")
    prv_rx = re.compile(rf"(?P<name>{REAL}|[一-龥]{{3}}){CHAIN_SEP}$")
    while tokens:
        alt = "|".join(sorted(map(re.escape, tokens), key=len, reverse=True))
        new = set()
        for k in re.finditer(alt, text):  # 每个已知人名前后各看一个并列项（不用一次 finditer，免得并列项被前一个匹配吃掉）
            for mm in (nxt_rx.match(text, k.end()), prv_rx.search(text[max(0, k.start() - 8): k.start()])):
                if not mm or mm.group("name") in tokens:
                    continue
                tok = mm.group("name")
                if looks_like_name(tok) or (len(tok) == 3 and "、" in mm.group(0) and lenient_ok(tok)):
                    new.add(tok)
        if not new:
            break
        tokens |= new
    # 本人是纯遮挡写法时，文中唯一一个同姓真名（"尹某某"与"尹大明"）、唯一一个同姓的另一种纯遮挡写法（"张xxx"与"张xx"，
    # 且两者从不并列出现）视为本人。只是推断，DeidResult.subject_variants 记合并了几种写法，供复核
    if subject and re.fullmatch(pure, subject):
        reals = {t for t in tokens if t[0] == subject[0] and not is_masked(t) and "·" not in t}
        if len(reals) == 1:
            same_as_subject |= reals
        variants = {t for t in tokens if t != subject and t[0] == subject[0] and re.fullmatch(pure, t)}
        if len(variants) == 1 and len(role_toks) <= 2:
            v = next(iter(variants))
            if not re.search(rf"{re.escape(v)}{SEP}{re.escape(subject)}(?!{MASK})|{re.escape(subject)}{SEP}{re.escape(v)}(?!{MASK})", text):
                same_as_subject.add(v)
    # 位置：遮挡写法用正则扫描结果（"韦*"与"韦*林"不混），其余写法找全部出现
    found = list(masked_hits)
    for t in tokens:
        if not is_masked(t):
            found += [(m.start(), m.end(), t) for m in re.finditer(re.escape(t), text)]
    return found, same_as_subject


def number_persons(text: str, pspans: list[Span], subject: str | None, same_as_subject: set[str],
                   seed: dict[str, str] | None) -> tuple[dict[str, str], bool]:
    """去重叠后剩下的人名片段按出现顺序编代号（repl 里暂存写法，就地换成代号）。"""
    persons: dict[str, str] = dict(seed or {})
    if subject:
        persons.setdefault(subject, "甲")
    for t in same_as_subject:
        persons.setdefault(t, "甲")
    used = set(persons.values())
    toks = [s.repl for s in pspans]
    for s in pspans:
        tok = s.repl
        if tok not in persons:
            n = len({v for v in persons.values() if v != "甲"})
            alias = ALIASES[n] if n < len(ALIASES) else f"人员{n + 2}"
            while alias in used:
                n += 1
                alias = ALIASES[n] if n < len(ALIASES) else f"人员{n + 2}"
            persons[tok] = alias
            used.add(alias)
        s.repl = persons[tok]
    # 同一列举里同一个纯遮挡写法出现两次：无法区分
    ambiguous, i = False, 0
    while i < len(pspans) and not ambiguous:
        j = i + 1
        while j < len(pspans) and re.fullmatch(SEP + r"|\s*", text[pspans[j - 1].end: pspans[j].start]):
            j += 1
        run = toks[i:j]
        ambiguous = any(run.count(t) > 1 and re.search(rf"{MASK}$|某$", t) for t in run)
        i = j
    return persons, ambiguous


def resolve(spans: list[Span]) -> list[Span]:
    """去重叠：优先级高的先占位；同优先级先长后短。"""
    chosen: list[Span] = []
    for s in sorted(spans, key=lambda x: (-x.prio, -(x.end - x.start), x.start)):
        if s.end <= s.start:
            continue
        if all(s.end <= c.start or s.start >= c.end for c in chosen):
            chosen.append(s)
    return sorted(chosen, key=lambda x: x.start)


def deidentify(text: str, *, subject: str | None = None, behavior: date | None = None, behavior_has_day: bool = True,
               persons: dict[str, str] | None = None) -> DeidResult:
    """persons：沿用另一段文本的代号表（单独脱敏的段落、标题）；subject 为空时自动找本人。
    behavior_has_day：行为日期是否到日（只到月时年龄按当月首尾两种情况算范围）。"""
    if subject is None and not persons:
        subject = find_subject(text)
    if subject is None and persons:
        subject = next((t for t, a in persons.items() if a == "甲"), None)
    found, same = person_candidates(text, subject, persons)
    flags: dict = {}
    spans = resolve(find_spans(text, behavior=behavior, behavior_has_day=behavior_has_day, flags=flags)
                    + [Span(a, b, t, "person", 8) for a, b, t in found])
    pmap, ambiguous = number_persons(text, [x for x in spans if x.cat == "person"], subject, same, persons)
    mid = apply(text, spans)
    # 第二步：整项删除后留下的空项（"男， ，。""：，"），只在删过东西的地方附近清理
    touched, delta = set(), 0
    for s in spans:
        if not s.repl:
            touched.add(s.start + delta)
        delta += len(s.repl) - (s.end - s.start)
    cleanup = [Span(m.start(), m.end(), "", "cleanup", 0) for m in CLEAN.finditer(mid)
               if any(abs(m.start() - t) <= 3 or abs(m.end() - t) <= 3 for t in touched)]
    counts: dict[str, int] = {}
    for s in spans:
        counts[s.cat] = counts.get(s.cat, 0) + 1
    return DeidResult(apply(mid, cleanup), spans, pmap, ambiguous, subject, counts, cleanup,
                      age_uncertain=bool(flags.get("age_uncertain")) and any(s.cat == "birth" and s.repl for s in spans),
                      subject_variants=len(same))


CLEAN = re.compile(r"(?<=[。；;\n])[ \t　 ]*[，,]|[ \t　 ]*[，,](?=[ \t　 ]*[，,。；;])|(?<=[：:，,])[ \t　 ]+|[ \t　 ]+(?=[，,。；;])")


def apply(text: str, spans: list[Span]) -> str:
    out, pos = [], 0
    for s in spans:
        out.append(text[pos:s.start])
        out.append(s.repl)
        pos = s.end
    out.append(text[pos:])
    return "".join(out)
