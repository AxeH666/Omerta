# Recon 03 — User-Facing Experience

> Read-only recon of what a person actually sees and interacts with. Every claim
> cites a file that was read. Items marked "inferred" were derived from
> filenames/imports only, not from reading the file body.

## What was read vs inferred

- **Read in full:** `strix/interface/cli.py`, `strix/interface/tui/live_view.py`,
  `strix/report/writer.py`, `strix/report/state.py`,
  `strix/interface/assets/tui_styles.tcss`,
  `strix/interface/tui/renderers/thinking_renderer.py`,
  `strix/interface/tui/renderers/finish_renderer.py`.
- **Read partially:** `strix/interface/tui/app.py` (structure grep + splash / compose /
  help sections — ~300 of 1861 lines).
- **Inferred (not read):** `tui/history.py`, `tui/messages.py`, and most renderers
  (`shell`, `proxy`, `agents_graph`, `filesystem`, `notes`, `todo`, `web_search`,
  `reporting`, `user_message`, `agent_message`). Two of ~14 renderers were read and
  their pattern generalized. The middle of `app.py` (event routing, tree updates) was
  not read; those points are marked inferred.

## 1. The TUI — a polished Textual app

**Library:** **Textual** for the app shell (`App`, `ModalScreen`, `reactive`, `Tree`,
`VerticalScroll`, `TextArea`, `Binding` — `app.py:674, 683-687`), with **Rich**
(`Panel`, `Text`, `Group`, `Align`, `Style`) rendering content inside Textual `Static`
widgets and driving the non-interactive CLI. Real TUI, not text dumps.

**Screens / components:**

- **Splash screen** (`app.py:101-198`) — full ASCII "STRIX" banner (`app.py:104-111`),
  version, tagline "Open-source AI hackers for your apps", animated shimmer on
  "Starting Strix Agent" via a 0.05s timer (`app.py:130-131, 177-198`). Auto-dismisses
  after 4.5s (`app.py:868`).
- **Main layout** (`app.py:765-831`) — horizontal split: a **chat area** (80% width:
  scrolling `chat_history` + a `> ` prompt `ChatTextArea`) and a **sidebar** (20%) with
  three stacked panels: an **agents Tree**, a **VulnerabilitiesPanel**, and a **stats
  panel** (`app.py:809-822`).
- **Modal dialogs** — Help (`app.py:201-211`, a bare keybinding list), Quit confirm
  (`app.py:630`), Stop-Agent confirm (`app.py:217`, "🛑 Stop '<name>'?"), and a
  **Vulnerability detail modal** with copy-to-clipboard (`app.py:265-292`; styled
  `tui_styles.tcss:128-205`).
- **Keybindings** (`app.py:683-687`) — F1 help, Ctrl+Q / Ctrl+C quit, ESC stop selected
  agent; Tab/arrows for panel/tree nav (`app.py:206-207`).

**Polish level: high.** A hand-written 688-line `.tcss` theme (dark `#000000`, green
`#22c55e` accent), hover/focus states, custom scrollbars, dashed tree guides
(`app.py:813-815`), toast notifications (`tui_styles.tcss:11-26`), and per-tool
renderers with emoji + color (🧠 purple "Thinking" `thinking_renderer.py:21-22`; ◆ green
"Penetration test completed" `finish_renderer.py:28-29`). Product-grade "hacker
aesthetic," not a debug console.

## 2. The CLI (non-interactive `-n`) — Rich panels, but coarse

`run_cli` (`cli.py:38-217`) is not raw logging. It prints:

- A green **startup panel** (target + output path, `cli.py:64-80`).
- A `rich.live.Live` **status panel** refreshing every 2s on a background thread —
  "Penetration test in progress" + live stats (`cli.py:157-171, 137-152`).
- Each vulnerability as a **red panel** the moment it is found, via a callback
  (`cli.py:104-120`, wired at `state.py:272-273`).
- A final blue **summary panel** (`cli.py:198-217`).

Absent here: no agent tree, no tool-call stream, no per-agent activity. Non-interactive
mode surfaces only findings + a periodic stats blob. Fine for CI, opaque for a human
watching.

## 3. What the user sees during a scan (real time)

**Interactive TUI: rich and transparent.** The scan streams SDK events through an
`event_sink` into `TuiLiveView.ingest_sdk_event` (`live_view.py:100-116`), which
projects three event kinds per agent:

- **Assistant text streamed token-by-token** (`response.output_text.delta` → incremental
  append, `live_view.py:123-128, 195-202`) — you watch the agent "type."
- **Tool calls** with per-tool renderers (`live_view.py:204-228`).
- **Tool outputs** with success/failure status (`live_view.py:230-260, 353-356`).

The **agents Tree** shows the live multi-agent graph (root + spawned subagents, hydrated
from `agents.json`, `live_view.py:25-48`); selecting an agent shows its stream, ESC stops
it (inferred from the `stop_selected_agent` binding + `events_for_agent`,
`live_view.py:117-118`). Agents are not opaque in interactive mode — arguably a firehose.

**Non-interactive: mostly opaque** (see §2) — findings + stats only.

## 4. The report / output — polished shell, raw security artifacts

On finish, `ReportState._save_artifacts` (`state.py:391-421`) writes a full artifact set
under `strix_runs/<run_name>/`:

- **`penetration_test_report.md`** — executive report: Executive Summary / Methodology /
  Technical Analysis / Recommendations (`writer.py:42-48`, formatted `state.py:373-389`).
- **`vulnerabilities/<id>.md`** — one rich markdown file per finding: title, severity,
  CVE/CWE/CVSS, Description, Impact, Technical Analysis, PoC (fenced code), Code Analysis
  with before/after diff blocks, Remediation (`writer.py:119-197`).
- **`vulnerabilities.csv`** + **`vulnerabilities.json`** — machine indexes,
  severity-sorted (`writer.py:68-92`).
- **`findings.sarif`** — SARIF 2.1.0 for CI / ASPM (GitHub code-scanning); emitted even
  when empty so fixed alerts auto-resolve (`state.py:403-417`).
- **`run.json`** — run record incl. LLM token usage + cost ledger
  (`state.py:419, 466-470`).

**Game-like vs raw:** the framing is deliberately branded/game-like — ASCII art, green
hacker theme, emoji, "AI hackers," `vuln-0001` IDs (`state.py:225`), live red finding
panels. The deliverables, though, are standard professional formats (Markdown + CSV +
JSON + SARIF + CVSS). A polished branded shell over conventional, CI-ready artifacts.

## Honest take — where the UX is weakest

1. **The wall before the polish (biggest risk).** All the nice TUI is gated behind hard
   setup that exits with red error panels: Docker installed *and* an image pulled over
   minutes (`main.py:796-797`), `STRIX_LLM` set or `sys.exit(1)` (`main.py:87-186`), and
   an LLM warm-up round-trip that must succeed or `sys.exit(1)` (`main.py:280-320`). A
   beginner can hit three separate fatal walls before ever seeing the splash. With the
   empty README (1 byte — see recon 01), there is essentially zero in-repo onboarding.

2. **No sense of progress.** Nothing shows % complete, ETA, or phase. The only signals
   are token/cost counters and an opaque turn budget (`DEFAULT_MAX_TURNS = 500`,
   `inputs.py:18`). Default mode is `deep` (long-running, `main.py:452-459`). Interactive
   is a scrolling firehose; non-interactive is a 2s-refreshing "in progress" panel. Both
   are boredom traps on a long scan.

3. **Non-interactive is comparatively blind.** The mode a beginner is most likely to pick
   for "just run it" (`-n`) hides all agent activity, surfacing only findings + stats.
   The transparency lives entirely in the TUI.

4. **Onboarding-free multi-agent complexity.** Help is a bare keybinding list
   (`app.py:206-207`); no tour explains the agents tree, that you can chat with agents,
   or what spawned subagents mean. A whitebox deep scan can fan out many agents into a
   20%-wide tree next to a single chat pane — high cognitive load with no guidance on
   which agent is "talking" (inferred; tree-update code not read).

**Net:** the interface is well-built and transparent once running interactively. The weak
points are all at the edges — brutal setup friction with no docs, no progress/ETA
feedback, and a non-interactive mode that trades away the transparency that makes the TUI
good.
