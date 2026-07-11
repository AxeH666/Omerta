"""Preflight environment checks ("doctor") + reusable friendly-failure probes.

Every setup check the CLI performs at startup is expressed here as a PURE
``probe_*`` function that returns a :class:`ProbeResult` -- it never calls
``sys.exit`` and never raises for an *expected* failure. That single design
choice is what lets the SAME logic back two surfaces:

* ``strix doctor`` -- runs every probe and renders a per-item report, never
  short-circuiting on the first failure, so the user sees the whole picture;
* the real startup path (``strix/interface/main.py``) -- renders the very same
  probe result before exiting, so the friendly message has one source of truth.

Each probe takes its external dependency by INJECTION (the ``which`` lookup, a
Docker client factory, a Docker client, or a zero-arg round-trip callable) so a
"missing/broken" state can be simulated deterministically in tests without a
real Docker daemon or a real network call.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import docker
from docker.errors import ImageNotFound
from rich.panel import Panel
from rich.text import Text

from strix.config.models import is_known_openai_bare_model
from strix.interface import theme


if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import Console


@dataclass
class ProbeResult:
    """The outcome of one preflight check.

    ``ok`` drives ✅/❌ and the overall exit code. ``title`` is the item label.
    ``guidance`` is the actionable, human next step shown on failure. ``detail``
    carries the raw underlying error (never invented). ``warnings`` are
    non-fatal notes (e.g. missing OPTIONAL env vars) that must NOT flip ``ok``.
    """

    ok: bool
    title: str
    guidance: str = ""
    detail: str = ""
    warnings: list[str] = field(default_factory=list)


def _provider_import_hint(exc: BaseException, model: str) -> str | None:
    """Return an install hint when *exc* is a missing provider dependency.

    Bedrock and Vertex AI ship as optional extras: Bedrock needs ``boto3`` and
    Vertex AI needs ``google-auth``. When either is absent, litellm raises an
    ``ImportError``/``ModuleNotFoundError`` naming the missing package. Map that
    back to the matching extra so the user knows what to install. Returns
    ``None`` for any unrelated error.
    """
    if not isinstance(exc, ImportError):
        return None
    message = str(exc)
    model_name = model.lower()
    if "boto3" in message and model_name.startswith("bedrock/"):
        return 'Bedrock support is optional. Install it with: pipx install "strix-agent[bedrock]"'
    if "google" in message and "vertex" in model_name:
        return 'Vertex AI support is optional. Install it with: pipx install "strix-agent[vertex]"'
    return None


# --------------------------------------------------------------------------- #
# Probes -- pure, dependency-injected
# --------------------------------------------------------------------------- #


def probe_llm_env(settings: Any) -> ProbeResult:
    """Check that the REQUIRED model config (``STRIX_LLM``) is present.

    Missing OPTIONAL vars (API key, base URL, Perplexity key) are surfaced as
    ``warnings`` and never flip ``ok`` -- they are legitimately absent for local
    models, Vertex AI, AWS, etc.
    """
    llm = settings.llm
    warnings: list[str] = []
    if not getattr(llm, "api_key", None):
        warnings.append("LLM_API_KEY is not set (fine for local models, Vertex AI, AWS, etc.)")
    if not getattr(llm, "api_base", None):
        warnings.append("LLM_API_BASE is not set (needed only for local models, e.g. Ollama)")
    if not getattr(settings.integrations, "perplexity_api_key", None):
        warnings.append("PERPLEXITY_API_KEY is not set (disables real-time web research)")

    if not getattr(llm, "model", None):
        return ProbeResult(
            ok=False,
            title="LLM configuration",
            guidance=(
                "STRIX_LLM is not set. Set it to the model to use, e.g.\n"
                "  export STRIX_LLM='openai/gpt-5.4'\n"
                "Use the '<provider>/<model>' form for non-OpenAI providers, "
                "e.g. 'anthropic/claude-opus-4-7'."
            ),
            warnings=warnings,
        )
    return ProbeResult(ok=True, title="LLM configuration", warnings=warnings)


def probe_docker_cli(which: Callable[[str], str | None] = shutil.which) -> ProbeResult:
    """Check that the ``docker`` CLI is on PATH (lookup injected as ``which``)."""
    if which("docker") is None:
        return ProbeResult(
            ok=False,
            title="Docker CLI",
            guidance=(
                "The 'docker' command was not found in your PATH. Install Docker "
                "and make sure the 'docker' command is available."
            ),
        )
    return ProbeResult(ok=True, title="Docker CLI")


def probe_docker_daemon(
    client_factory: Callable[[], Any] | None = None,
) -> ProbeResult:
    """Check that the Docker daemon is reachable by actually pinging it.

    The ping is what closes today's traceback gap: ``docker.from_env()`` alone
    does not contact the daemon, so a stopped daemon otherwise surfaces as an
    uncaught error deep in the pull path. Here any failure -- factory or ping --
    is caught and returned as a friendly result; this function never raises.
    """
    factory = client_factory if client_factory is not None else docker.from_env
    try:
        client = factory()
        client.ping()
    except Exception as exc:  # noqa: BLE001 - a doctor probe never propagates
        return ProbeResult(
            ok=False,
            title="Docker daemon",
            guidance=(
                "Cannot connect to the Docker daemon. Make sure Docker Desktop "
                "is installed and running, then re-run."
            ),
            detail=str(exc),
        )
    return ProbeResult(ok=True, title="Docker daemon")


def probe_docker_image(client: Any, image: str) -> ProbeResult:
    """Check whether the sandbox image is already present locally.

    An absent image is not fatal for a real scan (it is pulled on first run), so
    the guidance says exactly that rather than pretending the tool is broken.
    """
    try:
        client.images.get(image)
    except ImageNotFound:
        return ProbeResult(
            ok=False,
            title="Sandbox image",
            guidance=(
                f"Image not present locally. It is pulled automatically on first "
                f"run, or pull it now: docker pull {image}"
            ),
            detail=f"{image} not present locally",
        )
    except Exception as exc:  # noqa: BLE001 - a doctor probe never propagates
        return ProbeResult(
            ok=False,
            title="Sandbox image",
            guidance=f"Could not query the image. Try: docker pull {image}",
            detail=str(exc),
        )
    return ProbeResult(ok=True, title="Sandbox image", detail=image)


def probe_llm_model_name(settings: Any) -> ProbeResult:
    """Classify a bare, unknown model name (mirrors the warm-up guard).

    A bare name (no ``provider/`` prefix) that is not a known OpenAI model and
    has no custom ``api_base`` would silently route to OpenAI -- almost never
    what the user meant, so flag it instead of failing later with a cryptic API
    error.
    """
    llm = settings.llm
    raw_model = (getattr(llm, "model", None) or "").strip()
    api_base = getattr(llm, "api_base", None)
    is_bare_name = bool(raw_model) and "/" not in raw_model
    if is_bare_name and not is_known_openai_bare_model(raw_model) and not api_base:
        return ProbeResult(
            ok=False,
            title="Unknown model name",
            guidance=(
                f"'{raw_model}' is not a known OpenAI model. Bare names route to "
                "OpenAI by default. If you meant another provider, use the "
                "'<provider>/<model>' form, e.g. 'anthropic/claude-opus-4-7'."
            ),
        )
    return ProbeResult(ok=True, title="LLM model name")


def probe_llm_connection(model: str, run_check: Callable[[], Any]) -> ProbeResult:
    """Check the live LLM round-trip, injected as ``run_check``.

    ``run_check`` performs one real request and raises on any failure; injecting
    it keeps this function pure and network-free under test. A raised
    ``ImportError`` for an optional provider extra is turned into an install
    hint; every other error is reported verbatim in ``detail``.
    """
    try:
        run_check()
    except Exception as exc:  # noqa: BLE001 - a doctor probe never propagates
        hint = _provider_import_hint(exc, model)
        guidance = hint or (
            "Could not establish a connection to the language model. Check your "
            "model name, API key, and base URL, then try again."
        )
        return ProbeResult(ok=False, title="LLM connection", guidance=guidance, detail=str(exc))
    return ProbeResult(ok=True, title="LLM connection")


# --------------------------------------------------------------------------- #
# Aggregation / rendering
# --------------------------------------------------------------------------- #


def doctor_exit_code(results: list[ProbeResult]) -> int:
    """0 only if every probe passed, else 1 -- so the doctor is CI-usable."""
    return 0 if all(r.ok for r in results) else 1


def render_doctor_report(results: list[ProbeResult], console: Console) -> None:
    """Render every item with ✅/❌ + guidance -- NO early exit on failure.

    Rendering the whole list (not stopping at the first ❌) is the point: the
    user gets one complete picture of what to fix.
    """
    console.print()
    console.print(f"{theme.BRAND} DOCTOR", style=f"bold {theme.BLOOD}")
    console.print()
    for result in results:
        marker = "✅" if result.ok else "❌"
        line = Text()
        line.append(f"{marker} ")
        line.append(result.title, style="bold" if result.ok else "bold red")
        console.print(line)
        if not result.ok and result.guidance:
            for gline in result.guidance.splitlines():
                console.print(Text(f"     → {gline}"))
        if not result.ok and result.detail:
            console.print(Text(f"     {result.detail}", style="dim"))
        for warning in result.warnings:
            console.print(Text(f"     ⚠  {warning}", style="yellow"))
    console.print()


def render_failure_panel(result: ProbeResult, console: Console) -> None:
    """Render a single failing probe as the red STRIX panel used at startup.

    This is the reuse point: a startup crash site renders the same ``result``
    (title + guidance + raw detail + non-fatal warnings) the doctor would show,
    so the two surfaces never diverge. Warnings are included because
    ``probe_llm_env`` attaches optional-var notes (e.g. LLM_API_KEY unset) even
    on a hard failure, and dropping them here would hide guidance the doctor
    still prints.
    """
    text = Text()
    text.append(result.title, style="bold red")
    if result.guidance:
        text.append("\n\n")
        text.append(result.guidance)
    if result.detail:
        text.append("\n\n")
        text.append(result.detail, style="dim")
    for warning in result.warnings:
        text.append("\n\n")
        text.append(f"⚠  {warning}", style="yellow")

    panel = Panel(
        text,
        title=theme.PANEL_TITLE,
        title_align="left",
        border_style=theme.DANGER,
        padding=(1, 2),
    )
    console.print("\n")
    console.print(panel)
    console.print()
