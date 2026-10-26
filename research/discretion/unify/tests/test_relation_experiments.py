from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiment_latent_paths import BagSoftmax
from experiment_relation_metamorphic import rename_record
from experiment_relation_perturbations import case_packet
from experiment_relation_suite import amount_features


def test_latent_bag_learns_compatible_mass_without_edge_identity() -> None:
    model = BagSoftmax()
    positive = [{"compatible": 1.0}, {"compatible": 1.0}, {"rival": 1.0}]
    model.fit([(positive, {0, 1}), ([{"rival": 1.0}], None)], missing_weight=1.0,
              epochs=100)
    scores = model.posterior(positive)
    assert scores[0] == scores[1]
    assert scores[0] + scores[1] > scores[2]


def test_same_candidates_for_feature_ablations() -> None:
    text = "甲持有赌资500元，现场查获赌资1500元。"
    inp, packet = case_packet({"id": "test", "target": "甲", "facts": text})
    amounts = [q for q in packet["quantities"] if q["type"] == "amount"]
    assert len(amounts) == 2
    surface = amount_features("surface")(amounts[0], inp, packet)
    relation = amount_features("local_relation")(amounts[0], inp, packet)
    scene = amount_features("scene_relation")(amounts[0], inp, packet)
    assert surface
    assert set(surface) < set(relation) <= set(scene)
    assert "role:personal_stake" in relation


def test_target_rename_preserves_view_offsets() -> None:
    text = "甲持有赌资500元，甲在现场赌博。"
    inp, _ = case_packet({"id": "rename", "target": "甲", "facts": text})
    renamed = rename_record(inp, text)
    assert renamed is not None
    new_inp, new_text = renamed
    assert len(text) == len(new_text)
    assert new_inp["sentence_view"][0]["text"] == new_text
    assert new_inp["source_sha256"] == hashlib.sha256(new_text.encode()).hexdigest()
