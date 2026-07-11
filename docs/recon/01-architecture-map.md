# Recon 01 — Architecture Map

> Read-only recon of the Strix (upstream) codebase. Every claim below cites a file
> that was actually read. Items explicitly marked "inferred" were derived from
> filenames/imports only, not from reading the file body.

## 1. Entry point

- **CLI command:** `strix`, declared in `pyproject.toml:52` → `strix = "strix.interface.main:main"`.
  Package name is `strix-agent`, version `1.0.4` (`pyproject.toml:2-3`).
- **`main()`** lives at `strix/interface/main.py:785`. Flow:
  `configure_dependency_logging()` → `parse_arguments()` (`main.py:791`) → optional config
  override → `check_docker_installed()` + `pull_docker_image()` (`main.py:796-797`) →
  `validate_environment()` + `warm_up_llm()` (`main.py:799-800`) → clones repos / resolves
  diff-scope for code targets (`main.py:806-848`) → starts telemetry → dispatches to either
  `run_cli(args)` (non-interactive) or `run_tui(args)` (interactive TUI) at `main.py:862-865`.
- **Note:** `README.md` is empty (1 byte), so there is no prose description to cross-check
  against — the map is derived purely from code.

## 2. Top-level structure (subpackages of `strix/`)

| Package | Responsibility (from files read) |
|---|---|
| `interface/` | CLI entry, argument parsing, TUI. `main.py`, `cli.py`, `utils.py`, `tui/` |
| `core/` | Scan orchestration & the outer agent loop: `runner.py` (top-level `run_strix_scan`), `execution.py` (`run_agent_loop`/`_run_cycle`), `agents.py` (`AgentCoordinator` graph state), `sessions.py`, `hooks.py`, `inputs.py`, `paths.py` |
| `agents/` | Agent *construction*: `factory.py` (`build_strix_agent`, tool assembly), `prompt.py` (system-prompt rendering), `prompts/` |
| `tools/` | Host-side agent tools, one subpackage per family: `agents_graph`, `proxy`, `notes`, `todo`, `reporting`, `finish`, `load_skill`, `thinking`, `web_search`, `shell`, `apply_patch`, `agent_browser`, `view_image` |
| `runtime/` | Sandbox lifecycle: `session_manager.py`, `docker_client.py`, `backends.py`, `caido_bootstrap.py` |
| `report/` | Findings output: `state.py`, `writer.py`, `sarif.py`, `dedupe.py`, `usage.py` |
| `config/` | Settings/model config: `settings.py`, `loader.py`, `models.py` |
| `skills/` | Skill content (knowledge packs) loaded on demand — subdirs like `vulnerabilities`, `reconnaissance`, `frameworks`, `protocols`, etc. |
| `telemetry/` | `posthog.py`, `scarf.py`, logging setup |
| `utils/` | `resource_paths.py` helpers |

Not yet read (descriptions inferred from filenames/imports only): `interface/cli.py`,
`interface/tui/`, `agents/prompt.py`, `skills/*`, and most `tools/*` bodies.

## 3. The agent loop

**Strix does not implement the inner build-context → call-model → parse → run-tool →
feed-result cycle itself.** That cycle is delegated to the **OpenAI Agents SDK**
(`openai-agents[litellm]==0.14.6`, `pyproject.toml:36`). The actual model call / tool
dispatch happens inside `Runner.run_streamed(...)`, invoked at `strix/core/execution.py:352`.

What Strix owns is the **outer orchestration loop** around that SDK call:

- **`strix/core/execution.py`**
  - `_run_cycle()` (`execution.py:334`) — one SDK streamed run: calls `Runner.run_streamed`
    (line 352), pumps `stream.stream_events()` to the `event_sink` (line 364), with recovery
    logic (image-strip + retry on 400/404/422 input rejections, `execution.py:400-419`;
    budget-stop handling, `393-399`).
  - `run_agent_loop()` (`execution.py:41`) — the persistent per-agent loop. Interactive mode
    blocks on `coordinator.wait_for_message()` then re-runs a cycle (`execution.py:95-118`).
  - `_run_noninteractive_until_lifecycle()` (`execution.py:266`) — keeps re-running cycles
    until the agent calls a lifecycle tool (`finish_scan`/`agent_finish`), forcing continuation
    if it emits plain text (`execution.py:304-331`).
  - Stop condition: `_finish_tool_use_behavior` in `agents/factory.py:300` tells the SDK a run
    is "final" only when a lifecycle tool reports success.

- **`strix/core/runner.py`** — `run_strix_scan()` (`runner.py:54`) sets up the sandbox,
  `RunConfig`/`StrixProvider` (`runner.py:162`), builds the root agent via `build_strix_agent`
  (`runner.py:173`), and kicks off the root `run_agent_loop` (`runner.py:270`).

- **`strix/core/agents.py`** — `AgentCoordinator` (`agents.py:33`) is the shared state for the
  multi-agent graph: statuses, parent/child topology, inter-agent message passing
  (`send`/`wait_for_message`, `agents.py:123-162`), and resume snapshots to `agents.json`.

Agents and their toolset are built in `strix/agents/factory.py:352` (`build_strix_agent`) — a
`SandboxAgent` with `_BASE_TOOLS` (`factory.py:322`) plus `finish_scan` (root) or `agent_finish`
(child), and `Filesystem`/`Shell` sandbox capabilities.

## 4. Surprises / unusual notes

1. **The core "agent loop" is a dependency, not Strix code.** The novel part of Strix is the
   *multi-agent coordination layer* (`AgentCoordinator`, spawn/message/resume), not the LLM
   tool-calling loop — that's the SDK's `Runner`.
2. **Everything runs inside Docker sandboxes.** `main.py` hard-requires Docker and pulls an
   image before doing anything (`main.py:796-797`); agents get `Shell`/`Filesystem`
   capabilities bound to a live container session (`factory.py:399-410`).
3. **Full resume/snapshot machinery.** The coordinator atomically snapshots graph state to
   `agents.json` and can rebuild the whole agent tree, replaying each subagent's SDK session
   from `agents.db` (`runner.py:114-138`, `execution.py:185-264` `respawn_subagents`).
4. **Chat-Completions vs Responses dual pathway.** `factory.py` re-wraps tools depending on
   whether the model backend supports Responses-style custom tools
   (`_custom_tool_as_function_tool`, `_configure_chat_completions_filesystem_tools`,
   lines 124-167).
5. **Two telemetry sinks fire by default** (PostHog + Scarf, `main.py:857-858`), including on
   unhandled exceptions.
6. **Help text references placeholder/future model names** (`openai/gpt-5.4`,
   `anthropic/claude-opus-4-7`, `main.py:108-109, 148`) — cosmetic.
