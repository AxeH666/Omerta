"""Failing tests defining "done" for goal #2: `strix doctor` + friendly messages.

These pin the interface for a real ``strix doctor`` subcommand PLUS the
reuse of the same friendly-message probes at the real startup crash points
(``strix/interface/main.py``). The NEW module ``strix.interface.doctor`` and
the refactors it implies do not exist yet, so groups A-C and the parity guard
FAIL on purpose -- they are the finish line we build toward. The CLI-parsing
regression guard (group D, test 14) protects the EXISTING normal-scan
invocation from being broken by the introduction of subcommands.

Everything here runs on in-memory objects: plain namespaces standing in for
``Settings``, hand-built fake Docker clients, and injected callables. There is
NO real Docker call and NO real network -- each probe takes its dependency by
INJECTION so a "missing/broken" state can be simulated deterministically.

Design contract encoded below (mirrors the goal-1 ``format_*`` helpers and the
existing ``_provider_import_hint`` pattern):
- every probe is a PURE function returning a ``ProbeResult(ok, title,
  guidance, detail, warnings)`` -- it never calls ``sys.exit`` and never
  raises for an expected failure (that is the whole point of the doctor);
- optional env vars are WARNINGS, never failures;
- the doctor renders EVERY item (no early exit) and its exit code is derived
  from the results;
- the real startup path (``validate_environment``) renders the SAME probe
  result it would show in the doctor -- one source of truth, two surfaces.

Following the goal-1 convention, symbols from the not-yet-existing
``strix.interface.doctor`` module are imported INSIDE each test so that test
COLLECTION stays green and each unimplemented case fails on its own.
"""

from __future__ import annotations

import importlib
import io
from types import SimpleNamespace

import pytest
from docker.errors import DockerException, ImageNotFound
from rich.console import Console

from strix.config import loader


# ``strix.interface.__init__`` does ``from .main import main``, so the attribute
# ``strix.interface.main`` is the FUNCTION, not the submodule. Pull the real
# module object out of sys.modules so ``main_mod.parse_arguments`` /
# ``monkeypatch.setattr(main_mod, ...)`` target the module, not the function.
main_mod = importlib.import_module("strix.interface.main")


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

_ENV_KEYS = [
    "STRIX_LLM",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "LLM_API_BASE",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
    "LITELLM_BASE_URL",
    "OLLAMA_API_BASE",
    "PERPLEXITY_API_KEY",
]


@pytest.fixture(autouse=True)
def _reset_loader_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic settings: clear known env vars and the memoized cache."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(loader, "_cached", None)
    monkeypatch.setattr(loader, "_override", None)


def _settings(
    *,
    model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    perplexity_api_key: str | None = None,
) -> SimpleNamespace:
    """A stand-in for ``Settings`` with just the fields the probes read."""
    return SimpleNamespace(
        llm=SimpleNamespace(model=model, api_key=api_key, api_base=api_base),
        integrations=SimpleNamespace(perplexity_api_key=perplexity_api_key),
    )


def _capture_console() -> tuple[Console, io.StringIO]:
    """A wide, non-terminal console so Rich emits plain, unwrapped text."""
    sink = io.StringIO()
    console = Console(file=sink, width=200, force_terminal=False)
    return console, sink


# =========================================================================== #
# A. Detection / message layer -- pure, no Docker, no network
# =========================================================================== #


def test_1_env_probe_missing_strix_llm_fails() -> None:
    """STRIX_LLM unset -> probe ok=False and the guidance names STRIX_LLM."""
    from strix.interface.doctor import probe_llm_env

    result = probe_llm_env(_settings(model=None))

    assert result.ok is False
    assert "STRIX_LLM" in (result.title + result.guidance + result.detail)


def test_2_env_probe_with_strix_llm_passes() -> None:
    """STRIX_LLM set -> probe ok=True."""
    from strix.interface.doctor import probe_llm_env

    result = probe_llm_env(_settings(model="openai/gpt-5.4"))

    assert result.ok is True


def test_3_optional_vars_are_warnings_not_failures() -> None:
    """Required present but optional vars unset -> ok stays True, warnings listed."""
    from strix.interface.doctor import probe_llm_env

    result = probe_llm_env(
        _settings(model="openai/gpt-5.4", api_key=None, api_base=None, perplexity_api_key=None)
    )

    assert result.ok is True, "missing OPTIONAL vars must never be a failure"
    joined = " ".join(result.warnings)
    assert "LLM_API_KEY" in joined
    assert "PERPLEXITY_API_KEY" in joined


def test_4_docker_cli_absent_fails() -> None:
    """`which('docker')` -> None (injected) -> probe ok=False."""
    from strix.interface.doctor import probe_docker_cli

    result = probe_docker_cli(which=lambda _name: None)

    assert result.ok is False
    assert "docker" in (result.title + result.guidance).lower()


def test_5_docker_daemon_down_fails_gracefully() -> None:
    """Daemon down: client.ping() raises DockerException.

    Regression guard for today's traceback (utils.py:1568 raises RuntimeError,
    images.get() escapes uncaught): the probe must RETURN a friendly failure,
    never raise, and never emit a traceback.
    """
    from strix.interface.doctor import probe_docker_daemon

    fake_client = SimpleNamespace(
        ping=lambda: (_ for _ in ()).throw(DockerException("Cannot connect to the Docker daemon"))
    )

    result = probe_docker_daemon(client_factory=lambda: fake_client)  # must not raise

    assert result.ok is False
    assert "docker" in (result.title + result.guidance).lower()
    assert any(word in result.guidance.lower() for word in ("running", "daemon", "desktop"))


def test_6_docker_image_missing_reports_not_present() -> None:
    """images.get raises ImageNotFound -> probe reports the image is not present."""
    from strix.interface.doctor import probe_docker_image

    def _raise_not_found(_name: str) -> None:
        raise ImageNotFound("not found")

    fake_client = SimpleNamespace(images=SimpleNamespace(get=_raise_not_found))

    result = probe_docker_image(client=fake_client, image="ghcr.io/usestrix/strix-sandbox:1.0.0")

    assert result.ok is False
    assert "pull" in result.guidance.lower()
    assert "strix-sandbox" in (result.detail + result.title + result.guidance)


def test_7_bare_unknown_model_name_classified() -> None:
    """A bare, unknown model name with no api_base -> classified 'unknown model name'."""
    from strix.interface.doctor import probe_llm_model_name

    result = probe_llm_model_name(_settings(model="totallyunknownmodel", api_base=None))

    assert result.ok is False
    assert "unknown model name" in (result.title + result.guidance).lower()


def test_8_provider_import_error_yields_install_hint() -> None:
    """A missing-extra ImportError from the warm-up -> the matching install hint."""
    from strix.interface.doctor import probe_llm_connection

    def _raise_boto3() -> None:
        raise ModuleNotFoundError("No module named 'boto3'")

    bedrock = probe_llm_connection(
        model="bedrock/anthropic.claude-4-5-sonnet", run_check=_raise_boto3
    )
    assert bedrock.ok is False
    assert 'pipx install "strix-agent[' in bedrock.guidance
    assert "bedrock" in bedrock.guidance

    def _raise_google() -> None:
        raise ImportError("No module named 'google'")

    vertex = probe_llm_connection(model="vertex_ai/gemini-3-pro-preview", run_check=_raise_google)
    assert vertex.ok is False
    assert 'pipx install "strix-agent[' in vertex.guidance
    assert "vertex" in vertex.guidance


def test_9_generic_llm_error_fails_with_raw_detail_no_network() -> None:
    """A generic warm-up exception -> ok=False and the raw error in detail.

    The round-trip is an INJECTED callable, so no real network call happens.
    """
    from strix.interface.doctor import probe_llm_connection

    def _raise_generic() -> None:
        raise RuntimeError("kaboom-network-unreachable")

    result = probe_llm_connection(model="openai/gpt-5.4", run_check=_raise_generic)

    assert result.ok is False
    assert "kaboom-network-unreachable" in result.detail


def test_9b_llm_connection_ok_when_round_trip_succeeds() -> None:
    """The happy path: an injected round-trip that returns cleanly -> ok=True."""
    from strix.interface.doctor import probe_llm_connection

    result = probe_llm_connection(model="openai/gpt-5.4", run_check=lambda: None)

    assert result.ok is True


# =========================================================================== #
# B. Doctor aggregation / rendering
# =========================================================================== #


def test_10_all_green_prints_checks_and_exit_zero() -> None:
    """Every probe ok -> report shows all items with ✅ and exit code is 0."""
    from strix.interface.doctor import ProbeResult, doctor_exit_code, render_doctor_report

    results = [
        ProbeResult(ok=True, title="Docker CLI", guidance="", detail=""),
        ProbeResult(ok=True, title="Docker daemon", guidance="", detail=""),
        ProbeResult(ok=True, title="Sandbox image", guidance="", detail=""),
        ProbeResult(ok=True, title="LLM configuration", guidance="", detail=""),
        ProbeResult(ok=True, title="LLM connection", guidance="", detail=""),
    ]

    console, sink = _capture_console()
    render_doctor_report(results, console)
    out = sink.getvalue()

    assert doctor_exit_code(results) == 0
    assert "❌" not in out
    assert "✅" in out
    for r in results:
        assert r.title in out


def test_11_one_red_still_renders_every_item_and_exits_nonzero() -> None:
    """A failure in the MIDDLE must not short-circuit: all items still render."""
    from strix.interface.doctor import ProbeResult, doctor_exit_code, render_doctor_report

    results = [
        ProbeResult(ok=True, title="Docker CLI", guidance="", detail=""),
        ProbeResult(
            ok=False,
            title="Docker daemon",
            guidance="Start Docker Desktop and re-run.",
            detail="",
        ),
        ProbeResult(ok=True, title="Sandbox image", guidance="", detail=""),
        ProbeResult(ok=True, title="LLM configuration", guidance="", detail=""),
        ProbeResult(ok=True, title="LLM connection", guidance="", detail=""),
    ]

    console, sink = _capture_console()
    render_doctor_report(results, console)
    out = sink.getvalue()

    assert doctor_exit_code(results) != 0
    assert "❌" in out
    # No early exit: the items AFTER the failing one are still present.
    for r in results:
        assert r.title in out
    assert "Start Docker Desktop" in out


# =========================================================================== #
# C. CLI: the `doctor` subcommand
# =========================================================================== #


def test_12_doctor_subcommand_parses_without_a_target() -> None:
    """`strix doctor` must parse WITHOUT --target and not trip 'target required'."""
    args = main_mod.parse_arguments(["doctor"])

    assert getattr(args, "command", None) == "doctor"


# =========================================================================== #
# D. Startup-reuse parity + CLI regression guard
# =========================================================================== #


def test_13_startup_reuses_the_same_env_probe_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real startup path renders the SAME probe result the doctor would show.

    We monkeypatch ``probe_llm_env`` (as referenced from ``main``) to return a
    sentinel failure and assert ``validate_environment`` renders that exact
    guidance and exits 1 -- proving one source of truth, two surfaces.
    """
    from strix.interface.doctor import ProbeResult

    sentinel = ProbeResult(
        ok=False,
        title="LLM configuration",
        guidance="SENTINEL_GUIDANCE_TOKEN_9Z",
        detail="",
    )
    monkeypatch.setattr(main_mod, "probe_llm_env", lambda _settings: sentinel, raising=False)

    console, sink = _capture_console()
    with pytest.raises(SystemExit) as excinfo:
        main_mod.validate_environment(console=console)

    assert excinfo.value.code == 1
    assert "SENTINEL_GUIDANCE_TOKEN_9Z" in sink.getvalue()


def test_13b_startup_failure_panel_surfaces_probe_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The startup failure panel must show the probe's warnings, like doctor.

    ``probe_llm_env`` attaches optional-var notes even on a hard failure
    (e.g. STRIX_LLM unset). ``render_failure_panel`` must surface them so the
    startup crash and ``strix doctor`` present the exact same result -- not a
    lossy subset that silently drops the notes.
    """
    from strix.interface.doctor import ProbeResult

    sentinel = ProbeResult(
        ok=False,
        title="LLM configuration",
        guidance="Set STRIX_LLM",
        detail="",
        warnings=["OPTIONAL_WARNING_TOKEN_7Q is not set"],
    )
    monkeypatch.setattr(main_mod, "probe_llm_env", lambda _settings: sentinel, raising=False)

    console, sink = _capture_console()
    with pytest.raises(SystemExit):
        main_mod.validate_environment(console=console)

    assert "OPTIONAL_WARNING_TOKEN_7Q" in sink.getvalue()


def test_14_normal_scan_invocation_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """REGRESSION GUARD: introducing subcommands must not break `strix --target ...`."""
    monkeypatch.setenv("STRIX_LLM", "openai/gpt-5.4")

    args = main_mod.parse_arguments(["--target", "example.com"])

    assert getattr(args, "command", None) != "doctor"
    assert args.targets_info
    assert args.targets_info[0]["original"] == "example.com"
