"""Regression checks for as-of filtering, event isolation, and sparse backoff."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agency_prior import AgencyPrior, Context  # noqa: E402


def context(rid, event, authority, day, epoch="old_pre_2026", city="1301", province="13"):
    return Context(rid, event, authority, city, province, day, epoch,
                   "s1_record", "lake_exact_authority")


def test_prior_uses_only_earlier_other_events_and_shrinks_sparse_agency():
    rows = [
        {"id": "early", "event_id": "event-1", "target": {"type": "拘留"}},
        {"id": "future", "event_id": "event-2", "target": {"type": "罚款"}},
    ]
    contexts = {
        "early": context("early", "event-1", "A", date(2025, 1, 1)),
        "future": context("future", "event-2", "A", date(2025, 2, 1)),
    }
    prior = AgencyPrior(rows, contexts, [0, 1], smoothing_events=20)
    query = context("query", "event-3", "A", date(2025, 1, 15))
    result = prior.predict(query)
    assert result.source_level == "agency"
    assert result.effective_events == 1
    assert result.probabilities["拘留"] > result.probabilities["罚款"]
    assert result.probabilities["拘留"] < 1
    assert prior.predict(context("same", "event-1", "A", date(2025, 1, 15))).source_level == "unavailable_epoch_history"


def test_prior_falls_back_to_city_and_refuses_unknown_date_or_epoch():
    rows = [{"id": "early", "event_id": "event-1", "target": {"type": "罚款"}}]
    contexts = {"early": context("early", "event-1", "A", date(2025, 1, 1))}
    prior = AgencyPrior(rows, contexts, [0], smoothing_events=20)
    other_agency = context("query", "event-2", "B", date(2025, 1, 2))
    assert prior.predict(other_agency).source_level == "city"
    assert prior.predict(context("missing", "event-3", "B", None)).source_level == "unavailable_date"
    assert prior.predict(context("new", "event-4", "B", date(2026, 1, 2), "new_2026")).source_level == "unavailable_epoch_history"
