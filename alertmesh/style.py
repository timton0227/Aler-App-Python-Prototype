"""The iPhone app's look, for both desktop apps: colours, typeface and one stylesheet.

Ported from (values, light / dark), as written down in docs/desktop-design.md:
- ../alert-mesh/AlertMesh/Utils/Theme.swift (ThemePalette.alertMesh, severity fill and text colours)
- ../alert-mesh/AlertMesh/AlertMesh/Views/EmergencyLayout.swift (card radius 16, padding 18, gap 16;
  the system typeface, never monospace)
- ../alert-mesh/AlertMesh/AlertMesh/Views/ChatBubbleRow.swift (ChatBubbleStyle)

Streamlit draws its own widgets from THEME (both apps, light and dark). What Streamlit
has no setting for is drawn by small HTML blocks with the classes in CSS; every colour
there is a variable with a dark partner, so the page follows the system's light or dark
setting as the iPhone app does.

This is free and unencumbered software released into the public domain.
"""
import html

from alertmesh.wire import Severity

# The system typeface: SF Pro on a Mac, Segoe UI Variable on Windows. No bundled font.
# Names without quotes, so the same text works in a Streamlit flag and in CSS.
FONT = ("-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, "
        "system-ui, sans-serif")

# Streamlit's theme settings, by config section. `.streamlit/config.toml` holds the same
# values (a test checks), and desktop.py passes them as flags, because the packaged apps
# start where that file is not found.
THEME: dict[str, dict[str, object]] = {
    "theme": {"baseFontSize": 15},
    "theme.light": {
        "font": FONT,
        "primaryColor": "#007AFF",
        "backgroundColor": "#FFFFFF",
        "secondaryBackgroundColor": "#F2F2F7",
        "textColor": "#000000",
        "linkColor": "#005FCC",
    },
    "theme.light.sidebar": {"backgroundColor": "#F5F5F7"},
    "theme.dark": {
        "font": FONT,
        "primaryColor": "#0A84FF",
        "backgroundColor": "#000000",
        "secondaryBackgroundColor": "#1C1C1E",
        "textColor": "#FFFFFF",
        "linkColor": "#4DA3FF",
    },
    "theme.dark.sidebar": {"backgroundColor": "#161618"},
}


def streamlit_flags() -> dict[str, str]:
    """THEME as Streamlit command-line settings, "theme.light.primaryColor" -> "#007AFF"."""
    return {f"{section}.{name}": str(value) for section, options in THEME.items() for name, value in options.items()}


# Colour tokens for the HTML blocks, light / dark. Names match the design's colour table.
TOKENS: dict[str, tuple[str, str]] = {
    "bg": ("#FFFFFF", "#000000"),
    "card": ("#F2F2F7", "#1C1C1E"),
    "sidebar": ("#F5F5F7", "#161618"),
    "ink": ("#000000", "#FFFFFF"),
    "ink-2": ("rgba(60,60,67,.62)", "rgba(235,235,245,.62)"),
    "sep": ("rgba(60,60,67,.29)", "rgba(84,84,88,.65)"),
    "blue": ("#007AFF", "#0A84FF"),
    "blue-soft": ("rgba(0,122,255,.12)", "rgba(10,132,255,.2)"),
    "own": ("#0066DD", "#0A6CFF"),       # your chat bubble
    "other": ("#E9E9EB", "#26252A"),     # their chat bubble
    "red": ("#BF1A1A", "#BF1A1A"),       # Emergency Warning fill, calls for help, the help bar
    "red-text": ("#B01414", "#FF6B6B"),
    "red-wash": ("rgba(191,26,26,.08)", "rgba(255,80,80,.12)"),
    "watch": ("#D16600", "#FF9426"),
    "watch-text": ("#9A3D00", "#FF9E4D"),
    "advice": ("#B88A00", "#FFD633"),
    "advice-text": ("#8A6200", "#FFD84D"),
    "clear": ("#1E7B34", "#30D158"),     # all clear
    "bar": ("rgba(255,255,255,.86)", "rgba(22,22,24,.86)"),
}

# Short class suffix for each warning level: am-fill-e, am-t-w, am-bar-a, ...
LEVEL = {Severity.ADVICE: "a", Severity.WATCH_AND_ACT: "w", Severity.EMERGENCY_WARNING: "e"}


def _variables(which: int) -> str:
    return "".join(f"--am-{name}:{pair[which]};" for name, pair in TOKENS.items())


CSS = f"""
:root{{{_variables(0)}--am-f:{FONT};}}
@media (prefers-color-scheme: dark){{:root{{{_variables(1)}}}}}

/* Cards (EmergencyLayout: radius 16, padding 18, 16 between blocks). */
.am-card{{background:var(--am-card);border-radius:16px;padding:16px 18px;border:1px solid var(--am-sep);
  color:var(--am-ink);margin-bottom:16px;}}
.am-section{{font-size:13px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:var(--am-ink-2);
  margin:4px 0 8px;}}
.am-muted{{color:var(--am-ink-2);font-size:13.5px;}}
.am-headline{{font-size:16px;font-weight:600;}}
.am-level{{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;}}
.am-level svg,.am-ic svg{{width:15px;height:15px;flex:none;}}

/* A level as a solid fill: only the red is dark enough for white text. */
.am-fill-e{{background:var(--am-red);color:#fff;}}
.am-fill-w{{background:var(--am-watch);color:#000;}}
.am-fill-a{{background:var(--am-advice);color:#000;}}
/* A level as text on a grey card: the darker text colours, 4.5:1 contrast. */
.am-t-e{{color:var(--am-red-text);}}
.am-t-w{{color:var(--am-watch-text);}}
.am-t-a{{color:var(--am-advice-text);}}
.am-bar-e{{background:var(--am-red);}}
.am-bar-w{{background:var(--am-watch);}}
.am-bar-a{{background:var(--am-advice);}}
.am-border-e{{border:2px solid var(--am-red);}}
.am-border-w{{border:2px solid var(--am-watch);}}
.am-border-a{{border:2px solid var(--am-advice);}}
.am-clear{{color:var(--am-clear);}}

/* A warning as a card with a colour bar (every warning that does not cover you). */
.am-other{{display:flex;gap:12px;align-items:stretch;}}
.am-other .am-colourbar{{width:6px;border-radius:3px;flex:none;}}
.am-other .am-headline{{margin:3px 0 4px;}}

/* The solid block, only when a warning covers you (NowView.affectedBlock). */
.am-block{{border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:6px;margin-bottom:16px;}}
.am-block svg{{width:34px;height:34px;}}
.am-block .am-lvl{{font-size:30px;font-weight:900;line-height:1.05;letter-spacing:-.01em;}}
.am-block .am-stand{{font-size:18px;font-weight:600;}}
.am-block .am-headline{{font-size:16px;font-weight:600;}}
.am-block .am-meta{{font-size:13.5px;display:flex;gap:12px;flex-wrap:wrap;opacity:.92;}}
"""

# The level shown by a symbol as well as by colour (AlertSeverity.symbolName): circle-i
# for Advice, triangle for Watch and Act, octagon for Emergency Warning.
_SYMBOL_PATHS = {
    Severity.ADVICE: '<circle cx="12" cy="12" r="10"/><path fill="var(--am-bg)" d="M11 10h2v7h-2zM11 6.5h2v2h-2z"/>',
    Severity.WATCH_AND_ACT: ('<path d="M12 2.5 1.5 21h21z"/>'
                             '<path fill="var(--am-bg)" d="M11 9h2v6h-2zM11 16.5h2v2h-2z"/>'),
    Severity.EMERGENCY_WARNING: ('<path d="M8 2h8l6 6v8l-6 6H8l-6-6V8z"/>'
                                 '<path fill="var(--am-bg)" d="M11 6.5h2v7h-2zM11 15.5h2v2h-2z"/>'),
}


def symbol(severity: Severity, cut_out: str = "var(--am-bg)") -> str:
    """The level's symbol as a small picture in the text's colour. `cut_out` is the colour
    of the "i" or "!" inside it: the background behind the symbol."""
    paths = _SYMBOL_PATHS[severity].replace("var(--am-bg)", cut_out)
    return f'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{paths}</svg>'


def inject() -> None:
    """Puts the stylesheet on the page. Call once per run, before drawing."""
    import streamlit as st

    st.html(f"<style>{CSS}</style>")


def esc(text: str) -> str:
    return html.escape(text or "")
