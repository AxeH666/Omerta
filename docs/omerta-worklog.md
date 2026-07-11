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

## PR #2 — goal-2: doctor command + friendly messages  ✅ MERGED
Branch: `goal-2-doctor` → `main` (merge commit `f65c720`)

Rebased cleanly onto `main` (post-PR#1). Full suite green. Adds the `doctor`
preflight command and friendly, actionable env/setup probe messages.

**Bugbot finding (1, Medium) — fixed:**
1. *Failure panel omits probe warnings* — `render_failure_panel` printed
   title/guidance/detail but not `ProbeResult.warnings`, so a startup failure
   (e.g. `STRIX_LLM` unset) dropped optional-var notes that `strix doctor`
   still shows. → Append warnings to the panel (⚠ yellow, matching the doctor
   report); added `test_13b` asserting they surface. 164 passed.

---

## PR #3 — goal-3: live agent activity in the CLI  ✅ MERGED
Branch: `goal-3-cli-activity` → `main` (merge commit `c43f0d6`)

Rebased onto `main` (post-PR#2). **Conflict resolved** in `utils.py`: goal-1's
bugbot fix renamed `format_turn_budget` → `format_model_turns`, which collided
with goal-3's new functions inserted at the same spot. Kept the bugbot-fixed
`format_model_turns`, added goal-3's `agent_activity_from_run_dir` /
`build_agent_activity_text`, dropped the resurrected old `format_turn_budget`,
and updated goal-3's regression test to the renamed helper. Full suite green
(177 passed).

Adds honest live agent activity to the non-interactive CLI (lifecycle counts +
named roster) by disk-polling the coordinator's `{run_dir}/.state/agents.json`
snapshot — no change to the scan call signature.

**Bugbot: ✅ no new issues.** Merged.

---

## PR #4 — goal-4: Omerta rebrand + mafia-noir/cyberpunk UI  ✅ MERGED
Branch: `goal-4-omerta-rebrand` → `main` (merge commit `fc58ae5`)
Bugbot: ✅ no new issues.

Rebased via `git rebase --onto main 406f66f` (goal-4's 8 commits only, skipping
the already-merged goal-3 commits). One conflict, in `cli.py`: goal-4 rethemed
the same turn-counter line goal-1's bugbot fix renamed. Resolved to
`format_model_turns(...)` (the fixed helper) with goal-4's `theme.BONE` styling.
The doctor and app.py merges cleanly combined both worlds — the goal-2 warnings
fix + goal-4 rebrand in `render_failure_panel`, and goal-1's thread-safe agent
counts + `format_model_turns` under goal-4's new theme. Full suite green
(177 passed).

Scope (display-only rename, confirmed with the user): rebrands everything a user
reads to OMERTA (banners, panels, CLI help, doctor, TUI splash) with a
noir-cyberpunk palette (blood-red / neon-cyan / bone on near-black), an ASCII
wordmark, and an understated voice — while keeping `STRIX_*` env, `~/.strix`,
`strix_runs/`, the `strix-agent` package, module paths, SARIF tool identity, and
the Apache LICENSE/attribution untouched. Adds an `omerta` CLI entrypoint (with
a `strix` alias). Opening PR, awaiting bugbot.

Note: the pyproject `[project.scripts]` change makes `uv run` want to rebuild
offline (no cached hatchling) — run tests with `.venv/bin/python -m pytest`; a
networked `uv sync` resolves it and also generates the `omerta` launcher.

---

## ✅ Pipeline complete — final state

All four goals are merged into `main`, one PR at a time (no stacking), every
bugbot finding read via the GitHub API and fixed before merge:

| PR | Goal | Bugbot findings | Result |
|----|------|-----------------|--------|
| #1 | honest scan feedback (+ recon docs, guardrails) | 3 Medium — all fixed | merged |
| #2 | doctor command + friendly messages | 1 Medium — fixed | merged |
| #3 | live agent activity in the CLI | 0 | merged |
| #4 | Omerta rebrand + noir/cyberpunk UI | 0 | merged |

**Verified on `main`:** full suite **177 passed**; `omerta` and `strix`
entrypoints both work; `omerta doctor` runs end-to-end and renders the OMERTA
brand with honest ✅/❌ probes (it correctly reports this container's missing
Docker + `STRIX_LLM`).

**Run the tests:** `.venv/bin/python -m pytest tests/ -q`
(Use the venv Python, not `uv run` — the pyproject `[project.scripts]` change
wants an offline rebuild the sandbox can't do; a networked `uv sync` fixes it
and generates the `omerta` launcher.)

**Branches:** all `goal-*` feature branches merged and deleted (local + remote).
