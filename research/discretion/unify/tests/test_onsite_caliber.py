import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onsite_caliber import COIN, OTHER, PERSONAL, POOL, SEIZED, TOTAL, caliber_of, decide


def cal(text: str, raw: str, names=("周xx",)) -> str:
    i = text.index(raw)
    return caliber_of(text, i, i + len(raw), list(names), raw)


def test_stated_total_and_items_under_it():
    t = "后被公安机关查获，现场共查获赌资3695元，其中张x赌资900元、顾xx赌资760元。"
    assert cal(t, "3695元") == TOTAL
    assert cal(t, "900元") == PERSONAL
    assert cal(t, "760元") == PERSONAL


def test_seizure_heading_an_itemised_list_is_a_total():
    t = "民警现场查获赌资9195\n   元、赌具麻将40张，其中薛xx的赌资1165元。"
    assert cal(t, "9195\n   元") == TOTAL


def test_one_persons_money_is_not_a_total():
    assert cal("现场扣押邹xx赌资400元。", "400元") == PERSONAL
    assert cal("被查获时身上有赌资1800元。", "1800元") == PERSONAL
    assert cal("后当场被查获，查获张晶赌资315元。", "315元") == PERSONAL
    assert cal("查获时秦x输一百元，被查获赌资四百五十五元。", "四百五十五元") == PERSONAL


def test_pool_beside_items_is_a_part_not_the_total():
    t = "现场保全个人赌资七十元、共有赌资二万五千一百八十元。"
    assert cal(t, "二万五千一百八十元") == POOL
    t = "现场查获无主赌资4650元，赌具牌九一副，其中陈xx个人赌资50元。"
    assert cal(t, "4650元") == TOTAL


def test_losses_turnover_and_per_head_are_not_totals():
    assert cal("在赌博期间，沈某波一共输了1000元左右。", "1000元") == OTHER
    assert cal("下分赌资达21200元，总计流水为44500元。", "44500元") == OTHER
    assert cal("现场查获赌资总计2930元，人均赌资732.5元。", "732.5元") == OTHER
    assert cal("现场查获赌资总计2930元，人均赌资732.5元。", "2930元") == TOTAL
    assert cal("桌面总输赢达1500元的赌博活动。", "1500元") == TOTAL


def test_coin_count_and_unattributed_seizure():
    assert cal("经清点，老虎机内有一元硬币732个。", "一元") == COIN
    assert cal("后被公安机关查获，当场扣押赌资4140元。", "4140元") == SEIZED


def c(caliber, v):
    return {"candidate_id": f"Q-{v}", "raw": f"{v}元", "value": {"min": v, "max": v}, "caliber": caliber}


def test_decide():
    assert decide([c(TOTAL, 3695), c(PERSONAL, 900)])["status"] == "bound"
    assert decide([c(TOTAL, 3695), c(TOTAL, 3000)])["reason"] == "several_totals"
    assert decide([c(SEIZED, 4140)])["reason"] == "only_unattributed_money"
    assert decide([c(POOL, 31850)])["reason"] == "only_unattributed_money"
    assert decide([c(SEIZED, 1900), c(PERSONAL, 200)])["status"] == "unresolved"
    assert decide([c(PERSONAL, 400)]) == {"status": "absent", "reason": "no_total_expression"}
    assert decide([c(COIN, 1)])["reason"] == "coin_count"
    assert decide([])["reason"] == "no_amount"
