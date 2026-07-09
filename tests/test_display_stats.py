"""Failing tests defining "done" for goal #1: honest scan feedback.

These pin the interface for the display work. The NEW helpers/fields they
exercise do not exist yet, so groups A-D FAIL on purpose -- they are the
finish line we build toward. Group E tests EXISTING behavior and should
PASS now (and keep passing), acting as the no-regression guard.

Everything here runs on in-memory objects: a real ``ReportState``, plain
dicts, and a monkeypatched ``load_settings``. No scan, no container, no
network. Time is made deterministic by INJECTING ``now`` rather than
reading the clock.

Honesty contract encoded below:
- elapsed time is anchored to the real ``start_time`` (never faked),
- the turn counter is labeled as MODEL TURNS against a BUDGET, never as a
  percentage or "complete",
- the only phase we assert is the real ``scanning`` -> ``finalizing`` flip
  driven by ``finish_scan``; no invented recon/exploit labels.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from strix.core.inputs import DEFAULT_MAX_TURNS
from strix.interface.utils import build_live_stats_text, build_tui_stats_text
from strix.report.state import ReportState, set_global_report_state


FIXED_START = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_global_report_state():
    """Keep the module-global report state from leaking across tests."""
    yield
    set_global_report_state(None)  # type: ignore[arg-type]


@pytest.fixture
def patched_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``load_settings().llm.model`` deterministic for the builders."""
    monkeypatch.setattr(
        "strix.interface.utils.load_settings",
        lambda: SimpleNamespace(llm=SimpleNamespace(model="test-model")),
    )


# ---------------------------------------------------------------------------
# A. Elapsed time renders correctly from a controlled start_time
# ---------------------------------------------------------------------------


def test_elapsed_formats_known_interval() -> None:
    """83s after start renders as '1m 23s'."""
    from strix.interface.utils import format_elapsed

    now = FIXED_START + timedelta(seconds=83)
    assert format_elapsed(FIXED_START.isoformat(), now) == "1m 23s"


def test_elapsed_zero_is_zero_seconds() -> None:
    """now == start renders '0s' (not empty, not negative, no crash)."""
    from strix.interface.utils import format_elapsed

    assert format_elapsed(FIXED_START.isoformat(), FIXED_START) == "0s"


def test_elapsed_scales_past_an_hour() -> None:
    """3665s renders with an hours component: '1h 1m 5s'."""
    from strix.interface.utils import format_elapsed

    now = FIXED_START + timedelta(seconds=3665)
    assert format_elapsed(FIXED_START.isoformat(), now) == "1h 1m 5s"


def test_elapsed_anchored_to_start_not_now() -> None:
    """Elapsed is anchored to start_time (what resume restores), not 'now'.

    Guards the resume path: ``hydrate_from_run_dir`` restores the ORIGINAL
    start_time (state.py:170), so a resumed scan must show total elapsed
    since the real start, not since the resume.
    """
    from strix.interface.utils import format_elapsed

    resumed_now = FIXED_START + timedelta(hours=2, seconds=5)
    rendered = format_elapsed(FIXED_START.isoformat(), resumed_now)
    assert rendered.startswith("2h")


# ---------------------------------------------------------------------------
# B. Agent lifecycle counts render ("N running, N completed")
# ---------------------------------------------------------------------------


def test_agent_counts_mixed_statuses() -> None:
    """Tally per real status, canonical order, ' · ' separated."""
    from strix.interface.utils import format_agent_counts

    statuses = {"a": "running", "b": "running", "c": "completed", "d": "failed"}
    assert format_agent_counts(statuses) == "2 running · 1 completed · 1 failed"


def test_agent_counts_single_running_no_zero_noise() -> None:
    """A lone running agent renders '1 running' with no '0 completed' noise."""
    from strix.interface.utils import format_agent_counts

    assert format_agent_counts({"root": "running"}) == "1 running"


def test_agent_counts_only_real_statuses_appear() -> None:
    """Every present real status is counted; none are invented or dropped.

    Statuses come from the real Status enum (agents.py:21):
    running/waiting/completed/stopped/crashed/failed.
    """
    from strix.interface.utils import format_agent_counts

    rendered = format_agent_counts({"a": "waiting", "b": "crashed"})
    assert "1 waiting" in rendered
    assert "1 crashed" in rendered
    # nothing invented for statuses that are not present
    assert "running" not in rendered
    assert "completed" not in rendered


# ---------------------------------------------------------------------------
# C. Model-turn counter renders, labeled honestly (not "% complete")
# ---------------------------------------------------------------------------


def test_turn_budget_shows_count_and_budget() -> None:
    """Renders the live count and the budget ceiling, labeled as turns."""
    from strix.interface.utils import format_turn_budget

    rendered = format_turn_budget(47, 500)
    assert "47" in rendered
    assert "500" in rendered
    assert "turn" in rendered.lower()


def test_turn_budget_is_honest_not_a_percentage() -> None:
    """The honesty guard: never dress the turn counter up as % complete.

    This test fails if anyone later renders a completion percentage or
    calls the budget 'complete' -- the ceiling is a budget, not a finish.
    """
    from strix.interface.utils import format_turn_budget

    rendered = format_turn_budget(47, 500).lower()
    assert "%" not in rendered
    assert "complete" not in rendered


def test_turn_budget_zero_and_report_state_fields() -> None:
    """Fresh ReportState exposes the plumbed fields; zero turns is safe.

    ``model_turns`` (incremented per model turn) defaults to 0 and
    ``max_turns`` is plumbed onto the state (default DEFAULT_MAX_TURNS=500,
    which today stops at the runner/execution layer).
    """
    from strix.interface.utils import format_turn_budget

    state = ReportState(run_name="t")
    assert state.model_turns == 0
    assert state.max_turns == DEFAULT_MAX_TURNS

    rendered = format_turn_budget(state.model_turns, state.max_turns)
    assert "0" in rendered
    assert "500" in rendered


async def test_on_llm_end_increments_model_turns() -> None:
    """The counter is a REAL count: on_llm_end bumps it once per model turn.

    ``ReportUsageHooks.on_llm_end`` (hooks.py:36) already fires once per
    model response; it must increment the stored counter so the displayed
    number is counted, never faked.
    """
    from strix.core.hooks import ReportUsageHooks

    state = ReportState(run_name="t")
    set_global_report_state(state)

    hooks = ReportUsageHooks(model="test-model")
    context = SimpleNamespace(context={"agent_id": "root"})
    agent = SimpleNamespace(name="root")
    response = SimpleNamespace(usage=None)

    await hooks.on_llm_end(context, agent, response)  # type: ignore[arg-type]

    assert state.model_turns == 1


# ---------------------------------------------------------------------------
# D. scanning -> finalizing flips on finish_scan
# ---------------------------------------------------------------------------


def test_phase_defaults_to_scanning() -> None:
    """A fresh scan (nothing finalized) is 'scanning'."""
    from strix.interface.utils import scan_phase_label

    assert scan_phase_label(ReportState(run_name="t")) == "scanning"


def test_phase_flips_to_finalizing_on_finish() -> None:
    """Once finish_scan populates the final result, phase is 'finalizing'.

    ``finish_scan`` sets ``final_scan_result`` (state.py:324); that real,
    single transition is the honest signal for finalization.
    """
    from strix.interface.utils import scan_phase_label

    state = ReportState(run_name="t")
    state.final_scan_result = "Executive summary ..."
    assert scan_phase_label(state) == "finalizing"


def test_phase_not_flipped_by_incremental_vuln_report() -> None:
    """Filing a vuln mid-scan must NOT flip the phase to finalizing.

    ``create_vulnerability_report`` fires throughout the scan
    (reporting/tool.py:301), so it is NOT a finalization signal. This
    guards the false-phase trap: reporting happens continuously.
    """
    from strix.interface.utils import scan_phase_label

    state = ReportState(run_name="t")
    state.vulnerability_reports.append({"severity": "high", "title": "mid-scan finding"})
    assert scan_phase_label(state) == "scanning"


# ---------------------------------------------------------------------------
# E. No regression on existing display output (should PASS now)
# ---------------------------------------------------------------------------


def test_live_stats_still_renders_vuln_severity(patched_model: None) -> None:
    """build_live_stats_text still renders the severity breakdown."""
    state = ReportState(run_name="t")
    state.vulnerability_reports.extend(
        [
            {"severity": "critical", "title": "a"},
            {"severity": "critical", "title": "b"},
            {"severity": "low", "title": "c"},
        ]
    )
    plain = build_live_stats_text(state).plain
    assert "Vulnerabilities" in plain
    assert "CRITICAL: 2" in plain
    assert "LOW: 1" in plain


def test_tui_stats_still_renders_tokens_and_cost(patched_model: None) -> None:
    """build_tui_stats_text still renders 'N tokens · $X.XX'."""
    report_state = MagicMock()
    report_state.get_total_llm_usage.return_value = {"total_tokens": 12345, "cost": 1.5}
    report_state.caido_url = None

    plain = build_tui_stats_text(report_state).plain
    assert "tokens" in plain
    assert "$1.50" in plain


def test_tui_stats_caido_url_branch(patched_model: None) -> None:
    """caido_url is rendered when set and omitted when absent."""
    with_url = MagicMock()
    with_url.get_total_llm_usage.return_value = {"total_tokens": 0, "cost": 0.0}
    with_url.caido_url = "http://caido.local:8080"
    assert "http://caido.local:8080" in build_tui_stats_text(with_url).plain

    without_url = MagicMock()
    without_url.get_total_llm_usage.return_value = {"total_tokens": 0, "cost": 0.0}
    without_url.caido_url = None
    assert "Caido" not in build_tui_stats_text(without_url).plain


def test_builders_handle_empty_report_state() -> None:
    """Both builders return empty Text for a falsy report_state."""
    assert build_live_stats_text(None).plain == ""
    assert build_tui_stats_text(None).plain == ""
