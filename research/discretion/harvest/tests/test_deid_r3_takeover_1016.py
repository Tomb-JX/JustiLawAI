"""2026-10-16 r3 接管修复的回归测试（qa/r1-content-qa 四件已证实泄漏 + R6 23 个软候选复核结论）：
复议申请人位真名（"姓名不服"）、括号注记列举（"××（微信名：×某）、××"）、顿号列举真名连排、
证据列举夹项、"姓名在×市"语境、"等N人采用"、部分遮挡本人合并、表格续行后的顿号列举。
合成样例，姓名为虚构。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import deidentify  # noqa: E402
from r6_scan import load_whitelist, scan_text  # noqa: E402

WL = load_whitelist()


def hard_cats(text: str) -> set[str]:
    return {h.cat for h in scan_text(text, whitelist=WL) if h.hard}


# ---------- 脱敏 ----------

def test_review_applicant_real_name():
    # 复议申请人位："。麻亭玉不服，向本机关申请行政复议。"（本人是部分遮挡写法"麻某玉"）
    t = deidentify("被申请人某市公安局某分局对麻某玉作出处罚。麻某玉的处罚已执行。麻亭玉不服，向本机关申请行政复议。"
                   "本机关认为量罚得当。", subject="麻某玉").text
    assert "亭玉" not in t
    assert "甲不服，向本机关申请行政复议" in t        # 同姓且尾字一致：视为本人
    t2 = deidentify("文盎不服，向本机关申请行政复议。").text
    assert "文盎" not in t2 and "盎" not in t2       # 无本人时也要按语境认出


def test_pure_masked_variant_stays_subject():
    # 本人"隋xxx"与事实段"隋xx"（少一个遮挡号）：两种纯遮挡写法必须合并为甲（r4 接管修复回归：
    # 曾因插入部分遮挡合并块时缩进错误，把纯遮挡变体合并吞进新分支，导致"隋xx"另编乙、本人不再出现于事实段）
    t = deidentify("被处罚人隋xxx,男,居民身份证号码略。隋xx2023年2月至2023年7月参与网络赌博。", subject="隋xxx").text
    assert "乙" not in t and t.count("甲") >= 2


def test_annotated_role_list():
    # 复议当事人名录："申请人×（微信名：×某）、××、×××"——括号注记隔断并列，旧版只脱敏第一个
    t = deidentify("申请人祁慕函（微信名：凉某）、於航舟（微信名：孤某）、隰铭阔（微信名：庭某）、宦劲柏（微信名：月某）。"
                   "上述人员伙同赌博。").text
    for frag in ("慕函", "航舟", "铭阔", "劲柏"):
        assert frag not in t
    # R6 兜底：未脱敏的同类文本硬命中
    assert "person_annot" in hard_cats("祁慕函（微信名：凉某）、於航舟（微信名：孤某）伙同赌博。")


def test_list_run_after_chahuo():
    # "查获"后的顿号列举真名连排（qa 软候选 P 类两件：连排整串漏网）
    t = deidentify("民警在某游戏机室查获冯靖松、褚文轩、缪腾勃（另案处理）在该游戏机室参与赌博。").text
    for frag in ("靖松", "文轩", "腾勃"):
        assert frag not in t


def test_evid_statement_artifact():
    # "××陈述、××陈述"列举里的伪影：并列扩展曾把"（桂静怡）陈述"切出"怡陈述"当人名，
    # 与真名"桂静怡"重叠替换后残出"姓"+代号拼成假名（qa 软候选"姓+代号"假名类三件的根因）
    t = deidentify("以上事实有麻清源的陈述、桂静怡陈述、鲁永康陈述、检查笔录等证据证实。").text
    for frag in ("静怡", "永康", "清源"):
        assert frag not in t
    assert "陈述" in t                                     # 陈述一词本身保留


def test_listed_real_before_masked_siblings():
    # "查获麻秀玉⏎   、桑xx、柏xx和隋xx四人"：真名夹在遮挡写法列举里（软候选"高乙"类根因——
    # 并列扩展的向前窗口太短，把三字真名的姓切在窗外只认出尾部，残出"姓"+代号）
    t = deidentify("民警在某棋牌室查获麻秀玉\n   、桑xx、柏xx和隋xx四人利用麻将进行赌博。", subject="隋xx").text
    assert "秀玉" not in t and "麻乙" not in t and "麻丙" not in t
    assert "乙" in t and "丙、丁和甲四人" in t               # 真名整编代号，与遮挡写法的代号并列


def test_at_place_name():
    # "姓名在××市/区……"（qa 软候选 P 件："费××在无锡市滨湖区雪新苑用麻将"）
    t = deidentify("甲为陶万松、费岩松提供赌具。费岩松在通州市滨湖区雪新苑用麻将聚赌。").text
    assert "岩松" not in t and "万松" not in t


def test_deng_shi_ren_caiyong():
    # "，伊俊才等十人采用扑克"：旧版 CUE 语境只认"等人+动词"，不认"等N人+采用"
    t = deidentify("在某街道半岛咖啡包厢内，伊俊才等十人采用扑克计算输赢的方式进行赌博。").text
    assert "俊才" not in t


def test_cell_wrap_before_dunhao():
    # 表格续行把顿号列举切开（"柏小茉|⏎|⏎|、饶清晏在……"）：续行去掉后整串列举要能认出
    t = deidentify("戊、己、柏小茉|   \n|   |、饶清晏在定海区某街道的房屋内赌博。").text
    assert "小茉" not in t and "清晏" not in t


def test_time_and_common_noun_not_names():
    # 复核确认的两个误报不得被新规则误伤："于当日"（时间短语）、"屈辱"（普通名词）
    t = deidentify("乙等四人进行赌博，于当日被公安机关查获。当时其心中只有愤怒、屈辱，记录的内容想不起来。").text
    assert "于当日" in t and "屈辱" in t


def test_r6_backstop_hard_hits():
    assert "person_review" in hard_cats("某市公安局对麻亭玉作出处罚。麻亭玉不服，申请行政复议。")
    # 遮挡写法不算真名（残留时由既有的 person_masked 硬命中兜住）
    hits = [h for h in scan_text("麻某玉不服，申请行政复议。", whitelist=WL) if h.hard]
    assert {h.cat for h in hits} == {"person_masked"}
    assert not [h for h in scan_text("本机关认为，申辩意见成立，但不服理由不成立。", whitelist=WL) if h.hard]


# ---------- 2026-10-17 r4 金标复检回退修复 ----------

def test_room_number_masked():
    # "207房间""8416房间"：房屋后缀表缺"房间/号房"（r4 复检 privacy 回退）
    t = deidentify("民警在某宾馆207房间查获甲等人赌博，另一处在8416房间。").text
    assert "207房间" not in t and "8416房间" not in t


def test_village_name_with_flag_char():
    # "红旗村"：地名捕获排除表含"旗"字导致名字中间带旗的村名永远匹配不上（r4 复检回退）
    t = deidentify("在红旗村老五楼某室内赌博。").text
    assert "红旗村" not in t and "某村" in t                 # 专名整体换"某"，只留后缀


def test_zhai_suffix_place():
    # "白家寨（小地名）"：地名后缀缺"寨"（r4 复检回退）
    t = deidentify("在某村二组白家寨乙家中赌博。").text
    assert "白家寨" not in t


def test_wrapped_name_across_bare_newline():
    # "陆厚⏎   琴家"：表格裸换行把人名切成两行（r4 复检 possible_person_name 回退）
    t = deidentify("现查明：在红旗村老五楼某室陆厚\n   琴家中，四人利用打麻将赌博。").text
    assert "厚琴" not in t and "陆厚" not in t
