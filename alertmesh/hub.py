"""The evacuation-centre board: every live official warning, sized to be read from
across a hall rather than from a desk.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Views/HubBoardView.swift
(hero card, rows, hidden count, footer, clock, empty state, English strings).

It is a display, not a screen you operate: the most serious warning is always the
one in large type, the rest are listed under it, and a count in the footer says how
many did not fit, so no warning goes missing quietly.

Added for the prototype (not on the Swift board): a list of calls for help the
centre has heard, under the warnings. In the app the Mac notifies for these instead.

This is free and unencumbered software released into the public domain.
"""
import html
from dataclasses import dataclass

from alertmesh import labels, places
from alertmesh.reports import CommunityReport, ReportKind
from alertmesh.wire import OfficialAlert

# Enough to show what else is happening without shrinking the one warning that
# matters most.
MAX_ROWS = 3

TITLE = "Evacuation centre board"
EMPTY_TITLE = "No current warnings"
EMPTY_BODY = ("This board is live. A warning appears here the moment it arrives, over the internet "
              "or from a phone that carried it.")
ACTION_TITLE = "What to do"
SOS_TITLE = "Calls for help nearby"


def hidden_count(total: int) -> int:
    """Warnings that do not fit. `total` counts every live warning, the hero included."""
    return max(0, total - 1 - MAX_ROWS)


def peers_text(count: int) -> str:
    return "No devices nearby yet" if count <= 0 else f"{count} devices nearby"


def more_text(count: int) -> str:
    return f"{count} more warnings not shown"


@dataclass(frozen=True)
class Board:
    hero: OfficialAlert | None
    rows: list[OfficialAlert]
    hidden: int
    peers: int
    sos: list[CommunityReport]


def board(live_alerts: list[OfficialAlert], peers: int, live_reports: list[CommunityReport] = ()) -> Board:
    """What the board shows. `live_alerts` must be in the store's order, most severe
    first, so the first one is the worst."""
    hero = live_alerts[0] if live_alerts else None
    return Board(hero, list(live_alerts[1:1 + MAX_ROWS]), hidden_count(len(live_alerts)), peers,
                 [r for r in live_reports if r.kind is ReportKind.SOS])


# --- Drawing ------------------------------------------------------------------
# True sizes in pixels, far larger than a desk screen's: the headline has to be read
# from the back of a hall (the Swift board sets its own point sizes for the same reason).


def _hero_html(alert: OfficialAlert, now_ms: int) -> str:
    fill, on_fill = labels.SEVERITY_FILL[alert.severity], labels.SEVERITY_ON_FILL[alert.severity]
    action = ""
    if alert.action_text:
        action = (f'<div style="font-size:22px;font-weight:600;opacity:.65;margin-top:18px">{ACTION_TITLE}</div>'
                  f'<div style="font-size:40px;font-weight:600;line-height:1.15">{html.escape(alert.action_text)}</div>')
    cells = "&nbsp;&nbsp;".join(f"#{c}" for c in alert.area_cells)
    return f"""
<div style="border-radius:10px;overflow:hidden;border:2px solid {fill}">
  <div style="background:{fill};color:{on_fill};padding:18px 28px;font-size:34px;font-weight:700">{labels.title(alert)}</div>
  <div style="padding:24px 28px">
    <div style="font-size:52px;font-weight:700;line-height:1.1">{html.escape(alert.headline)}</div>
    {action}
    <div style="font-size:22px;opacity:.65;margin-top:18px">{labels.until(alert.expires_at, now_ms)}&nbsp;&nbsp;&nbsp;{cells}</div>
  </div>
</div>"""


def _row_html(alert: OfficialAlert, now_ms: int) -> str:
    return f"""
<div style="display:flex;gap:18px;padding:16px 24px;border-top:1px solid #ddd">
  <div style="width:8px;border-radius:3px;background:{labels.SEVERITY_FILL[alert.severity]}"></div>
  <div>
    <div style="font-size:20px;font-weight:600;color:{labels.SEVERITY_TEXT[alert.severity]}">{labels.title(alert)}</div>
    <div style="font-size:28px;font-weight:600">{html.escape(alert.headline)}</div>
    <div style="font-size:18px;opacity:.65">{labels.until(alert.expires_at, now_ms)}</div>
  </div>
</div>"""


def _sos_html(reports: list[CommunityReport], now_ms: int) -> str:
    if not reports:
        return ""
    items = []
    for report in reports:
        minutes = max(0, (now_ms - report.created_at) // 60_000)
        where = places.label(report.geohash) or report.geohash
        note = f' — {html.escape(report.note)}' if report.note else ""
        items.append(f'<div style="font-size:26px;padding:8px 0"><b>{html.escape(report.author_nickname)}</b>, '
                     f'{html.escape(where)} ({report.geohash}), {minutes} min ago{note}</div>')
    return (f'<div style="margin-top:28px;padding:16px 24px;border:2px dashed #888;border-radius:10px">'
            f'<div style="font-size:24px;font-weight:700">{SOS_TITLE}</div>'
            f'<div style="font-size:18px;opacity:.65">From people nearby, not official warnings. '
            f'Nobody has checked them.</div>{"".join(items)}</div>')


def board_html(b: Board, now_ms: int) -> str:
    """The whole board as one block of HTML: header with the clock, the warnings,
    calls for help, and the footer."""
    header = (f'<div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 16px 20px">'
              f'<div style="font-size:30px;font-weight:600">{TITLE}</div>'
              f'<div style="font-size:44px;font-weight:700;font-variant-numeric:tabular-nums">'
              f'{labels.clock(now_ms)}</div></div>')
    if b.hero is None:
        body = (f'<div style="text-align:center;padding:60px 16px">'
                f'<div style="font-size:52px;font-weight:700">{EMPTY_TITLE}</div>'
                f'<div style="font-size:26px;opacity:.65;max-width:760px;margin:12px auto">{EMPTY_BODY}</div></div>')
    else:
        body = _hero_html(b.hero, now_ms) + "".join(_row_html(a, now_ms) for a in b.rows)
    footer = peers_text(b.peers)
    if b.hidden:
        footer += f" &nbsp;·&nbsp; <b>{more_text(b.hidden)}</b>"
    page = (f'<div style="background:#fff;color:#111;padding:12px;border-radius:12px">{header}{body}'
            f'{_sos_html(b.sos, now_ms)}'
            f'<div style="font-size:20px;opacity:.65;padding:20px 16px 4px">{footer}</div></div>')
    return one_line(page)


def one_line(block: str) -> str:
    """HTML for a Markdown page, on one line. In Markdown a blank line ends an HTML
    block, and a line indented 4 spaces after it shows as code: a warning with no
    "what to do" would leave exactly that and print the rest of its card as text."""
    return "".join(line.strip() for line in block.splitlines())
