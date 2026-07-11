# Omerta — PR pipeline worklog

A running record of the branch/PR pipeline landing the goal work onto `main`.
One PR at a time (no stacking): rebase onto `main` → test → push → open PR →
read Cursor Bugbot findings via the GitHub API → fix → push → merge →
delete branch → pull `main`. Bugbot reviews only the first push of a PR, so
after a fix push there is no second review to wait on.

Verification command (offline, bypasses uv's rebuild-on-pyproject-change):
`.venv/bin/python -m pytest tests/ -q`

Reading bugbot findings:
`gh api repos/AxeH666/Omerta/pulls/<N>/comments` (inline, line-level)
`gh api repos/AxeH666/Omerta/pulls/<N>/reviews`  (review summary)

---

## PR #1 — goal-1: honest scan feedback  ✅ MERGED
Branch: `goal-1-honest-feedback` → `main` (merge commit `6708b60`)

Landed honest CLI/TUI scan feedback (elapsed anchored to real start, agent
lifecycle counts, model-turn counter, `scanning → finalizing` phase) plus the
foundational recon docs and the guardrails hook.

**Bugbot findings (3, all Medium) — all fixed in `1b9078d`:**
1. *Resume resets model turn counter* — `model_turns` wasn't persisted to
   `run.json`, so resume reset it to 0. → Persist in `run_record` on save,
   restore on hydrate.
2. *Global turns vs per-cycle budget* — UI divided a scan-wide `model_turns`
   count by `max_turns` (the SDK's per-run ceiling), rendering e.g. "612/500".
   → Replaced `format_turn_budget` with `format_model_turns` (plain count).
3. *Unsynchronized coordinator status reads* — the UI timer thread iterated
   the live `coordinator.statuses` dict the scan loop mutates ("dictionary
   changed size during iteration"). → Count from the UI-thread-owned
   `live_view.agents` via `agent_statuses_from_view`.

---

## PR #2 — goal-2: doctor command + friendly messages  🔄 IN PROGRESS
Branch: `goal-2-doctor` → `main`

Rebased cleanly onto `main` (post-PR#1). Full suite green. Adds the `doctor`
preflight command and friendly, actionable env/setup probe messages.

**Bugbot finding (1, Medium) — fixed:**
1. *Failure panel omits probe warnings* — `render_failure_panel` printed
   title/guidance/detail but not `ProbeResult.warnings`, so a startup failure
   (e.g. `STRIX_LLM` unset) dropped optional-var notes that `strix doctor`
   still shows. → Append warnings to the panel (⚠ yellow, matching the doctor
   report); added `test_13b` asserting they surface. 164 passed.
