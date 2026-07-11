"""Failing tests defining "done" for goal #3: live agent activity in the CLI.

Recon established that the non-interactive CLI path is BLIND to agent
activity: it renders vuln stats, phase, elapsed and the turn budget from
``ReportState``, but never surfaces how many agents are running or what they
are. The TUI shows this; the CLI does not, purely because it has no handle on
the ``AgentCoordinator`` (see the honesty comment at cli.py:150-153).

Approach (locked): the coordinator already snapshots live agent state to
``{run_dir}/.state/agents.json`` on every status change (agents.py:298-316,
wired at runner.py:105) -- the same file the TUI hydrates from
(live_view.py:26-27). The CLI can read that file on its existing 2s refresh
and render lifecycle counts + a roster, reusing the ALREADY-SHIPPED
``format_agent_counts`` helper (utils.py:90, tested in test_display_stats.py).

These tests pin the interface for that work. The NEW symbols they import
(``agent_activity_from_run_dir``, ``build_agent_activity_text``) do not exist
yet, so groups A-C FAIL on purpose -- they are the finish line. Group D
exercises EXISTING behavior and should PASS now (and keep passing), acting as
the additive / no-regression guard.

Everything here runs on an on-disk fixture ``agents.json`` in a pytest
``tmp_path``: no scan, no container, no SDK, no network.

Honesty contract encoded below:
- only agent statuses ACTUALLY present in the snapshot are rendered -- no
  invented categories, no "0 completed" noise,
- no completion percentage and no fabricated "complete" when nothing is,
- no invented recon/exploit phase labels injected into the roster,
- when no agents are known yet, NOTHING renders (no empty "Agents:" header).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from strix.core.paths import runtime_state_dir
from strix.interface.utils import (
    build_live_stats_text,
    format_agent_counts,
    format_turn_budget,
    scan_phase_label,
)
from strix.report.state import ReportState


FIXED_START = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)

# A realistic coordinator snapshot: a root plus two children, mixed statuses.
# Shape mirrors AgentCoordinator.snapshot() (agents.py:278-286).
MIXED_SNAPSHOT: dict[str, Any] = {
    "statuses": {"root": "running", "recon": "running", "exploit": "completed"},
    "parent_of": {"root": None, "recon": "root", "exploit": "root"},
    "names": {"root": "strix", "recon": "recon-scout", "exploit": "exploit-agent"},
    "metadata": {},
    "pending_counts": {},
}

# A snapshot with a single running agent -- nothing completed. Used to prove
# the render never fabricates completeness when there is none.
RUNNING_ONLY_SNAPSHOT: dict[str, Any] = {
    "statuses": {"root": "running"},
    "parent_of": {"root": None},
    "names": {"root": "strix"},
    "metadata": {},
    "pending_counts": {},
}


def _write_snapshot(run_dir: Path, snapshot: dict[str, Any]) -> Path:
    """Write ``snapshot`` to ``{run_dir}/.state/agents.json`` (the real layout)."""
    state_dir = runtime_state_dir(run_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    agents_path = state_dir / "agents.json"
    agents_path.write_text(json.dumps(snapshot), encoding="utf-8")
    return agents_path


@pytest.fixture
def patched_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``load_settings().llm.model`` deterministic for the builders."""
    monkeypatch.setattr(
        "strix.interface.utils.load_settings",
        lambda: SimpleNamespace(llm=SimpleNamespace(model="test-model")),
    )


# ---------------------------------------------------------------------------
# A. Pure reader: agents.json -> real status map
# ---------------------------------------------------------------------------


def test_reader_returns_real_status_map(tmp_path: Path) -> None:
    """The helper reads the fixture snapshot and returns its true status map."""
    from strix.interface.utils import agent_activity_from_run_dir

    run_dir = tmp_path / "strix_runs" / "run"
    _write_snapshot(run_dir, MIXED_SNAPSHOT)

    statuses = agent_activity_from_run_dir(run_dir)
    assert statuses == MIXED_SNAPSHOT["statuses"]


def test_reader_missing_file_returns_empty(tmp_path: Path) -> None:
    """No agents.json (scan not started / no agents yet) -> empty, no crash.

    Must NOT raise and must NOT fabricate any agents.
    """
    from strix.interface.utils import agent_activity_from_run_dir

    run_dir = tmp_path / "strix_runs" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)  # run dir exists, .state does not

    statuses = agent_activity_from_run_dir(run_dir)
    assert not statuses


def test_reader_corrupt_file_returns_empty(tmp_path: Path) -> None:
    """A mid-write / corrupt agents.json degrades gracefully to empty.

    The coordinator writes atomically (tempfile + replace, agents.py:306-316),
    but a truncated or hand-corrupted file must never crash the CLI refresh
    thread or dump a traceback -- it just yields no agents this tick.
    """
    from strix.interface.utils import agent_activity_from_run_dir

    run_dir = tmp_path / "strix_runs" / "run"
    state_dir = runtime_state_dir(run_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "agents.json").write_text('{ "statuses": { "root": ', encoding="utf-8")

    statuses = agent_activity_from_run_dir(run_dir)
    assert not statuses


def test_reader_wrong_shape_returns_empty(tmp_path: Path) -> None:
    """Valid JSON but no usable ``statuses`` map -> empty, no crash."""
    from strix.interface.utils import agent_activity_from_run_dir

    run_dir = tmp_path / "strix_runs" / "run"
    _write_snapshot(run_dir, {"statuses": "not-a-dict"})

    assert not agent_activity_from_run_dir(run_dir)


# ---------------------------------------------------------------------------
# B. Status map feeds the EXISTING format_agent_counts helper
# ---------------------------------------------------------------------------


def test_reader_output_feeds_format_agent_counts(tmp_path: Path) -> None:
    """The reader's map plugs straight into the goal-1 helper, unchanged.

    format_agent_counts already renders canonical-order, ' · ' separated
    tallies (utils.py:90); goal #3 only has to supply it a real status map.
    """
    from strix.interface.utils import agent_activity_from_run_dir

    run_dir = tmp_path / "strix_runs" / "run"
    _write_snapshot(run_dir, MIXED_SNAPSHOT)

    rendered = format_agent_counts(agent_activity_from_run_dir(run_dir))
    assert rendered == "2 running · 1 completed"


# ---------------------------------------------------------------------------
# C. Render helper for the CLI live panel
# ---------------------------------------------------------------------------


def test_activity_text_empty_when_no_agents(tmp_path: Path) -> None:
    """No agents known yet -> render NOTHING (no empty 'Agents:' header)."""
    from strix.interface.utils import build_agent_activity_text

    run_dir = tmp_path / "strix_runs" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    text = build_agent_activity_text(run_dir)
    assert text.plain == ""
    assert "Agents" not in text.plain


def test_activity_text_renders_counts_and_roster(tmp_path: Path) -> None:
    """With agents present: a header, lifecycle counts, and the named roster."""
    from strix.interface.utils import build_agent_activity_text

    run_dir = tmp_path / "strix_runs" / "run"
    _write_snapshot(run_dir, MIXED_SNAPSHOT)

    plain = build_agent_activity_text(run_dir).plain
    # header appears only when there is something to show
    assert "Agents" in plain
    # lifecycle counts, via the existing helper
    assert "2 running" in plain
    assert "1 completed" in plain
    # roster surfaces the real friendly agent names (agents.py names map)
    assert "recon-scout" in plain
    assert "exploit-agent" in plain


def test_activity_text_is_honest_no_fabricated_completeness(tmp_path: Path) -> None:
    """A single running agent must not be dressed up as progress/completeness.

    Guards against: a completion percentage, a fabricated 'complete' when
    nothing has completed, invented recon/exploit phase labels, and statuses
    that are not actually present.
    """
    from strix.interface.utils import build_agent_activity_text

    run_dir = tmp_path / "strix_runs" / "run"
    _write_snapshot(run_dir, RUNNING_ONLY_SNAPSHOT)

    lowered = build_agent_activity_text(run_dir).plain.lower()
    assert "1 running" in lowered
    # no completion theatre
    assert "%" not in lowered
    assert "complete" not in lowered  # nothing has completed
    # only statuses actually present appear -- nothing invented
    assert "waiting" not in lowered
    assert "failed" not in lowered
    assert "stopped" not in lowered
    # no invented pentest-phase labels injected into the activity view
    assert "recon" not in lowered
    assert "exploit" not in lowered
    assert "phase" not in lowered


def test_activity_text_only_present_statuses(tmp_path: Path) -> None:
    """Mixed snapshot renders exactly the present statuses -- no zero-noise."""
    from strix.interface.utils import build_agent_activity_text

    run_dir = tmp_path / "strix_runs" / "run"
    _write_snapshot(run_dir, MIXED_SNAPSHOT)

    lowered = build_agent_activity_text(run_dir).plain.lower()
    assert "running" in lowered
    assert "completed" in lowered
    # statuses that are not in the snapshot must not appear at all
    assert "waiting" not in lowered
    assert "crashed" not in lowered
    assert "failed" not in lowered


# ---------------------------------------------------------------------------
# D. No regression: existing CLI live-panel building blocks are unchanged.
#    (These PASS now and must keep passing -- goal #3 is strictly additive.)
# ---------------------------------------------------------------------------


def test_live_stats_still_renders_vuln_severity(patched_model: None) -> None:
    """build_live_stats_text still renders the vuln severity breakdown."""
    state = ReportState(run_name="t")
    state.vulnerability_reports.extend(
        [
            {"severity": "critical", "title": "a"},
            {"severity": "high", "title": "b"},
        ]
    )
    plain = build_live_stats_text(state).plain
    assert "Vulnerabilities" in plain
    assert "CRITICAL: 1" in plain
    assert "HIGH: 1" in plain


def test_phase_label_unchanged() -> None:
    """The only honest phase flip (scanning -> finalizing) is untouched."""
    state = ReportState(run_name="t")
    assert scan_phase_label(state) == "scanning"
    state.final_scan_result = "Executive summary ..."
    assert scan_phase_label(state) == "finalizing"


def test_turn_budget_still_honest() -> None:
    """The turn counter stays a budget, never a % complete."""
    rendered = format_turn_budget(47, 500).lower()
    assert "47" in rendered
    assert "500" in rendered
    assert "%" not in rendered
    assert "complete" not in rendered


def test_elapsed_unchanged() -> None:
    """Elapsed still formats from an injected ``now`` (deterministic)."""
    from strix.interface.utils import format_elapsed

    now = FIXED_START + timedelta(seconds=83)
    assert format_elapsed(FIXED_START.isoformat(), now) == "1m 23s"
