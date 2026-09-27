"""The evacuation-centre board.

Ported from ../alert-mesh/AlertMeshTests/AlertMesh/Views/HubBoardViewTests.swift. The
Swift rendering tests (mount the view in both themes) become checks on the HTML.
"""
from alertmesh import hub
from alertmesh.alert_store import AlertStore, IngestResult
from alertmesh.reports import ReportAuthor, ReportSeverity
from alertmesh.signer import OfficialAlertSigner, WarningDraft
from alertmesh.wire import HazardType, OfficialAlert, Severity

NOW_MS = 1_700_000_000_000


def make_store(severities) -> AlertStore:
    store = AlertStore(clock=lambda: NOW_MS)
    signer = OfficialAlertSigner()
    for index, severity in enumerate(severities):
        draft = WarningDraft(HazardType.BUSHFIRE, severity, "Bushfire at Mount Barker - leave now",
                             "Travel north on Highway 1. Do not wait.", 6, ["r7hg", "r7hu"])
        alert = signer.sign(draft, bytes([index]) * 16, NOW_MS - index * 60_000)
        assert store.ingest(alert) is IngestResult.ACCEPTED
    return store


def test_footer_says_none_rather_than_zero():
    assert hub.peers_text(0) == "No devices nearby yet"
    assert hub.peers_text(-1) == "No devices nearby yet"
    assert hub.peers_text(3) == "3 devices nearby"


def test_warnings_past_the_third_row_are_counted_not_dropped():
    """The hero plus MAX_ROWS fit; everything beyond is only in the footer's count, so
    the count has to be right or a warning goes missing with nothing to say it did."""
    assert hub.hidden_count(0) == 0
    assert hub.hidden_count(1) == 0
    assert hub.hidden_count(1 + hub.MAX_ROWS) == 0
    assert hub.hidden_count(2 + hub.MAX_ROWS) == 1
    assert hub.hidden_count(10) == 10 - 1 - hub.MAX_ROWS
    store = make_store([Severity.ADVICE] * 7)
    b = hub.board(store.live_alerts(), peers=2)
    assert 1 + len(b.rows) + b.hidden == 7
    assert "3 more warnings not shown" in hub.board_html(b, NOW_MS)


def test_the_clock_shows_a_time_and_no_date():
    html = hub.board_html(hub.board([], 0), NOW_MS)
    clock = hub.labels.clock(NOW_MS)
    assert len(clock) == 5 and clock[2] == ":"
    assert clock in html


def test_the_worst_warning_is_the_one_in_large_type():
    store = make_store([Severity.ADVICE, Severity.EMERGENCY_WARNING, Severity.WATCH_AND_ACT])
    ordered = store.live_alerts()
    assert [a.severity for a in ordered] == [Severity.EMERGENCY_WARNING, Severity.WATCH_AND_ACT, Severity.ADVICE]
    b = hub.board(ordered, peers=4)
    assert b.hero.severity is Severity.EMERGENCY_WARNING
    assert [a.severity for a in b.rows] == [Severity.WATCH_AND_ACT, Severity.ADVICE]


def test_the_board_draws_empty_and_populated():
    empty = hub.board_html(hub.board([], 0), NOW_MS)
    assert hub.EMPTY_TITLE in empty and "No devices nearby yet" in empty
    full = hub.board_html(hub.board(make_store(list(Severity)).live_alerts(), 4), NOW_MS)
    assert "Emergency Warning · Bushfire" in full and "4 devices nearby" in full
    assert "#r7hg" in full and "What to do" in full


def test_a_row_draws_without_an_action_or_a_known_hazard():
    live = make_store([Severity.WATCH_AND_ACT]).live_alerts()[0]
    odd = OfficialAlert(live.alert_id, 0x7E, live.severity, live.area_cells, "Strange <b>thing</b>", "",
                        live.issued_at, live.expires_at, live.signature)
    html = hub.board_html(hub.board([live, odd], 0), NOW_MS)
    assert "Watch and Act · Official warning" in html
    assert "Strange &lt;b&gt;thing&lt;/b&gt;" in html  # text is escaped, never HTML
    hero_only = hub.board_html(hub.board([odd], 0), NOW_MS)
    assert "What to do" not in hero_only


# --- Calls for help (added for the prototype) ---


def test_only_calls_for_help_are_listed_under_the_warnings():
    sam, jo = ReportAuthor("Sam"), ReportAuthor("Jo")
    sos = sam.sos("qvqj9w2", "Car stuck at the causeway", NOW_MS - 5 * 60_000)
    hazard = jo.hazard(HazardType.FLOOD, ReportSeverity.HIGH, "qvqj9w3", "Causeway under water", NOW_MS)
    b = hub.board([], 0, [sos, hazard])
    assert b.sos == [sos]
    html = hub.board_html(b, NOW_MS)
    assert hub.SOS_TITLE in html and "Sam" in html and "5 min ago" in html and "Car stuck" in html
    assert "Causeway under water" not in html
    assert hub.SOS_TITLE not in hub.board_html(hub.board([], 0, [hazard]), NOW_MS)


def test_the_board_is_one_line_so_markdown_never_turns_it_into_code():
    """A blank line then an indented line would end the HTML block and print the rest
    as code. A warning with no "what to do" used to leave exactly that."""
    live = make_store([Severity.WATCH_AND_ACT]).live_alerts()[0]
    bare = OfficialAlert(live.alert_id, live.hazard_code, live.severity, live.area_cells, live.headline, "",
                         live.issued_at, live.expires_at, live.signature)
    for b in (hub.board([bare], 0), hub.board([], 0), hub.board(make_store(list(Severity)).live_alerts(), 2)):
        assert "\n" not in hub.board_html(b, NOW_MS)


def test_the_board_stays_black_with_the_apps_dark_colours():
    """Shown on a projector in a hall: black whatever the system's light or dark setting,
    with the iPhone app's colours made for a dark background (docs/desktop-design.md)."""
    html = hub.board_html(hub.board(make_store(list(Severity)).live_alerts(), 2), NOW_MS)
    assert html.startswith('<div class="am-board" style="background:#000000;color:#FFFFFF')
    assert "background:#FF9426" in html  # Watch and Act's dark-mode fill, on a row's bar
    assert "color:#FFD84D" in html       # Advice's dark-mode text colour
    assert "background:#BF1A1A;color:#FFFFFF" in html  # the Emergency Warning hero: white on red
