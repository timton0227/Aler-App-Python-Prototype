"""Alert Mesh — the phone app, on a laptop.

Run from this folder, from VS Code's terminal (see README, "Bluetooth permission"):

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

from alertmesh import hub, labels, notifications, phone, places, reports
from alertmesh.chat import TEXT_MAX_BYTES
from alertmesh.node import NEARBY
from alertmesh.proximity import Urgency, sos_urgency
from alertmesh.reports import ReportKind, ReportSeverity
from alertmesh.wire import HazardType

st.set_page_config(page_title="Alert Mesh", page_icon="📡", layout="centered")

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


# --- Header and settings --------------------------------------------------------


def status_line() -> str:
    bluetooth = p.bluetooth_status.split(":")[0]  # the reason, if any, is shown below
    count = p.node.link.neighbours()
    if bluetooth == "on":
        laptops = "laptop" if count == 1 else "laptops"
        bluetooth = f"on, {count} {laptops} in range"
    return f"Bluetooth: {bluetooth} · Local network: {p.wifi_status}"


def save_nickname() -> None:
    p.set_nickname(state.nickname)


def save_town() -> None:
    p.set_town(state.town)


def sidebar() -> None:
    st.sidebar.title("You")
    state.setdefault("nickname", p.nickname)
    st.sidebar.text_input("Nickname (people nearby see it; anyone can pick any name)", key="nickname",
                          max_chars=reports.NICKNAME_MAX_BYTES, on_change=save_nickname)
    names = town_names()
    state.setdefault("town", p.profile.town if p.profile.town in names else None)
    st.sidebar.selectbox("Where you are", names, key="town", on_change=save_town, index=None,
                         placeholder="Pick your town")
    st.sidebar.caption("A laptop has no GPS, so your town stands in for your position. "
                       "It decides which warnings are for you, and a call for help says you are there.")
    st.sidebar.divider()
    st.sidebar.caption(status_line())
    if p.bluetooth_status.startswith("off"):
        reason = p.bluetooth_status.partition(":")[2].strip()
        st.sidebar.warning("Without Bluetooth, messages cannot reach other laptops. " + reason)
    st.sidebar.caption(places.CREDIT)


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
    mine = p.my_call_for_help()
    if mine is not None:
        st.error(f"**Your call for help is out.** It keeps travelling between laptops until "
                 f"{labels.clock(mine.expires_at)}. It says you are {place_words(mine.geohash)}.")
        with st.container(horizontal=True):
            st.button("I'm safe now", type="primary", on_click=p.send_safe)
            st.button("Send it again", on_click=p.send_sos, args=(mine.note,))
        return
    if p.geohash is None:
        st.button("Call for help", type="primary", disabled=True, width="stretch",
                  help="Pick your town first, so people know where to come.")
        return
    if not state.get("sos_open"):
        st.button("Call for help", type="primary", width="stretch",
                  on_click=lambda: state.update(sos_open=True))
        return
    with st.container(border=True):
        st.markdown(f"**Call for help**, {place_words(p.geohash)}")
        st.caption("This is not 000. If you have any phone signal at all, call emergency services first.")
        st.text_input("Note", placeholder="who is with you, what is wrong (optional)",
                      max_chars=reports.NOTE_MAX_BYTES, key="sos_note")
        with st.container(horizontal=True):
            st.button("Send call for help", type="primary", on_click=send_sos)
            st.button("Cancel", on_click=lambda: state.update(sos_open=False))


def warning_card(item: phone.WarningView) -> None:
    """One warning as the phone lists it: level colour, headline, how close, what to do."""
    alert = item.alert
    fill, on_fill = labels.SEVERITY_FILL[alert.severity], labels.SEVERITY_ON_FILL[alert.severity]
    loud = "Loud: " if item.decision.urgency is Urgency.LOUD else ""
    st.markdown(hub.one_line(f"""
<div style="border:1px solid {fill};border-radius:10px;overflow:hidden;margin-bottom:10px">
  <div style="background:{fill};color:{on_fill};padding:8px 10px;font-weight:700">{labels.title(alert)}</div>
  <div style="padding:8px 10px">
    <div style="font-size:1.15em;font-weight:700">{html.escape(alert.headline)}</div>
    <div style="opacity:.75">{labels.proximity(item.decision)} · {labels.until(alert.expires_at, p.clock())}</div>
    <div style="margin-top:6px"><b>What to do</b><br>{html.escape(alert.action_text)}</div>
    <div style="margin-top:6px;font-size:.85em;opacity:.7">{loud}{labels.REASON_TEXT[item.decision.reason.kind]}</div>
  </div>
</div>"""), unsafe_allow_html=True)


def now_view() -> None:
    call_for_help()
    helps = p.calls_for_help()
    if helps:
        st.subheader("People asking for help")
        for report in helps:
            with st.container(border=True):
                st.markdown(f":material/sos: **{html.escape(report.author_nickname or 'Someone')} needs help** — "
                            f"{place_words(report.geohash)}, {labels.clock(report.created_at)}")
                if report.note:
                    st.caption(report.note)
    st.subheader("Warnings")
    items = p.warnings()
    if not items:
        st.markdown("**No current warnings**")
        st.caption("Keep Bluetooth on. A warning reaches this laptop over the local network, or from any "
                   "laptop in range that has it.")
    for item in items:
        warning_card(item)


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

sidebar()
state.news = news()  # what this run shows; the fragment reruns the page when it changes
watch()
tell_about_new_things()

st.title("Alert Mesh")
if p.geohash is None:
    st.info("Pick your town in the sidebar, so the app knows which warnings are for you.")


# A radio, not st.tabs: the page must know which tab is open, so that opening Chat marks
# its messages read. Its labels stay fixed (a label that changes can reset the choice);
# the counts go on the line below it.
view = st.radio("Show", [NOW, REPORT, CHAT], key="view", horizontal=True, label_visibility="collapsed")
counts = []
urgent = len(p.calls_for_help()) + sum(1 for w in p.warnings() if w.decision.urgency is Urgency.LOUD)
if urgent and view != NOW:
    counts.append(f"Now: {urgent} for you")
if p.node.chats.unread and view != CHAT:
    counts.append(f"Chat: {p.node.chats.unread} new")
if counts:
    st.caption(" · ".join(counts))
if view == REPORT:
    report_view()
elif view == CHAT:
    chat_view()
else:
    now_view()
