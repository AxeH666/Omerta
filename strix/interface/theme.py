"""Omerta interface theme — mafia-noir meets cyberpunk.

A single source of truth for the interface's *presentation*: the brand,
the palette, the ASCII wordmark, and the small set of headline phrases that
give the UI its voice. Nothing here changes behavior — it only decides how
things look and read. Import these constants instead of scattering literal
hex codes and the word "Strix" across the interface.

The look: near-black backdrop, ``BLOOD`` red as the "family" accent (borders,
danger, the wordmark), ``NEON_CYAN`` as the cyberpunk signal (active work,
links), ``BONE`` for body text and ``GOLD`` brass for the numbers that matter.
The voice is understated — a quiet operator, not a barker.

Internal identifiers (the ``strix`` package, ``STRIX_*`` env vars,
``~/.strix`` config, ``strix_runs/`` output, the ``strix-agent`` distribution)
are deliberately NOT redefined here: this fork rebrands what a user *reads*,
not the on-disk contract or the upstream attribution.
"""

from __future__ import annotations


# --- Brand -----------------------------------------------------------------

BRAND = "OMERTA"
# omertà — the code of silence. The tagline is the whole ethos in three words.
TAGLINE = "silence is the code"
DESCRIPTION = "Omerta — AI enforcers that break into your apps before the wrong people do"


# --- Palette (mafia-noir / cyberpunk) --------------------------------------

NEAR_BLACK = "#0a0a0f"  # backdrop
BLOOD = "#b91c1c"  # deep blood red — brand, borders, danger
BLOOD_BRIGHT = "#ef4444"  # brighter red for emphasis / alarms
NEON_CYAN = "#22d3ee"  # cyberpunk signal — active work, links, "running"
NEON_CYAN_DIM = "#0e7490"  # muted cyan for secondary signal
BONE = "#e7e5e4"  # primary body text (bone white)
ASH = "#6b7280"  # dim / secondary text (cigarette ash)
GOLD = "#d4af37"  # brass — totals, counts, the numbers that matter
AMBER = "#fbbf24"  # cost / soft warning

# Semantic accents (kept legible & conventional; tinted toward the palette).
DANGER = BLOOD_BRIGHT
ACTIVE = NEON_CYAN
DONE = "#65a30d"  # completed — muted olive, not a loud green

# Diff colors deliberately keep the universal green-add / red-remove
# convention — readability wins over palette purity where +/- lines are
# involved. Green added, red removed; both stay distinct on near-black.
DIFF_ADD = "#65a30d"  # added lines / fix_after
DIFF_DEL = BLOOD_BRIGHT  # removed lines / fix_before


# --- ASCII wordmark --------------------------------------------------------
# Block-letter OMERTA. Rendered in BLOOD on the near-black terminal — a
# speakeasy sign with a neon flicker (the tagline underneath in cyan).

WORDMARK = (
    " ██████╗ ███╗   ███╗███████╗██████╗ ████████╗ █████╗ \n"
    "██╔═══██╗████╗ ████║██╔════╝██╔══██╗╚══██╔══╝██╔══██╗\n"
    "██║   ██║██╔████╔██║█████╗  ██████╔╝   ██║   ███████║\n"
    "██║   ██║██║╚██╔╝██║██╔══╝  ██╔══██╗   ██║   ██╔══██║\n"
    "╚██████╔╝██║ ╚═╝ ██║███████╗██║  ██║   ██║   ██║  ██║\n"
    " ╚═════╝ ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝"
)


# --- Voice: headline phrases (the flavor lives here, not in field labels) --
# Functional labels ("Target", "Vulnerabilities", severities) stay plain and
# clear so the tool is still dead-simple to read. Only the headlines carry the
# noir tone.

CONTRACT_OPENED = "The contract is open"
JOB_RUNNING = "The job is running"
FINAL_WORD = "The final word"
# Shown under the startup banner — quiet reassurance, honest about what runs.
STARTUP_NOTE = "Findings surface here as they're made. Nothing leaves this room."


# --- Rich panel styling helpers -------------------------------------------
# The house style for bordered panels: blood border, the OMERTA name in the
# title. One helper keeps every panel consistent.

PANEL_TITLE = f"[bold {BONE}]{BRAND}"


def panel_kwargs(*, accent: str = BLOOD) -> dict[str, object]:
    """Standard Rich ``Panel`` styling for the Omerta look.

    Returns the shared ``title``/``border_style``/``padding`` so call sites
    read ``Panel(body, **panel_kwargs())`` and stay uniform. Pass ``accent``
    to override the border (e.g. ``DANGER`` for a finding card).
    """
    return {
        "title": PANEL_TITLE,
        "title_align": "left",
        "border_style": accent,
        "padding": (1, 2),
    }
