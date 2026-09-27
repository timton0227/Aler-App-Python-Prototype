"""Alert Mesh — the phone app, on a laptop.

Run from this folder, from VS Code's terminal (see README, "Bluetooth and network
permission"):

    streamlit run phone_app.py

or use Run and Debug -> "Phone app" in VS Code.

Like the iPhone app, three tabs, here in a sidebar, in the iPhone app's look
(alertmesh/style.py):
- Now: the warning that covers you, other warnings, calls for help from people nearby,
  and the red "I need help" bar (EmergencyRootView, NowView, SOSView);
- Report: tell people nearby about a hazard, and see what they report
  (CommunityReportsView);
- Chat: Nearby, where everyone in range reads along, and private conversations
  (ChatInboxView).

Messages travel laptop to laptop over real Bluetooth, hopping through laptops in
between. Official warnings arrive from the warning app over the local network, and
are passed on over Bluetooth to laptops that have no network.

This is free and unencumbered software released into the public domain.
"""
import html

import streamlit as st

from alertmesh import hub, labels, notifications, phone, places, reports, style
from alertmesh.chat import TEXT_MAX_BYTES
from alertmesh.node import NEARBY
from alertmesh.proximity import Urgency, sos_urgency
from alertmesh.reports import ReportKind, ReportSeverity
from alertmesh.wire import HazardType

st.set_page_config(page_title="Alert Mesh", page_icon="📡", layout="wide")

state = st.session_state
p = phone.shared()

NOW, REPORT, CHAT = "Now", "Report", "Chat"


@st.cache_data
def town_names() -> list[str]:
    return sorted({t.name for t in places.towns()})


# --- Keeping the page up to date ------------------------------------------------


def news() -> tuple:
    """What changes the page: anything new in the mesh, the links' state, and the minute
    (warnings and calls for help end on their own)."""
    return (p.node.version, p.bluetooth_status, p.wifi_status, p.node.link.neighbours(), p.clock() // 60_000)


@st.fragment(run_every=1)
def watch() -> None:
    """Checks once a second, and redraws the page only when something changed, so a
    half-typed message is not disturbed for nothing."""
    if state.get("news") != news():
        state.news = news()
        st.rerun()


def tell_about_new_things() -> None:
    """A pop-up for each new warning, call for help and message, like a notification."""
    seen = state.setdefault("told", set())
    first = not seen
    for item in p.warnings():
        key = ("warning", item.alert.alert_id, item.alert.issued_at)
        if key not in seen:
            seen.add(key)
            if not first:
                where = notifications.whereabouts(item.decision.reason.kind)
                content = notifications.alert_content(item.alert, item.decision.urgency, where)
                st.toast(f"**{content.title}**  \n{content.body}", icon="⚠️")
    for report in p.calls_for_help():
        key = ("sos", report.author_signing_key, report.report_id, report.created_at)
        if key not in seen:
            seen.add(key)
            if not first:
                content = notifications.sos_content(report, sos_urgency(report.geohash, p.geohash))
                st.toast(f"**{content.title}**  \n{content.body}", icon="🆘")
    seen.add(("first",))


# --- Sidebar, settings and status bar ------------------------------------------------


def bluetooth_words() -> tuple[bool, str]:
    bluetooth, _, reason = p.bluetooth_status.partition(":")
    if bluetooth != "on":
        return False, "Bluetooth off" + (f": {reason.strip()}" if reason.strip() else "")
    count = p.node.link.neighbours()
    return True, f"Bluetooth on · {count} {'laptop' if count == 1 else 'laptops'} nearby"


def network_words() -> tuple[bool, str]:
    network, _, reason = p.wifi_status.partition(":")
    if network != "on":
        return False, "Local network off" + (f": {reason.strip()}" if reason.strip() else "")
    return True, "Local network on"


def save_nickname() -> None:
    p.set_nickname(state.nickname)


def save_town() -> None:
    p.set_town(state.town)


def open_settings() -> None:
    state.settings_open = True


def close_settings() -> None:
    state.settings_open = False


@st.dialog("Settings", on_dismiss=close_settings)
def settings() -> None:
    # Starting values as parameters: a value put in Session State before the sheet opens
    # does not reach a field inside it in the browser.
    names = town_names()
    st.text_input("Nickname (people nearby see it; anyone can pick any name)", p.nickname, key="nickname",
                  max_chars=reports.NICKNAME_MAX_BYTES, on_change=save_nickname)
    st.selectbox("Where you are", names, key="town", on_change=save_town, placeholder="Pick your town",
                 index=names.index(p.profile.town) if p.profile.town in names else None)
    st.caption("A laptop has no GPS, so your town stands in for your position. "
               "It decides which warnings are for you, and a call for help says you are there.")
    st.caption(places.CREDIT)
    st.button("Done", type="primary", on_click=close_settings)


def sidebar_foot() -> None:
    """You and your town at the foot of the sidebar; clicking them opens Settings."""
    with st.sidebar.container(key="am_foot"):
        st.button(f"{p.nickname} · {p.profile.town or 'Pick your town'}", key="open_settings",
                  icon=":material/settings:", width="stretch", on_click=open_settings,
                  help=f"Settings: your nickname and town ({style.shortcut_label(',')})")


def status_bar() -> None:
    style.status_bar([bluetooth_words(), network_words()], style.updated_text())


# --- Now (NowView, SOSView) -------------------------------------------------------


def place_words(cell: str) -> str:
    """ "near Katherine" or "about 60 km south of Katherine", to go inside a sentence."""
    words = places.label(cell)
    return words[0].lower() + words[1:] if words else f"at {cell}"


def send_sos() -> None:
    if p.send_sos(state.get("sos_note", "")):
        state.sos_open = False
        state.sos_note = ""


def open_sos() -> None:
    state.sos_open = True


def close_sos() -> None:
    state.sos_open = False


def sheet_buttons(*buttons) -> None:
    """A sheet's buttons in the system's order (Cancel, then the main button, on a Mac;
    the main button first on Windows), right-aligned on a Mac."""
    with st.container(horizontal=True, horizontal_alignment="left" if style.WINDOWS else "right"):
        for draw in buttons:
            draw()


@st.dialog("Call for help", on_dismiss=close_sos)
def sos_sheet() -> None:
    """The iPhone's SOSView: send a call for help, or, when one is out, send it again or
    say you are safe."""
    mine = p.my_call_for_help()
    if mine is not None:
        st.markdown(hub.one_line(f"""
<div class="am-status-title am-t-e">Your call for help is out</div>
<div class="am-muted">It keeps travelling between laptops until {labels.clock(mine.expires_at)}. """
                                 """Send it again whenever new people come near.</div>"""), unsafe_allow_html=True)
        st.button("Send it again", key="sos_again", on_click=p.send_sos, args=(mine.note,), width="stretch")
        st.caption("Sends it again. Everyone sees the same call for help, not a second one.")
        st.button("I'm safe now", key="sos_safe", type="primary", on_click=lambda: (p.send_safe(), close_sos()),
                  width="stretch")
        st.caption("Tells every laptop that got your call for help that you are okay, and stops it spreading.")
        return
    st.markdown(hub.one_line(f"""
<p class="am-muted" style="font-size:14.5px">This tells every laptop near you that you need help, and they """
                             f"""pass it on until it reaches someone with a signal.</p>
<p class="am-warnline">This is not 000. If you have any phone signal at all, call emergency services first.</p>
<p class="am-muted" style="font-size:14px">It says you are {style.esc(place_words(p.geohash))}, the town """
                             """picked in Settings: a laptop has no GPS.</p>"""), unsafe_allow_html=True)
    st.text_input("Note", placeholder="who is with you, what is wrong (optional)", max_chars=reports.NOTE_MAX_BYTES,
                  key="sos_note")
    sheet_buttons(*style.button_order(
        lambda: st.button("Send call for help", key="sos_send", type="primary", on_click=send_sos),
        lambda: st.button("Cancel", key="sos_cancel", on_click=close_sos)))


def my_call_for_help() -> None:
    """Your own call for help, while it is out, at the top of Now."""
    mine = p.my_call_for_help()
    if mine is None:
        return
    st.markdown(hub.one_line(f"""
<div class="am-card am-help"><div class="am-who">{style.HELP_ICON}Your call for help is out</div>
<div class="am-muted">It keeps travelling between laptops until {labels.clock(mine.expires_at)}. """
                             f"""It says you are {style.esc(place_words(mine.geohash))}.</div></div>"""),
                unsafe_allow_html=True)
    with st.container(horizontal=True):
        st.button("I'm safe now", key="mine_safe", type="primary", on_click=p.send_safe)
        st.button("Send it again", key="mine_again", on_click=p.send_sos, args=(mine.note,))


def help_bar() -> None:
    """The red "I need help" bar, pinned to the bottom of Now (EmergencyHelpBarModifier).
    It opens the sheet; nothing is sent until "Send call for help"."""
    with st.container(key="am_helpbar"):
        st.button("I need help", key="need_help", icon=":material/sos:", type="primary", width="stretch",
                  disabled=p.geohash is None, on_click=open_sos,
                  help="Pick your town in Settings first, so people know where to come." if p.geohash is None
                  else f"Opens the call for help ({style.shortcut_label('h', shift=True)}). Nothing is sent until "
                  "you press Send.")


def open_warning(alert_id: bytes) -> None:
    state.open_warning = alert_id


def close_warning() -> None:
    state.open_warning = None


@st.dialog("Warning", width="medium", on_dismiss=close_warning)
def warning_detail(item: phone.WarningView) -> None:
    """The full warning (the iPhone's alert detail): level, headline, what to do, where,
    until when, and why the app was loud or quiet about it."""
    alert = item.alert
    level = style.LEVEL[alert.severity]
    loud = "Told loudly. " if item.decision.urgency is Urgency.LOUD else "Told quietly. "
    st.markdown(hub.one_line(f"""
<div class="am-level am-t-{level}" style="font-size:15px">{style.symbol(alert.severity)}{labels.title(alert)}</div>
<div class="am-headline" style="font-size:20px;margin:6px 0 10px">{style.esc(alert.headline)}</div>
<div class="am-section">What to do</div>
<div class="am-action" style="margin-bottom:12px">{style.esc(alert.action_text) or "Follow advice from emergency services."}</div>
<div class="am-muted">{labels.proximity(item.decision)} · {labels.until(alert.expires_at, p.clock())}</div>
<div class="am-muted">{loud}{labels.REASON_TEXT[item.decision.reason.kind]}.</div>
<div class="am-muted">Issued {labels.clock(alert.issued_at)} · area {", ".join(alert.area_cells)}</div>"""),
                unsafe_allow_html=True)
    st.button("Close", type="primary", on_click=close_warning)


def status_block(now: phone.NowStatus) -> None:
    """The top of Now. A solid block in the level's colour only when a warning covers
    you (NowView.affectedBlock); otherwise a grey card."""
    if now.kind is phone.NowKind.CLEAR:
        st.markdown(hub.one_line("""
<div class="am-card"><div class="am-status-title am-clear">No current warnings</div>
<div class="am-muted">Keep Bluetooth on. A warning reaches this laptop over the local network, or from any """
                                 """laptop in range that has it.</div></div>"""), unsafe_allow_html=True)
        return
    if now.kind is phone.NowKind.ELSEWHERE:
        count = len(now.others)
        listed = "1 warning for another area is" if count == 1 else f"{count} warnings for other areas are"
        st.markdown(hub.one_line(f"""
<div class="am-card"><div class="am-status-title">No warnings where you are</div>
<div class="am-muted">{listed} listed below.</div></div>"""), unsafe_allow_html=True)
        return
    alert = now.affected.alert
    level = style.LEVEL[alert.severity]
    st.markdown(hub.one_line(f"""
<div class="am-block am-fill-{level}">{style.symbol_on_fill(alert.severity)}
<span class="am-lvl">{labels.SEVERITY_NAMES[alert.severity]}</span>
<span class="am-stand">{labels.proximity(now.affected.decision)}</span>
<span class="am-headline">{style.esc(alert.headline)}</span>
<span class="am-meta"><span>{labels.hazard_name(alert.hazard)}</span><span>{labels.until(alert.expires_at, p.clock())}</span></span>
</div>"""), unsafe_allow_html=True)
    st.button("Open full warning ›", key="open_affected", type="tertiary", on_click=open_warning,
              args=(alert.alert_id,))
    if alert.action_text:
        st.markdown(hub.one_line(f"""
<div class="am-card am-border-{level}"><div class="am-section">What to do</div>
<div class="am-action">{style.esc(alert.action_text)}</div></div>"""), unsafe_allow_html=True)


def other_warning(item: phone.WarningView) -> None:
    """A warning that does not cover you: a grey card with a colour bar."""
    alert = item.alert
    level = style.LEVEL[alert.severity]
    where = places.label(alert.area_cells[0]) if alert.area_cells else ""
    st.markdown(hub.one_line(f"""
<div class="am-card am-other"><span class="am-colourbar am-bar-{level}"></span><div>
<div class="am-level am-t-{level}">{style.symbol(alert.severity, "var(--am-card)")}{labels.title(alert)}</div>
<div class="am-headline">{style.esc(alert.headline)}</div>
<div class="am-muted">{labels.proximity(item.decision)}{" · " + style.esc(where) if where else ""}<br>
{labels.until(alert.expires_at, p.clock())}</div></div></div>"""), unsafe_allow_html=True)
    st.button("Open full warning ›", key=f"open_{alert.alert_id.hex()}", type="tertiary", on_click=open_warning,
              args=(alert.alert_id,))


def message_person(key: str) -> None:
    state.chat_with = key
    state.view = CHAT


def calls_for_help_section(helps) -> None:
    """Calls for help from people nearby, red-bordered, with "Message" when that person
    is in range."""
    st.markdown('<div class="am-section">Calls for help</div>', unsafe_allow_html=True)
    in_range = {peer.key for peer in p.node.nearby_peers()}
    for report in helps:
        name = report.author_nickname or "Someone"
        note = f'<div class="am-note">{style.esc(report.note)}</div>' if report.note else ""
        st.markdown(hub.one_line(f"""
<div class="am-card am-help"><div class="am-who">{style.HELP_ICON}{style.esc(name)} needs help</div>{note}
<div class="am-muted">{style.esc(places.label(report.geohash) or report.geohash)} · {labels.clock(report.created_at)}</div>
</div>"""), unsafe_allow_html=True)
        key = report.author_signing_key.hex()
        if key in in_range:
            st.button(f"Message {name}", key=f"help_msg_{key}_{report.report_id.hex()}", on_click=message_person,
                      args=(key,))


def connection_section() -> None:
    """How you're connected, in plain counts (NowView.connectionSection)."""
    on, _ = bluetooth_words()
    count = p.node.link.neighbours() if on else 0
    if not on:
        bluetooth = "Bluetooth is off, so no laptop nearby can pass warnings to you"
    elif count == 0:
        bluetooth = "No laptops nearby yet"
    else:
        bluetooth = f"{count} {'laptop' if count == 1 else 'laptops'} nearby can pass warnings to you"
    network_on, _ = network_words()
    network = ("Official warnings arrive over the local network" if network_on
               else "Local network off: warnings arrive only from laptops nearby")
    st.markdown(hub.one_line(f"""
<div class="am-card"><div class="am-section">How you're connected</div>
<div class="am-row">{style.APP_ICON}{bluetooth}</div>
<div class="am-row">{style.APP_ICON}{network}</div>
<div class="am-muted">Warnings travel laptop to laptop over Bluetooth. They keep arriving with no internet.</div>
</div>"""), unsafe_allow_html=True)


def now_view() -> None:
    items = p.warnings()
    now = phone.now_status(items)
    helps = p.calls_for_help()
    with st.container(key="am_now"):
        main, side = st.columns([3, 2], gap="large")
        with main:
            my_call_for_help()
            status_block(now)
            if now.others:
                st.markdown('<div class="am-section">Other warnings</div>', unsafe_allow_html=True)
                for item in now.others:
                    other_warning(item)
        with side:
            if helps:
                calls_for_help_section(helps)
            connection_section()
    opened = next((w for w in items if w.alert.alert_id == state.get("open_warning")), None)
    if opened is not None:
        warning_detail(opened)
    elif state.get("sos_open") and p.geohash is not None:
        sos_sheet()
    help_bar()


# --- Report (CommunityReportsView) ------------------------------------------------


def send_hazard() -> None:
    if p.send_hazard(state.r_hazard, state.r_how_bad, state.get("r_note", "")):
        state.r_note = ""


# "How bad" as the iPhone's three buttons, with its symbols.
HOW_BAD_ICONS = {ReportSeverity.LOW: ":material/info:",
                 ReportSeverity.MODERATE: ":material/warning:",
                 ReportSeverity.HIGH: ":material/priority_high:"}

REPORT_ICONS = {
    ReportKind.HAZARD: ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4 3h16a2 2 0 0 1 2 2'
                        'v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/></svg>'),
    ReportKind.SAFE: ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10"/>'
                      '<path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="var(--am-card)" stroke-width="2.4"/></svg>'),
    ReportKind.SOS: style.HELP_ICON,
}


def report_card(report) -> None:
    """One report from people nearby. Calls for help are red; hazard reports and "I'm
    safe" are grey, so a neighbour's report never borrows a warning's colours."""
    own = p.is_own(report)
    who = "You" if own else (report.author_nickname or "Someone")
    if report.kind is ReportKind.SOS:
        title = "You need help" if own else f"{who} needs help"
    elif report.kind is ReportKind.SAFE:
        title = "You are safe" if own else f"{who} is safe"
    else:
        title = f"{labels.hazard_name(report.hazard)} · {labels.REPORT_SEVERITY_NAMES.get(report.severity, '')}"
    where = places.label(report.geohash) or report.geohash if report.geohash else ""
    meta = " · ".join(x for x in (who if report.kind is ReportKind.HAZARD else "", where,
                                  labels.clock(report.created_at)) if x)
    note = f'<div class="am-note">{style.esc(report.note)}</div>' if report.note else ""
    help_class = " am-help" if report.kind is ReportKind.SOS else ""
    st.markdown(f'<div class="am-card am-rep{help_class}"><span class="am-ic">{REPORT_ICONS[report.kind]}</span>'
                f'<div><div class="am-t">{style.esc(title)}</div><div class="am-muted">{style.esc(meta)}</div>'
                f'{note}</div></div>', unsafe_allow_html=True)


def report_view() -> None:
    form, listed = st.columns([5, 6], gap="large")
    with form:
        st.markdown('<div class="am-section">Report a hazard</div>', unsafe_allow_html=True)
        with st.container(border=True):
            if p.geohash is None:
                st.caption("A report needs a place. Pick your town in Settings first.")
            else:
                st.selectbox("Type", list(HazardType), format_func=labels.hazard_name, key="r_hazard")
                # Three buttons, the chosen one blue (a segmented control's look; the
                # control itself cannot be driven by Streamlit 1.51's test runner).
                state.setdefault("r_how_bad", ReportSeverity.MODERATE)
                st.markdown('<div class="am-fieldlabel">How bad</div>', unsafe_allow_html=True)
                with st.container(horizontal=True, gap="small", key="am_how_bad"):
                    for level in ReportSeverity:
                        st.button(labels.REPORT_SEVERITY_NAMES[level], key=f"how_bad_{level.name.lower()}",
                                  icon=HOW_BAD_ICONS[level], width="stretch",
                                  type="primary" if state.r_how_bad is level else "secondary",
                                  on_click=state.update, kwargs={"r_how_bad": level})
                st.text_area("What's happening here?", max_chars=reports.NOTE_MAX_BYTES, key="r_note", height=80)
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.button("Send report", type="primary", on_click=send_hazard)
                    st.caption(f"Sent from {place_words(p.geohash)}")
    with listed:
        st.markdown('<div class="am-section">From people nearby</div>', unsafe_allow_html=True)
        items = p.reports()
        if not items:
            st.caption("No reports nearby.")
        for report in items:
            report_card(report)
        st.caption("Not official warnings. Nobody has checked them.")


# --- Chat (ChatInboxView) ---------------------------------------------------------


def conversation_name(key: str) -> str:
    if key == NEARBY:
        return "Nearby"
    peer = p.node.peers.get(key)
    if peer:
        return peer.announce.nickname or "Someone"
    entries = p.node.chats.conversations.get(key)
    incoming = [e for e in entries.entries if not e.outgoing] if entries else []
    return incoming[-1].message.sender_nickname if incoming else "Someone"


def open_conversation(key: str) -> None:
    state.chat_with = key


def chat_view() -> None:
    state.setdefault("chat_with", NEARBY)
    conversations = p.node.chats.conversations
    keys = [NEARBY] + sorted((k for k in conversations if k != NEARBY),
                             key=lambda k: -max((e.received_at for e in conversations[k].entries), default=0))
    if state.chat_with not in keys:
        keys.append(state.chat_with)

    left, right = st.columns([1, 2], gap="medium")
    with left:
        st.markdown('<div class="am-listhead">Chats</div>', unsafe_allow_html=True)
        for key in keys:
            unread = conversations[key].unread if key in conversations and key != state.chat_with else 0
            st.button(conversation_name(key) + (f" :blue-badge[{unread}]" if unread else ""), key=f"chat_{key}",
                      icon=":material/cell_tower:" if key == NEARBY else ":material/person:",
                      type="primary" if key == state.chat_with else "tertiary", width="stretch",
                      on_click=open_conversation, args=(key,))
        people = [peer for peer in p.node.nearby_peers()]
        st.markdown('<div class="am-listhead">People nearby</div>', unsafe_allow_html=True)
        if not people:
            st.caption("Nobody yet. Other laptops running the phone app appear here when they are within "
                       "Bluetooth range, or in range of a laptop that is.")
        for peer in people:
            st.button(f"Message {peer.announce.nickname or 'Someone'}", key=f"msg_{peer.key}",
                      icon=":material/chat_bubble:", on_click=open_conversation, args=(peer.key,))

    with right:
        key = state.chat_with
        p.node.mark_read(key)
        if key == NEARBY:
            who_reads = ("Everyone in Bluetooth range reads this, including through other laptops. "
                         "Messages are signed, so nobody can change them on the way.")
        else:
            who_reads = (f"Only {conversation_name(key)} can read this. Laptops in between pass it on without "
                         "being able to open it.")
        st.markdown(f'<div class="am-convhead"><b>{style.esc(conversation_name(key))}</b>'
                    f'<span>{style.esc(who_reads)}</span></div>', unsafe_allow_html=True)
        entries = conversations[key].entries if key in conversations else []
        with st.container(height=400, border=False):
            if not entries:
                st.caption("No messages yet.")
            else:
                st.markdown(style.bubbles([
                    (e.outgoing, "you" if e.outgoing else e.message.sender_key.hex(),
                     "You" if e.outgoing else (e.message.sender_nickname or "Someone"),
                     e.message.text, e.message.sent_at) for e in entries]), unsafe_allow_html=True)
        reachable = key == NEARBY or any(peer.key == key for peer in p.node.nearby_peers())
        text = st.chat_input(f"Message {conversation_name(key)}" if reachable else "Not in range right now",
                             key="chat_text", max_chars=TEXT_MAX_BYTES, disabled=not reachable)
        if text and p.node.say(text, None if key == NEARBY else key) is None:
            st.warning("Not sent: a message is at most 280 bytes (about 280 letters, fewer with emoji).")
        elif text:
            st.rerun()


# --- Page -----------------------------------------------------------------------

style.inject()
state.news = news()  # what this run shows; the fragment reruns the page when it changes
watch()
tell_about_new_things()

# The page must know which tab is open, so that opening Chat marks its messages read.
urgent = len(p.calls_for_help()) + sum(1 for w in p.warnings() if w.decision.urgency is Urgency.LOUD)
PAGES = [(NOW, ":material/home:"), (REPORT, ":material/campaign:"), (CHAT, ":material/chat:")]
view = style.nav(PAGES, {NOW: urgent if state.get("view") != NOW else 0,
                         CHAT: p.node.chats.unread if state.get("view") != CHAT else 0}, "Alert Mesh")
# ⌘1-3, ⌘, for Settings and ⌘⇧H for "I need help" (Ctrl on Windows). "I need help" only
# opens the sheet: as on the iPhone, nothing is sent until "Send call for help".
style.shortcuts({**style.nav_shortcuts(PAGES), ",": {"key": "open_settings"},
                 "shift+h": {"key": "need_help", "via": style.nav_key(NOW)}})
sidebar_foot()
status_bar()
if state.get("settings_open"):
    settings()

style.page_title(view)
if p.geohash is None:
    st.info("Pick your town in Settings, so the app knows which warnings are for you.")
    st.button("Open Settings", on_click=open_settings)
if view == REPORT:
    report_view()
elif view == CHAT:
    chat_view()
else:
    now_view()
