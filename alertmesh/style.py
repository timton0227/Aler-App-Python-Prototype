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
import inspect
import json
import sys
import time

from alertmesh.wire import Severity

# Which system the window is on. The page server runs on the same computer as the window,
# so the page can ask Python. Only what the system owns follows it: shortcut keys and the
# order of buttons in a sheet.
MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"

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
    "badge": ("#FF3B30", "#FF453A"),     # system red, as on the iPhone tab bar's counts
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
  margin:8px 0 8px;}}
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

/* The window: a 220-wide sidebar with the tabs, the page, and a status bar along the
   bottom. Below 1100 wide the sidebar shows icons with short labels under them. */
.stSidebar{{width:220px!important;min-width:220px!important;max-width:220px!important;}}
[data-testid="stSidebarHeader"],[data-testid="stSidebarCollapseButton"],[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapsedControl"]{{display:none!important;}}
[data-testid="stSidebarContent"]{{padding:0!important;}}
[data-testid="stSidebarUserContent"]{{padding:14px 10px 120px!important;}}
.stMainBlockContainer{{padding-top:22px!important;padding-bottom:140px!important;max-width:1180px;}}
.am-brand{{display:flex;align-items:center;gap:9px;padding:0 8px 6px;font-weight:600;font-size:18px;}}
.am-appicon{{width:26px;height:26px;border-radius:7px;background:var(--am-red);color:#fff;display:grid;
  place-items:center;flex:none;}}
.am-appicon svg{{width:15px;height:15px;}}
.stSidebar [class*="st-key-nav_"] button{{justify-content:flex-start;padding:6px 10px;min-height:36px;
  border-radius:8px;border:0;}}
.stSidebar [class*="st-key-nav_"] button > div{{width:100%;justify-content:flex-start;}}
.st-key-am_nav{{gap:2px;}}
/* Counts as on the iPhone tab bar: white on the system red. */
.stSidebar [class*="st-key-nav_"] .stMarkdownBadge{{background-color:var(--am-badge)!important;color:#fff!important;
  font-size:12px!important;font-weight:600;border-radius:10px;padding:0 6px;margin-left:6px;
  font-variant-numeric:tabular-nums;}}
.stSidebar [class*="st-key-nav_"] button p{{font-size:14.5px;font-weight:500;}}
.stSidebar [class*="st-key-nav_"] button [data-testid="stMarkdownContainer"],
.stSidebar [class*="st-key-nav_"] button p{{text-align:left;}}
.stSidebar [class*="st-key-nav_"] button[kind="primary"],
.stSidebar [class*="st-key-nav_"] button[data-testid="stBaseButton-primary"]{{background:var(--am-blue-soft);
  color:var(--am-blue);}}
.am-pagetitle{{font-size:22px;font-weight:700;line-height:1.2;margin:0 0 6px;}}
.st-key-am_foot{{position:fixed;bottom:34px;left:10px;width:200px;z-index:2;border-top:1px solid var(--am-sep);
  padding-top:8px;}}
.st-key-open_settings button{{justify-content:flex-start;border:0;background:transparent;text-align:left;}}
.am-statusbar{{position:fixed;left:0;right:0;bottom:0;height:26px;z-index:1000000;display:flex;align-items:center;
  gap:18px;padding:0 14px;font-size:12px;color:var(--am-ink-2);background:var(--am-sidebar);
  border-top:1px solid var(--am-sep);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;}}
.am-statusbar .am-dot{{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:6px;
  background:var(--am-clear);}}
.am-statusbar .am-dot.am-off{{background:var(--am-ink-2);}}
.am-statusbar .am-end{{margin-left:auto;}}
/* The "I need help" bar, pinned to the bottom of Now (EmergencyHelpBarModifier). */
.st-key-am_helpbar{{position:fixed;left:220px;right:0;width:auto!important;bottom:26px;z-index:999;padding:10px 24px;
  background:var(--am-bar);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border-top:1px solid var(--am-sep);}}
.st-key-am_helpbar button{{height:56px;border-radius:16px;border:0;background:var(--am-red);color:#fff;}}
.st-key-am_helpbar button:hover,.st-key-am_helpbar button:focus{{background:var(--am-red);color:#fff;
  filter:brightness(1.08);}}
.st-key-am_helpbar button p{{font-size:19px;font-weight:700;}}
@media (max-width:1100px){{
  .stSidebar{{width:76px!important;min-width:76px!important;max-width:76px!important;}}
  [data-testid="stSidebarUserContent"]{{padding:12px 6px 120px!important;}}
  .am-brand{{justify-content:center;padding:0 0 6px;}}
  .am-brand span:last-child{{display:none;}}
  .stSidebar [class*="st-key-nav_"] button{{padding:6px 2px;flex-direction:column;justify-content:center;gap:2px;}}
  .stSidebar [class*="st-key-nav_"] button [data-testid="stMarkdownContainer"]{{text-align:center;}}
  .stSidebar [class*="st-key-nav_"] button{{position:relative;}}
  .stSidebar [class*="st-key-nav_"] .stMarkdownBadge{{position:absolute;top:3px;right:8px;margin:0;font-size:11px!important;}}
  .stSidebar [class*="st-key-nav_"] button > div,.stSidebar [class*="st-key-nav_"] button > div > span{{
    flex-direction:column;justify-content:center;align-items:center;gap:2px;}}
  .stSidebar [class*="st-key-nav_"] button p{{font-size:11px;text-align:center;}}
  .stSidebar [class*="st-key-nav_"] [data-testid="stIconMaterial"]{{font-size:22px;}}
  .st-key-am_foot{{left:6px;width:64px;}}
  .st-key-open_settings button{{justify-content:center;}}
  .st-key-am_foot [class*="st-key-open_"] button p,.st-key-am_foot .am-hide-compact{{display:none;}}
  .am-clock{{font-size:14px;text-align:center;}}
  .st-key-am_advance{{flex-direction:column;}}
  .st-key-am_helpbar{{left:76px;padding:10px 20px;}}
}}

/* The solid block, only when a warning covers you (NowView.affectedBlock). */
.am-block{{border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:6px;margin-bottom:8px;}}
.am-block svg{{width:34px;height:34px;}}
.am-block .am-lvl{{font-size:30px;font-weight:900;line-height:1.05;letter-spacing:-.01em;}}
.am-block .am-stand{{font-size:18px;font-weight:600;}}
.am-block .am-headline{{font-size:16px;font-weight:600;}}
.am-block .am-meta{{font-size:13.5px;display:flex;gap:12px;flex-wrap:wrap;opacity:.92;}}
.am-status-title{{font-size:18px;font-weight:600;}}
/* "What to do", in large type. */
.am-action{{font-size:20px;font-weight:600;line-height:1.3;margin-top:4px;}}
/* A call for help: red-bordered, never a warning's colours otherwise (CommunityReportStyle). */
.am-help{{border:2px solid var(--am-red);background:linear-gradient(var(--am-red-wash),var(--am-red-wash)),var(--am-card);}}
.am-who{{font-weight:700;color:var(--am-red-text);display:flex;align-items:center;gap:8px;font-size:15.5px;}}
.am-who svg{{width:20px;height:20px;flex:none;}}
.am-note{{font-size:15px;margin:4px 0;}}
.am-row{{display:flex;gap:10px;align-items:center;font-size:15px;margin:6px 0;}}
.am-row svg{{width:20px;height:20px;flex:none;}}
/* Reports from people nearby (CommunityReportStyle): hazard reports and "safe" are grey,
   only calls for help are red. */
.am-rep{{display:flex;gap:12px;align-items:flex-start;}}
.am-rep .am-ic{{width:22px;height:22px;flex:none;color:var(--am-ink-2);}}
.am-rep .am-ic svg{{width:22px;height:22px;}}
.am-rep .am-t{{font-weight:600;font-size:15px;}}
.am-rep.am-help .am-ic,.am-rep.am-help .am-t{{color:var(--am-red-text);}}

.am-fieldlabel{{font-size:14px;margin-bottom:-6px;}}
.st-key-am_how_bad button p{{font-size:13.5px;}}

/* The call-for-help sheet. */
.am-warnline{{font-size:14px;font-weight:600;color:var(--am-red-text);}}
.st-key-sos_send button{{background:var(--am-red);border-color:var(--am-red);color:#fff;}}
.st-key-sos_send button:hover{{background:var(--am-red);border-color:var(--am-red);color:#fff;filter:brightness(1.08);}}

/* Chat: bubbles as in Messages (ChatBubbleStyle: radius 18, yours blue on the right,
   theirs grey on the left; the name above the first of a run, the time under the last). */
.am-convhead{{display:flex;flex-direction:column;align-items:center;gap:1px;padding:4px 0 10px;
  border-bottom:1px solid var(--am-sep);text-align:center;}}
.am-convhead b{{font-size:15px;font-weight:600;}}
.am-convhead span{{font-size:12.5px;color:var(--am-ink-2);}}
.am-msgs{{display:flex;flex-direction:column;gap:3px;padding:6px 4px;}}
.am-msg{{display:flex;flex-direction:column;gap:2px;align-items:flex-start;padding-right:56px;}}
.am-msg.am-gap{{margin-top:10px;}}
.am-msg .am-from{{font-size:12px;color:var(--am-ink-2);padding-left:12px;}}
.am-msg .am-time{{font-size:11.5px;color:var(--am-ink-2);padding:0 12px;}}
.am-msg .am-bub{{padding:7px 12px;border-radius:18px;background:var(--am-other);color:var(--am-ink);font-size:15px;
  max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;}}
.am-msg.am-out{{align-items:flex-end;padding-right:0;padding-left:56px;}}
.am-msg.am-out .am-bub{{background:var(--am-own);color:#fff;}}
.am-listhead{{font-size:12px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:var(--am-ink-2);
  margin:10px 10px 2px;}}
[class*="st-key-chat_"] button{{justify-content:flex-start;border-radius:10px;}}
[class*="st-key-chat_"] button > div{{width:100%;justify-content:flex-start;}}
[class*="st-key-chat_"] .stMarkdownBadge{{background-color:var(--am-blue)!important;color:#fff!important;
  border-radius:10px;padding:0 6px;margin-left:6px;}}
[data-testid="stChatInput"]{{border-radius:18px;}}

/* Warning app: the simulated clock at the foot of the sidebar, and Cancel in red. */
.am-clock{{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1;}}
.st-key-am_advance button{{min-height:28px;padding:2px 10px;border-radius:7px;}}
.st-key-am_advance button p{{font-size:12.5px;}}
[class*="st-key-cancel_"]:not([class*="st-key-cancel_yes_"]):not([class*="st-key-cancel_no_"]) button p{{
  color:var(--am-red-text);}}
[class*="st-key-cancel_yes_"] button{{background:var(--am-red);border-color:var(--am-red);color:#fff;}}

/* The keyboard shortcuts' script takes no room. */
.st-key-am_keys{{display:none!important;}}

/* Side columns move under the main column in a narrow window. */
@media (max-width:1100px){{
  .st-key-am_now [data-testid="stHorizontalBlock"]{{flex-wrap:wrap;}}
  .st-key-am_now [data-testid="stColumn"]{{flex:1 1 100%!important;min-width:100%!important;}}
}}
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


# A lifebuoy, for calls for help: they are never shown with a warning's symbols.
HELP_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true">'
             '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>'
             '<path d="M5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M18.4 5.6l-3.6 3.6M9.2 14.8l-3.6 3.6"/></svg>')

# The fill colour behind each level's block, for the symbol's cut-out.
_FILL_VARIABLE = {"e": "var(--am-red)", "w": "var(--am-watch)", "a": "var(--am-advice)"}


def symbol_on_fill(severity: Severity) -> str:
    return symbol(severity, _FILL_VARIABLE[LEVEL[severity]])


def symbol(severity: Severity, cut_out: str = "var(--am-bg)") -> str:
    """The level's symbol as a small picture in the text's colour. `cut_out` is the colour
    of the "i" or "!" inside it: the background behind the symbol."""
    paths = _SYMBOL_PATHS[severity].replace("var(--am-bg)", cut_out)
    return f'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{paths}</svg>'


# The app's icon: an antenna sending, white on red, as on the iPhone app's icon.
APP_ICON = ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="11" r="2.5"/>'
            '<path d="M11 13h2l1.5 9h-5z"/><path fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" d="M7.8 6.8a6 6 0 0 0 0 8.4M16.2 6.8a6 6 0 0 1 0 8.4M4.9 3.9a10 10 0 0 0 0 14.2'
            'M19.1 3.9a10 10 0 0 1 0 14.2"/></svg>')


def nav(pages: list[tuple[str, str]], badges: dict[str, int], brand: str) -> str:
    """The tabs, as buttons in the sidebar (the iPhone's tab bar on a desktop). A count
    is a red badge, as on the iPhone tab bar. Returns the open tab, kept in
    `st.session_state.view`."""
    import streamlit as st

    state = st.session_state
    state.setdefault("view", pages[0][0])
    st.sidebar.markdown(f'<div class="am-brand"><span class="am-appicon">{APP_ICON}</span><span>{esc(brand)}</span>'
                        f'</div>', unsafe_allow_html=True)
    tabs = st.sidebar.container(key="am_nav")
    for number, (name, icon) in enumerate(pages, start=1):
        count = badges.get(name, 0)
        tabs.button(name + (f" :red-badge[{count}]" if count else ""), key=nav_key(name), icon=icon,
                    type="primary" if state.view == name else "tertiary", width="stretch",
                    on_click=state.update, kwargs={"view": name}, help=f"{name} ({shortcut_label(str(number))})")
    return state.view


def nav_shortcuts(pages: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
    """⌘1, ⌘2, ⌘3 (Ctrl on Windows) for the tabs."""
    return {str(number): {"key": nav_key(name)} for number, (name, _) in enumerate(pages, start=1)}


def nav_key(name: str) -> str:
    return "nav_" + name.lower().replace(" ", "_")


def page_title(title: str) -> None:
    import streamlit as st

    st.markdown(f'<div class="am-pagetitle">{esc(title)}</div>', unsafe_allow_html=True)


def status_bar(items: list[tuple[bool, str]], end: str = "") -> None:
    """The strip along the bottom of the window, on every tab: each item is (on, words)."""
    import streamlit as st

    parts = "".join(f'<span><span class="am-dot{"" if on else " am-off"}"></span>{esc(words)}</span>'
                    for on, words in items)
    st.markdown(f'<div class="am-statusbar">{parts}<span class="am-end">{esc(end)}</span></div>',
                unsafe_allow_html=True)


def updated_text() -> str:
    return "Updated " + time.strftime("%H:%M:%S")


def button_order(main, cancel) -> list:
    """The two buttons of a sheet in the system's order: the main button last on a Mac
    (and Linux), first on Windows. The main button is always the coloured one."""
    return [main, cancel] if WINDOWS else [cancel, main]


def runs(senders: list[tuple[str, int]], gap_ms: int = 5 * 60_000) -> list[tuple[bool, bool]]:
    """For each message (sender, sent at), whether it starts a run and whether it ends
    one. A run is messages from one sender with no more than `gap_ms` between them; the
    name goes above the first, the time under the last."""
    marks = []
    for i, (sender, sent_at) in enumerate(senders):
        first = i == 0 or senders[i - 1][0] != sender or sent_at - senders[i - 1][1] > gap_ms
        last = (i == len(senders) - 1 or senders[i + 1][0] != sender
                or senders[i + 1][1] - sent_at > gap_ms)
        marks.append((first, last))
    return marks


def bubbles(messages: list[tuple[bool, str, str, str, int]]) -> str:
    """Chat messages as bubbles. Each is (yours, sender key, name, text, sent at)."""
    from alertmesh.labels import clock

    rows = []
    for (outgoing, sender, name, text, sent_at), (first, last) in zip(
            messages, runs([(m[1], m[4]) for m in messages])):
        classes = "am-msg" + (" am-out" if outgoing else "") + (" am-gap" if first and rows else "")
        who = f'<span class="am-from">{esc(name)}</span>' if first and not outgoing else ""
        when = f'<span class="am-time">{clock(sent_at)}</span>' if last else ""
        rows.append(f'<div class="{classes}">{who}<span class="am-bub">{esc(text)}</span>{when}</div>')
    return f'<div class="am-msgs">{"".join(rows)}</div>'


def shortcut_label(key: str, shift: bool = False) -> str:
    """How a shortcut is written on this system: "⌘1" and "⌘⇧H" on a Mac, "Ctrl+1" and
    "Ctrl+Shift+H" on Windows."""
    if MAC:
        return "⌘" + ("⇧" if shift else "") + key.upper()
    return "Ctrl+" + ("Shift+" if shift else "") + key.upper()


# Presses the page's own buttons, found by their keys. With ⌘ on a Mac and Ctrl
# elsewhere. A button that is not on the page (the help bar outside Now) is reached by
# first pressing `via` (its tab), then waiting for it to appear.
_SHORTCUT_SCRIPT = """
(function () {
  const doc = window.frameElement ? window.parent.document : document;
  const bindings = %s, mac = %s;
  const press = (key) => { const b = doc.querySelector('.st-key-' + key + ' button');
    if (b && !b.disabled) { b.click(); return true; } return !!b; };
  if (doc.amShortcuts) doc.removeEventListener('keydown', doc.amShortcuts, true);
  doc.amShortcuts = function (e) {
    if (!(mac ? e.metaKey : e.ctrlKey) || e.altKey || (mac && e.ctrlKey)) return;
    const code = e.code || '';
    const key = code.startsWith('Digit') ? code.slice(5) : code === 'Comma' ? ',' :
      code.startsWith('Key') ? code.slice(3).toLowerCase() : (e.key || '').toLowerCase();
    const binding = bindings[(e.shiftKey ? 'shift+' : '') + key];
    if (!binding) return;
    e.preventDefault(); e.stopPropagation();
    if (press(binding.key) || !binding.via) return;
    press(binding.via);
    let tries = 0;
    const again = setInterval(() => { if (press(binding.key) || ++tries > 30) clearInterval(again); }, 100);
  };
  doc.addEventListener('keydown', doc.amShortcuts, true);
})();
"""


def shortcut_script(bindings: dict[str, dict[str, str]]) -> str:
    """The script for `bindings`: {"1": {"key": "nav_now"}, "shift+h": {"key": "need_help",
    "via": "nav_now"}, ...}, where each key is a button's key."""
    return _SHORTCUT_SCRIPT % (json.dumps(bindings), "true" if MAC else "false")


def shortcuts(bindings: dict[str, dict[str, str]]) -> None:
    """Keyboard shortcuts for the page's buttons (see `shortcut_script`)."""
    import streamlit as st

    script = f"<script>{shortcut_script(bindings)}</script>"
    with st.container(key="am_keys"):
        if "unsafe_allow_javascript" in inspect.signature(st.html).parameters:
            st.html(script, unsafe_allow_javascript=True)  # newer Streamlit: in the page itself
        else:
            import streamlit.components.v1 as components

            components.html(script, height=0)  # earlier: in a frame, reaching up to the page


def inject() -> None:
    """Puts the stylesheet on the page. Call once per run, before drawing."""
    import streamlit as st

    st.html(f"<style>{CSS}</style>")


def esc(text: str) -> str:
    return html.escape(text or "")
