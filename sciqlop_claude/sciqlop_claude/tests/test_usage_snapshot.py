"""ResultMessage and get_context_usage() map into a UsageSnapshot.

Guarded: this plugin's conftest stubs SciQLop with MagicMock in a Qt-less CI
env, and asserting against a MagicMock would pass vacuously. Skip there.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from SciQLop.components.agents import backend as _agents_backend

pytestmark = pytest.mark.skipif(
    isinstance(_agents_backend, MagicMock),
    reason="SciQLop is stubbed in this environment; usage types are not real",
)


def _result(**kwargs):
    base = dict(
        usage={"input_tokens": 1000, "output_tokens": 250,
               "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 40},
        total_cost_usd=0.42, num_turns=12, duration_api_ms=108_000,
        session_id="abc123", model_usage=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _bare_backend(**attrs):
    """A ClaudeBackend with only the attributes usage_snapshot() reads.

    Built without __init__ so no SDK client is required. Centralised because
    every new instance attribute the backend gains would otherwise break each
    hand-rolled construction site individually — that has happened twice.
    """
    from sciqlop_claude import backend as mod

    be = object.__new__(mod.ClaudeBackend)
    be._last_result = None
    be._client = None
    be._rate_limits = {}
    for name, value in attrs.items():
        setattr(be, name, value)
    return be


def test_result_message_maps_tokens_cost_and_turns():
    from sciqlop_claude.backend import result_to_usage

    snapshot = result_to_usage(_result())
    assert snapshot.tokens.input == 1000
    assert snapshot.tokens.output == 250
    assert snapshot.tokens.cache_read == 9000
    assert snapshot.tokens.cache_write == 40
    assert snapshot.cost.amount == 0.42
    assert snapshot.cost.unit == "USD"
    assert snapshot.num_turns == 12
    assert snapshot.duration_api_ms == 108_000
    assert snapshot.session_id == "abc123"


def test_canonical_model_is_preferred_for_display():
    from sciqlop_claude.backend import result_to_usage

    snapshot = result_to_usage(_result(
        model_usage={"claude-opus-4-5-20251101": {"canonicalModel": "Opus 4.5"}}))
    assert snapshot.model == "Opus 4.5"


def test_canonical_model_is_found_on_a_later_model_usage_entry():
    """A multi-model turn (a subagent on another model) can carry the canonical
    name on any entry, so the loop must not settle for the first raw key."""
    from sciqlop_claude.backend import result_to_usage

    snapshot = result_to_usage(_result(model_usage={
        "claude-haiku-4-5-20251001": {},
        "claude-opus-4-5-20251101": {"canonicalModel": "Opus 4.5"},
    }))
    assert snapshot.model == "Opus 4.5"


def test_falls_back_to_the_raw_model_key_without_a_canonical_name():
    from sciqlop_claude.backend import result_to_usage

    snapshot = result_to_usage(_result(
        model_usage={"claude-opus-4-5-20251101": {}}))
    assert snapshot.model == "claude-opus-4-5-20251101"


def test_missing_cost_stays_none_rather_than_zero():
    from sciqlop_claude.backend import result_to_usage

    assert result_to_usage(_result(total_cost_usd=None)).cost is None


def test_context_payload_maps_to_categories_and_totals():
    from sciqlop_claude.backend import context_to_breakdown

    tokens, maximum, categories, model = context_to_breakdown({
        "categories": [
            {"name": "System prompt", "tokens": 3100},
            {"name": "Messages", "tokens": 127000},
        ],
        "totalTokens": 168_000,
        "maxTokens": 500_000,
        "model": "Opus 4.5",
    })
    assert tokens == 168_000
    assert maximum == 500_000
    assert model == "Opus 4.5"
    assert [(c.name, c.tokens) for c in categories] == [
        ("System prompt", 3100), ("Messages", 127000)]


def test_context_payload_tolerates_missing_and_malformed_fields():
    from sciqlop_claude.backend import context_to_breakdown

    assert context_to_breakdown({}) == (None, None, (), None)
    assert context_to_breakdown(None) == (None, None, (), None)
    tokens, maximum, categories, _ = context_to_breakdown(
        {"categories": [{"tokens": 5}, "junk", {"name": "ok", "tokens": 7}]})
    assert [(c.name, c.tokens) for c in categories] == [("", 5), ("ok", 7)]


def test_usage_snapshot_merges_result_and_context():
    from sciqlop_claude import backend as mod

    be = _bare_backend()
    be._last_result = _result()
    be._client = SimpleNamespace(
        get_context_usage=lambda: _async({"totalTokens": 1, "maxTokens": 2}))

    snapshot = asyncio.run(mod.ClaudeBackend.usage_snapshot(be))
    assert snapshot.cost.amount == 0.42
    assert snapshot.context_tokens == 1
    assert snapshot.context_max == 2


def test_the_canonical_model_beats_the_context_payload_model():
    """`get_context_usage()` succeeds on every connected refresh and reports
    whatever alias the request carried — exactly what `canonicalModel` exists to
    normalise away. Letting it win makes the canonical path dead code."""
    from sciqlop_claude import backend as mod

    be = _bare_backend()
    be._last_result = _result(
        model_usage={"claude-opus-4-5-20251101": {"canonicalModel": "Opus 4.5"}})
    be._client = SimpleNamespace(get_context_usage=lambda: _async(
        {"totalTokens": 1, "maxTokens": 2, "model": "claude-opus-4-5-20251101"}))

    snapshot = asyncio.run(mod.ClaudeBackend.usage_snapshot(be))
    assert snapshot.model == "Opus 4.5"


def test_the_context_model_still_fills_in_when_the_result_has_none():
    from sciqlop_claude import backend as mod

    be = _bare_backend()
    be._last_result = _result(model_usage=None)      # no model_usage at all
    be._client = SimpleNamespace(get_context_usage=lambda: _async(
        {"totalTokens": 1, "maxTokens": 2, "model": "Sonnet 4.6"}))

    assert asyncio.run(mod.ClaudeBackend.usage_snapshot(be)).model == "Sonnet 4.6"


def test_usage_snapshot_survives_a_context_call_failure():
    from sciqlop_claude import backend as mod

    async def boom():
        raise RuntimeError("not connected")

    be = _bare_backend()
    be._last_result = _result()
    be._client = SimpleNamespace(get_context_usage=boom)

    snapshot = asyncio.run(mod.ClaudeBackend.usage_snapshot(be))
    assert snapshot.cost.amount == 0.42      # result data still reported
    assert snapshot.context_tokens is None


def test_usage_snapshot_is_none_before_any_turn():
    from sciqlop_claude import backend as mod

    be = _bare_backend()
    be._last_result = None
    be._client = None
    assert asyncio.run(mod.ClaudeBackend.usage_snapshot(be)) is None


async def _async(value):
    return value


def test_rate_limit_events_map_to_five_hour_and_weekly_quotas():
    from sciqlop_claude.backend import rate_limits_to_quotas

    events = {
        "five_hour": SimpleNamespace(
            status="allowed", utilization=0.82, resets_at=1_785_000_000,
            rate_limit_type="five_hour"),
        "seven_day": SimpleNamespace(
            status="allowed_warning", utilization=0.41, resets_at=1_785_300_000,
            rate_limit_type="seven_day"),
    }
    five, week = rate_limits_to_quotas(events)
    assert (five.label, five.percent_used, five.resets_at) == ("5h", 82.0, 1_785_000_000)
    assert (week.label, week.percent_used, week.resets_at) == ("week", 41.0, 1_785_300_000)


def test_only_the_windows_the_cli_reported_appear():
    from sciqlop_claude.backend import rate_limits_to_quotas

    events = {"five_hour": SimpleNamespace(
        status="allowed", utilization=0.1, resets_at=1, rate_limit_type="five_hour")}
    quotas = rate_limits_to_quotas(events)
    assert [q.label for q in quotas] == ["5h"]
    assert rate_limits_to_quotas({}) == ()


def test_a_model_specific_weekly_window_is_labelled_by_its_model():
    from sciqlop_claude.backend import rate_limits_to_quotas

    events = {"seven_day_opus": SimpleNamespace(
        status="allowed", utilization=0.55, resets_at=2,
        rate_limit_type="seven_day_opus")}
    quotas = rate_limits_to_quotas(events)
    assert [q.label for q in quotas] == ["week (opus)"]


def test_a_window_with_no_utilization_is_skipped_rather_than_shown_as_zero():
    from sciqlop_claude.backend import rate_limits_to_quotas

    events = {"five_hour": SimpleNamespace(
        status="allowed", utilization=None, resets_at=1, rate_limit_type="five_hour")}
    assert rate_limits_to_quotas(events) == ()


def test_usage_snapshot_carries_the_rate_limit_windows():
    from sciqlop_claude import backend as mod

    be = _bare_backend()
    be._last_result = _result()
    be._client = None
    be._rate_limits = {"five_hour": SimpleNamespace(
        status="allowed", utilization=0.5, resets_at=9, rate_limit_type="five_hour")}

    snapshot = asyncio.run(mod.ClaudeBackend.usage_snapshot(be))
    assert [q.label for q in snapshot.quotas] == ["5h"]
    assert snapshot.quotas[0].percent_used == 50.0


def test_context_is_reported_before_any_turn_completes():
    """Claude Code shows /context the moment the session connects; the system
    prompt, MCP tools and CLAUDE.md files already occupy real budget. Waiting
    for a ResultMessage kept the strip blank through the whole first turn."""
    from sciqlop_claude import backend as mod

    be = _bare_backend(_client=SimpleNamespace(get_context_usage=lambda: _async(
        {"totalTokens": 34_000, "maxTokens": 500_000, "model": "Opus 4.5",
         "categories": [{"name": "MCP tools", "tokens": 28_400}]})))

    snapshot = asyncio.run(mod.ClaudeBackend.usage_snapshot(be))
    assert snapshot is not None
    assert snapshot.context_tokens == 34_000
    assert snapshot.context_max == 500_000
    assert snapshot.model == "Opus 4.5"
    assert snapshot.tokens is None          # no turn has happened yet
    assert snapshot.cost is None


def test_nothing_to_report_without_a_client_or_a_turn():
    from sciqlop_claude import backend as mod

    assert asyncio.run(mod.ClaudeBackend.usage_snapshot(_bare_backend())) is None


def test_rate_limit_windows_alone_are_worth_reporting():
    """The windows arrive on the stream and outlive any one turn, so they are
    reportable even before the first result and with no live client."""
    from sciqlop_claude import backend as mod

    be = _bare_backend(_rate_limits={"five_hour": SimpleNamespace(
        status="allowed", utilization=0.3, resets_at=5,
        rate_limit_type="five_hour")})

    snapshot = asyncio.run(mod.ClaudeBackend.usage_snapshot(be))
    assert snapshot is not None
    assert [q.label for q in snapshot.quotas] == ["5h"]


def test_an_empty_snapshot_is_reported_as_nothing_at_all():
    """A snapshot with no field set must not reach the strip: `info_segments`
    renders a non-None snapshot, so an empty one leaves the strip showing the
    effort segment alone with no model, context or cost beside it."""
    from sciqlop_claude import backend as mod

    be = _bare_backend(_client=SimpleNamespace(
        get_context_usage=lambda: _async({})))          # CLI knows nothing yet

    assert asyncio.run(mod.ClaudeBackend.usage_snapshot(be)) is None


def test_a_failing_context_call_before_any_turn_reports_nothing():
    from sciqlop_claude import backend as mod

    async def boom():
        raise RuntimeError("no context yet")

    be = _bare_backend(_client=SimpleNamespace(get_context_usage=boom))
    assert asyncio.run(mod.ClaudeBackend.usage_snapshot(be)) is None
