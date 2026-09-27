"""Alert Mesh — the phone app, on a laptop.

Run from this folder, from VS Code's terminal (see README, "Bluetooth and network
permission"):

    streamlit run phone_app.py

or use Run and Debug -> "Phone app" in VS Code.

Like the iPhone app, three tabs:
- Now: calls for help from people nearby, then official warnings, and a "Call for help"
  button (EmergencyRootView, NowView, SOSView);
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
                  help="Settings: your nickname and town")


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


def call_for_help() -> None:
    """Your own call for help, when one is out, and the call-for-help sheet when the
    "I need help" bar was pressed."""
    mine = p.my_call_for_help()
    if mine is not None:
        st.error(f"**Your call for help is out.** It keeps travelling between laptops until "
                 f"{labels.clock(mine.expires_at)}. It says you are {place_words(mine.geohash)}.")
        with st.container(horizontal=True):
            st.button("I'm safe now", type="primary", on_click=p.send_safe)
            st.button("Send it again", on_click=p.send_sos, args=(mine.note,))
        return
    if not state.get("sos_open") or p.geohash is None:
        return
    with st.container(border=True):
        st.markdown(f"**Call for help**, {place_words(p.geohash)}")
        st.caption("This is not 000. If you have any phone signal at all, call emergency services first.")
        st.text_input("Note", placeholder="who is with you, what is wrong (optional)",
                      max_chars=reports.NOTE_MAX_BYTES, key="sos_note")
        with st.container(horizontal=True):
            st.button("Send call for help", type="primary", on_click=send_sos)
            st.button("Cancel", on_click=lambda: state.update(sos_open=False))


def help_bar() -> None:
    """The red "I need help" bar, pinned to the bottom of Now (EmergencyHelpBarModifier)."""
    with st.container(key="am_helpbar"):
        st.button("I need help", key="need_help", icon=":material/sos:", type="primary", width="stretch",
                  disabled=p.geohash is None, on_click=lambda: state.update(sos_open=True),
                  help="Pick your town in Settings first, so people know where to come." if p.geohash is None
                  else "Opens the call for help. Nothing is sent until you press Send.")


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
            call_for_help()
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
    help_bar()


# --- Report (CommunityReportsView) ------------------------------------------------


def send_hazard() -> None:
    if p.send_hazard(state.r_hazard, state.r_how_bad, state.get("r_note", "")):
        state.r_note = ""


def report_view() -> None:
    with st.container(border=True):
        st.markdown("**Report a hazard**")
        if p.geohash is None:
            st.caption("A report needs a place. Pick your town first.")
        else:
            st.selectbox("Type", list(HazardType), format_func=labels.hazard_name, key="r_hazard")
            st.radio("How bad", list(ReportSeverity), format_func=labels.REPORT_SEVERITY_NAMES.get,
                     horizontal=True, key="r_how_bad")
            st.text_input("What's happening here?", max_chars=reports.NOTE_MAX_BYTES, key="r_note")
            st.button("Send report", on_click=send_hazard)
    st.subheader("Community reports")
    st.caption("What people nearby are reporting. These are not official warnings and nobody has checked them.")
    items = p.reports()
    if not items:
        st.caption("No reports nearby.")
    for report in items:
        kind = labels.REPORT_KIND_NAMES[report.kind]
        if report.kind is ReportKind.HAZARD:
            kind += f" · {labels.hazard_name(report.hazard)} · {labels.REPORT_SEVERITY_NAMES.get(report.severity, '')}"
        who = "You" if p.is_own(report) else (report.author_nickname or "Someone")
        icon = {ReportKind.SOS: ":material/sos:", ReportKind.SAFE: ":material/check_circle:",
                ReportKind.HAZARD: ":material/warning:"}[report.kind]
        with st.container(border=True):
            st.markdown(f"{icon} **{kind}** — {html.escape(who)}, {place_words(report.geohash)}, "
                        f"{labels.clock(report.created_at)}")
            if report.note:
                st.caption(report.note)


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
        st.markdown("**Chats**")
        for key in keys:
            unread = conversations[key].unread if key in conversations and key != state.chat_with else 0
            st.button(conversation_name(key) + (f" · {unread} new" if unread else ""), key=f"chat_{key}",
                      type="primary" if key == state.chat_with else "secondary", width="stretch",
                      on_click=open_conversation, args=(key,))
        people = [peer for peer in p.node.nearby_peers()]
        st.markdown("**People in range**")
        if not people:
            st.caption("Nobody yet. Other laptops running the phone app appear here when they are within "
                       "Bluetooth range, or in range of a laptop that is.")
        for peer in people:
            st.button(f"Message {peer.announce.nickname or 'Someone'}", key=f"msg_{peer.key}",
                      on_click=open_conversation, args=(peer.key,))

    with right:
        key = state.chat_with
        p.node.mark_read(key)
        if key == NEARBY:
            st.caption("Everyone in Bluetooth range reads Nearby, including through other laptops. "
                       "Messages are signed, so nobody can change them on the way.")
        else:
            st.caption(f"Only {html.escape(conversation_name(key))} can read this conversation. "
                       "Laptops in between pass it on without being able to open it.")
        entries = conversations[key].entries if key in conversations else []
        with st.container(height=380):
            if not entries:
                st.caption("No messages yet.")
            for entry in entries:
                name = "You" if entry.outgoing else (entry.message.sender_nickname or "Someone")
                with st.chat_message("user" if entry.outgoing else "assistant",
                                     avatar=":material/person:" if entry.outgoing else ":material/podcasts:"):
                    st.markdown(f"**{html.escape(name)}** · {labels.clock(entry.message.sent_at)}")
                    st.text(entry.message.text)
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
view = style.nav([(NOW, ":material/home:"), (REPORT, ":material/campaign:"), (CHAT, ":material/chat:")],
                 {NOW: urgent if state.get("view") != NOW else 0,
                  CHAT: p.node.chats.unread if state.get("view") != CHAT else 0}, "Alert Mesh")
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
