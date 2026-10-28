"""规则生成特征（ADR-011）：名单由规则枚举、与规则同变；规则特征模型的名单哈希必须与当前规则一致（规则改了须重训）。"""
from datetime import date

import pytest

from app.discretion import practice, rule_features
from app.discretion.norm_layer import Facts
from app.discretion.schema import AmountRange


def test_spec_is_enumerated_from_rules():
    names = [s["name"] for s in rule_features.spec()]
    assert len(names) == len(set(names))
    assert "320000:参与赌博:measure:personal_or_per_capita:source:cumulative_stake" in names
    assert "320000:为赌博提供条件:elevate:role_lender:true" in names
    assert names[:9] == [f"rule:{k}:{t}" for t in practice.ORDER for k in ("unique", "candidate")] + ["rule:none"] or \
        names[8] == "rule:none"


def test_features_read_rule_computation():
    f = Facts(behavior_date=date(2022, 5, 1), decision_date=date(2022, 6, 1), region="320500",
              behavior_type="参与赌博", method="网络赌博", cumulative_stake=AmountRange(min=1987, max=1987))
    x = dict(zip([s["name"] for s in rule_features.spec()], rule_features.features(f)))
    assert x["rule:unique:拘留并处罚款"] == 1 and x["prov:320000"] == 1
    assert x["320000:参与赌博:measure:personal_or_per_capita:source:cumulative_stake"] == 1
    assert x["320000:参与赌博:measure:personal_or_per_capita:band_lo"] == 3


@pytest.mark.parametrize("name", ["rap-ruled-v2.json", "rap-ruleonly-v2.json"])
def test_rule_feature_models_match_current_rules(name):
    m = practice.load_model(str(practice.MODEL_PATH.parent / name))
    assert m is not None and not m.get("stale"), "规则已变更：重跑 research/eval/rule_chain/rap_v2.py 重训"
