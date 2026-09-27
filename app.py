"""Alert Mesh — live demo page.

Run from this folder:

    streamlit run app.py

or use Run and Debug -> "Streamlit demo" in VS Code.

One simulated town lives in the page: about 300 phones, a few with internet, and an
evacuation centre (a Mac) in the middle. The warning console sends into that town.
Time only moves when you press a "+ minutes" button in the sidebar.

This is free and unencumbered software released into the public domain.
"""
import html

import streamlit as st

from alertmesh import labels, metrics, notifications, places, reports, viz, world
from alertmesh.console import AREA_SIZE_NAMES, PROBLEM_TEXT, AreaSize, IssueError, outcome_text, toggle_area
from alertmesh.proximity import Urgency
from alertmesh.reports import ReportKind, ReportSeverity
from alertmesh.signer import DURATION_RANGE, WarningDraft
from alertmesh.wire import ACTION_TEXT_MAX_BYTES, HEADLINE_MAX_BYTES, HazardType, Severity

st.set_page_config(page_title="Alert Mesh prototype", layout="wide")

state = st.session_state

# The mouse wheel scrolls the page, not the map; the maps zoom with their + and - buttons.
MAP_CONFIG = {"scrollZoom": False}


# --- The town -----------------------------------------------------------------


def new_town(scenario: metrics.Scenario) -> None:
    state.world = world.build(scenario)
    state.c_online = True
    state.c_editing = None
    state.c_confirm = False
    state.c_cancelling = None


if "world" not in state:
    new_town(world.DEFAULT_SCENARIO)
    state.c_cells = []

w: world.World = state.world


@st.cache_data
def town_names() -> list[str]:
    return list(dict.fromkeys(p.name for p in places.towns()))


def sidebar() -> None:
    s = w.scenario
    st.sidebar.title("Alert Mesh")
    st.sidebar.caption("A simulated town. Nothing here uses real Bluetooth or the real internet.")
    st.sidebar.metric("Simulated time", labels.clock(w.mesh.now_ms), f"minute {w.minutes:g}", delta_color="off")
    st.sidebar.write("Let time pass, in minutes:")
    cols = st.sidebar.columns(3)
    for col, minutes in zip(cols, (1, 5, 15)):
        col.button(f"+{minutes}", key=f"advance_{minutes}", on_click=w.advance, args=(minutes,),
                   width="stretch")

    with st.sidebar.form("town"):
        st.write("**Build a new town**")
        names = town_names()
        town = st.selectbox("Town", names, index=names.index(s.town))
        n = st.slider("Phones", 50, 600, s.n_phones, step=50)
        online = st.slider("Share with internet", 0.0, 1.0, s.share_online, step=0.05)
        moving = st.slider("Share walking about", 0.0, 1.0, s.share_moving, step=0.05)
        reach = st.slider("Bluetooth reach (m)", 20, 100, int(s.bluetooth_range_m), step=10)
        seed = st.number_input("Layout number (same number, same town)", 1, 999, s.seed)
        if st.form_submit_button("Build", width="stretch"):
            new_town(metrics.Scenario(town=town, n_phones=n, area_m=s.area_m, share_online=online,
                                      share_moving=moving, bluetooth_range_m=reach, speed_mps=s.speed_mps,
                                      seed=int(seed)))
            st.rerun()
    st.sidebar.caption(places.CREDIT)


# --- Warning console (IssueWarningView) -----------------------------------------

CONFIRM_BODY = ("It goes to nearby devices over Bluetooth and to phones in the area over the internet. "
                "Phones treat it as an official warning.")


def draft_from_form() -> WarningDraft:
    return WarningDraft(state.c_hazard, state.c_level, state.c_headline, state.c_action,
                        int(state.c_hours), list(state.c_cells))


def load_draft(draft: WarningDraft) -> None:
    state.c_hazard, state.c_level = draft.hazard, draft.severity
    state.c_headline, state.c_action = draft.headline, draft.action_text
    state.c_hours, state.c_cells = draft.duration_hours, list(draft.area_cells)


def stop_editing() -> None:
    state.c_editing = None
    state.c_confirm = False
    load_draft(WarningDraft())


def start_update(alert) -> None:
    state.c_editing = alert.alert_id
    state.c_confirm = False
    load_draft(WarningDraft.updating(alert, w.mesh.now_ms))


def editing_alert():
    return next((a for a in w.live_warnings() if a.alert_id == state.c_editing), None)


def send() -> None:
    state.c_confirm = False
    try:
        editing = editing_alert()
        if editing is not None:
            w.console.update(editing, draft_from_form())
        else:
            w.console.issue(draft_from_form())
    except IssueError:
        return
    stop_editing()


def toggle_place(place, size) -> None:
    state.c_cells = toggle_area(place.latitude, place.longitude, size, list(state.c_cells))


def remove_cell(cell: str) -> None:
    state.c_cells = [c for c in state.c_cells if c != cell]


def cancel(alert) -> None:
    state.c_cancelling = None
    w.console.cancel(alert)
    if state.c_editing == alert.alert_id:
        stop_editing()


def byte_count(title: str, text: str, limit: int) -> None:
    used = len(text.strip().encode())
    colour = "red" if used > limit else "gray"
    st.markdown(f"**{title}** :{colour}[{used} / {limit}]")


def preview_card(draft: WarningDraft) -> None:
    """Roughly what a phone shows: level and hazard on the level's colour, then the
    headline and what to do."""
    fill, on_fill = labels.SEVERITY_FILL[draft.severity], labels.SEVERITY_ON_FILL[draft.severity]
    level = f"{labels.SEVERITY_NAMES[draft.severity]} · {labels.hazard_name(draft.hazard)}"
    headline = html.escape(draft.headline.strip()) or '<span style="opacity:.5">Headline</span>'
    action = html.escape(draft.action_text.strip()) or "What to do"
    st.markdown(f"""
<div style="border:1px solid {fill};border-radius:10px;overflow:hidden">
  <div style="background:{fill};color:{on_fill};padding:10px;font-weight:700">{level}</div>
  <div style="padding:10px"><div style="font-size:1.25em;font-weight:700">{headline}</div>
  <div style="opacity:.75">{action}</div></div>
</div>""", unsafe_allow_html=True)


def places_by_distance() -> list:
    lat, lon = w.centre
    return sorted(places.towns(), key=lambda p: places.distance_km(lat, lon, p.latitude, p.longitude))


def console_tab() -> None:
    state.setdefault("c_hazard", HazardType.FLOOD)
    state.setdefault("c_level", Severity.WATCH_AND_ACT)
    state.setdefault("c_headline", "")
    state.setdefault("c_action", "")
    state.setdefault("c_hours", 6)
    if state.c_editing is not None and editing_alert() is None:
        stop_editing()  # the warning being updated ended or was cancelled meanwhile

    st.caption("You play the Bureau or a government agency. Write a warning, pick its area, check the "
               "preview, send. It is signed with the development key, which phones in this demo trust.")
    left, right = st.columns([5, 6], gap="large")
    with left:
        st.subheader("Update warning" if state.c_editing else "New warning")
        if state.c_editing:
            st.button("Start a new warning", on_click=stop_editing)

        st.selectbox("Hazard", list(HazardType), format_func=labels.hazard_name, key="c_hazard")
        st.radio("Warning level", list(Severity), format_func=labels.SEVERITY_NAMES.get, horizontal=True,
                 key="c_level")
        byte_count("Headline", state.c_headline, HEADLINE_MAX_BYTES)
        st.text_input("Headline", key="c_headline", label_visibility="collapsed")
        byte_count("What to do", state.c_action, ACTION_TEXT_MAX_BYTES)
        st.text_area("What to do", key="c_action", height=80, label_visibility="collapsed")
        st.number_input("Lasts (hours)", DURATION_RANGE.start, DURATION_RANGE.stop - 1, key="c_hours")

        st.markdown("**Area**")
        options = places_by_distance()
        lat, lon = w.centre
        place = st.selectbox(
            "Place (nearest first)", options, key="c_place",
            format_func=lambda p: f"{p.name} ({places.distance_km(lat, lon, p.latitude, p.longitude):.0f} km away)")
        area_size = st.selectbox("Area size", list(AreaSize), index=2, format_func=AREA_SIZE_NAMES.get, key="c_size")
        # Rows of buttons wrap onto the next line in a narrow window.
        with st.container(horizontal=True):
            st.button("Add or remove this area", on_click=toggle_place, args=(place, area_size))
            st.button("Cover the simulated town", on_click=lambda: state.update(c_cells=w.town_cells()))
        if state.c_cells:
            with st.container(horizontal=True):
                for cell in state.c_cells:
                    st.button(cell, key=f"remove_{cell}", icon=":material/close:", help="Remove this area",
                              on_click=remove_cell, args=(cell,))
        else:
            st.caption("Pick a place and a size, then add it. Up to 4 areas.")

        draft = draft_from_form()
        preview_card(draft)
        for problem in draft.problems:
            st.markdown(f":gray[:material/error: {PROBLEM_TEXT[problem]}]")

        st.toggle("Evacuation centre has internet", key="c_online",
                  on_change=lambda: w.set_online(state.c_online))
        updating = state.c_editing is not None
        level = labels.SEVERITY_NAMES[draft.severity]
        if not state.c_confirm:
            st.button("Send update…" if updating else "Send warning…", type="primary", disabled=bool(draft.problems),
                      on_click=lambda: state.update(c_confirm=True))
        else:
            verb = "Update this" if updating else "Send this"
            where = "on every phone in the area?" if updating else "to every phone in the area?"
            st.warning(f"**{verb} {level} {where}**\n\n{CONFIRM_BODY}")
            with st.container(horizontal=True):
                st.button("Send update" if updating else "Send warning", type="primary", on_click=send)
                st.button("Back", on_click=lambda: state.update(c_confirm=False))
        if w.console.last_outcome is not None:
            st.info(outcome_text(w.console.last_outcome), icon=":material/send:")

    with right:
        st.caption("The area picked so far. The black dot is the evacuation centre.")
        st.plotly_chart(viz.area_map(draft.area_cells, labels.SEVERITY_FILL[draft.severity], w.centre),
                        width="stretch", key="console_map", config=MAP_CONFIG)
        live_list()


def live_list() -> None:
    st.subheader("Live warnings")
    alerts = w.live_warnings()
    if not alerts:
        st.caption("No live warnings.")
    for alert in alerts:
        with st.container(border=True):
            colour = labels.SEVERITY_TEXT[alert.severity]
            st.markdown(f'<span style="color:{colour};font-weight:700">{labels.title(alert)}</span> '
                        f"&nbsp;**{html.escape(alert.headline)}**", unsafe_allow_html=True)
            st.caption(f"{labels.until(alert.expires_at, w.mesh.now_ms)} · {', '.join(alert.area_cells)}")
            key = alert.alert_id.hex()
            if state.c_cancelling == alert.alert_id:
                st.warning("**Cancel this warning on every phone?**")
                with st.container(horizontal=True):
                    st.button("Cancel warning", key=f"cancel_yes_{key}", type="primary", on_click=cancel,
                              args=(alert,))
                    st.button("Keep it", key=f"cancel_no_{key}", on_click=lambda: state.update(c_cancelling=None))
                continue
            with st.container(horizontal=True):
                st.button("Update…", key=f"update_{key}", on_click=start_update, args=(alert,))
                st.button("Send again", key=f"resend_{key}", on_click=w.console.resend, args=(alert,))
                st.button("Cancel warning", key=f"cancel_{key}",
                          on_click=lambda a=alert: state.update(c_cancelling=a.alert_id))


# --- Map ----------------------------------------------------------------------


def warning_label(alert_id: bytes) -> str:
    alert = w.sent[alert_id]
    live = any(a.alert_id == alert_id for a in w.live_warnings())
    return f"{labels.title(alert)}: {alert.headline}" + ("" if live else " (ended or cancelled)")


def play(alert_id: bytes, minutes: int) -> None:
    state.m_played = (alert_id, w.play(alert_id, minutes), w.mesh.now_ms)


def map_tab() -> None:
    st.caption("Every dot is a phone. Blue phones read the warning on the internet; red phones got it over "
               "Bluetooth, from a phone nearby or one that walked past. The black dot is the evacuation centre.")
    if not w.sent:
        st.info("No warning yet. Send one from the Warning console, then watch it spread here.")
        alert_id, alert = b"", None
    else:
        ids = list(reversed(w.sent))  # newest first
        alert_id = st.selectbox("Warning", ids, format_func=warning_label, key="m_alert")
        alert = w.sent[alert_id]

    extra = []
    if alert is not None:
        extra += viz.area_traces(alert.area_cells, labels.SEVERITY_FILL[alert.severity])
    extra += [viz.centre_trace(w.centre)]

    played = state.get("m_played")
    if played and played[0] == alert_id and played[2] == w.mesh.now_ms:
        frames = played[1]
        st.caption("Press ▶ to play the minutes that just passed, or drag the slider.")
    else:
        frames = w.phones_now(alert_id)
    _, zoom = viz.fit_zoom(list(zip(frames["lat"], frames["lon"])), maximum=15.5)
    st.plotly_chart(viz.spread_map(frames, zoom=zoom, extra_traces=extra), key="spread_map", config=MAP_CONFIG)

    if alert is not None:
        counts = w.spread(alert_id)
        a, b, c, d = st.columns(4)
        a.metric(f"Warned, of {counts['phones']}", counts["phones"] - counts["not warned yet"],
                 help="Phones holding the warning")
        b.metric(f"In area, of {counts['in area']}", counts["in area warned"],
                 help="Phones inside the warning area that hold it")
        c.metric("Told loudly", counts["told loudly"], help="Phones that showed a loud notification")
        d.metric("Via Bluetooth", counts["warned by Bluetooth"],
                 help="Phones with no internet that got it from another phone")
        minutes = st.slider("Minutes to play", 1, 30, 10, key="m_minutes")
        st.button(f"Let {minutes} minutes pass and record them", type="primary", on_click=play,
                  args=(alert_id, minutes))


# --- Phone view (AlertsView, CommunityReportsView, SOSView) ----------------------


def phone_label(phone) -> str:
    facts = ["internet" if phone.has_internet else "no internet"]
    if phone.route:
        facts.append("walking")
    if not phone.bluetooth_on:
        facts.append("Bluetooth off")
    if not phone.location_on:
        facts.append("location off")
    name = phone.author.nickname if phone.author.nickname != phone.id else phone.id
    return f"{name} ({', '.join(facts)})"


def where_words(lat: float, lon: float) -> str:
    rough = places.describe(lat, lon)
    return places.text(rough) if rough else "Somewhere in Australia"


def report_place(report) -> str:
    return places.label(report.geohash) or report.geohash


def active_sos(phone) -> bool:
    """This phone's own call for help is out: its latest check-in is an SOS still live."""
    last = phone.author.last_check_in
    return bool(last and last.kind is ReportKind.SOS and last.expires_at > w.mesh.now_ms)


def notification_card(content: notifications.Content, loud: bool) -> None:
    body = "<br>".join(html.escape(line) for line in content.body.split("\n"))
    style = "loud (time-sensitive)" if loud else "quiet"
    st.markdown(f"""
<div style="border:1px solid #bbb;border-radius:12px;padding:8px 12px;background:#f6f6f6">
  <div style="font-size:.8em;opacity:.6">Notification · {style}</div>
  <div style="font-weight:700">{html.escape(content.title)}</div><div>{body}</div>
</div>""", unsafe_allow_html=True)


def warning_card(item: world.PhoneWarning) -> None:
    """One warning as the phone lists it: level colour, headline, how close, what to do."""
    alert = item.alert
    fill, on_fill = labels.SEVERITY_FILL[alert.severity], labels.SEVERITY_ON_FILL[alert.severity]
    st.markdown(f"""
<div style="border:1px solid {fill};border-radius:10px;overflow:hidden;margin-bottom:6px">
  <div style="background:{fill};color:{on_fill};padding:8px 10px;font-weight:700">{labels.title(alert)}</div>
  <div style="padding:8px 10px">
    <div style="font-size:1.15em;font-weight:700">{html.escape(alert.headline)}</div>
    <div style="opacity:.75">{labels.proximity(item.now)} · {labels.until(alert.expires_at, w.mesh.now_ms)}</div>
    <div style="margin-top:6px"><b>What to do</b><br>{html.escape(alert.action_text)}</div>
  </div>
</div>""", unsafe_allow_html=True)
    loud = item.now.urgency is Urgency.LOUD
    st.markdown(f"**{'Loud' if loud else 'Quiet'} now:** {labels.REASON_TEXT[item.now.reason.kind]}.")
    content = item.notification()
    if content is None:
        st.caption("No notification shown for this version.")
    else:
        notification_card(content, item.notified.urgency is Urgency.LOUD)


def report_line(report, phone) -> None:
    kind = labels.REPORT_KIND_NAMES[report.kind]
    if report.kind is ReportKind.HAZARD:
        kind += f" · {labels.hazard_name(report.hazard)} · {labels.REPORT_SEVERITY_NAMES.get(report.severity, '')}"
    who = "You" if report.author_signing_key == phone.author.public_key else report.author_nickname
    icon = {ReportKind.SOS: ":material/sos:", ReportKind.SAFE: ":material/check_circle:",
            ReportKind.HAZARD: ":material/warning:"}[report.kind]
    with st.container(border=True):
        st.markdown(f"{icon} **{kind}** — {html.escape(who)}, {report_place(report)}")
        if report.note:
            st.caption(report.note)


def send_sos(phone) -> None:
    w.mesh.send_sos(phone, state.p_sos_note)


def send_safe(phone) -> None:
    w.mesh.send_safe(phone, "")


def send_hazard(phone) -> None:
    w.mesh.send_hazard(phone, state.p_hazard, state.p_how_bad, state.p_report_note)
    state.p_report_note = ""


def phone_tab() -> None:
    st.caption("One phone in the town: what it shows, and why it was loud or quiet. Change its settings, "
               "or send a call for help or a report from it; then let time pass to watch it spread.")
    # Options are IDs, not phones: Streamlit copies its options, and a phone holds a private key.
    ids = [p.id for p in w.phones()]
    default = next(i for i, p in enumerate(w.phones()) if not p.has_internet)
    phone_id = st.selectbox("Phone", ids, index=default, key="p_phone",
                            format_func=lambda i: phone_label(w.mesh.phones[i]))
    phone = w.mesh.phones[phone_id]

    left, right = st.columns([2, 3], gap="large")
    with left:
        st.markdown(f"**Where:** {where_words(phone.lat, phone.lon)}")
        name = st.text_input("Nickname (anyone can pick any name)", phone.author.nickname,
                             max_chars=reports.NICKNAME_MAX_BYTES, key=f"p_name_{phone.id}")
        phone.author.nickname = name.strip() or phone.id
        st.toggle("Bluetooth", phone.bluetooth_on, key=f"p_bt_{phone.id}",
                  on_change=lambda: w.set_phone(phone, bluetooth=state[f"p_bt_{phone.id}"]))
        st.toggle("Location", phone.location_on, key=f"p_loc_{phone.id}",
                  on_change=lambda: w.set_phone(phone, location=state[f"p_loc_{phone.id}"]))
        st.toggle("Internet", phone.has_internet, key=f"p_net_{phone.id}",
                  on_change=lambda: w.set_phone(phone, internet=state[f"p_net_{phone.id}"]))
        towns = [None] + places_by_distance()[:40]
        st.selectbox("Watch a place (for people who keep location off)", towns, key=f"p_watch_{phone.id}",
                     format_func=lambda p: "No watched place" if p is None else p.name,
                     on_change=lambda: w.set_phone(phone, watched=state[f"p_watch_{phone.id}"]))

        st.subheader("Call for help")
        if phone.geohash() is None:
            st.caption("Turn on location first, so people know where to come.")
        elif active_sos(phone):
            st.warning("**Your call for help is out.** It keeps travelling between phones for six hours.")
            with st.container(horizontal=True):
                st.button("I'm safe now", type="primary", on_click=send_safe, args=(phone,))
                st.button("Send it again", on_click=send_sos, args=(phone,))
        else:
            st.caption("This is not 000. If you have any phone signal at all, call emergency services first.")
            st.text_input("Note", placeholder="who is with you, what is wrong (optional)",
                          max_chars=reports.NOTE_MAX_BYTES, key="p_sos_note")
            st.button("Send call for help", type="primary", on_click=send_sos, args=(phone,))

        st.subheader("Report a hazard")
        if phone.geohash() is None:
            st.caption("A report needs a place. Turn on location to send one.")
        else:
            st.selectbox("Type", list(HazardType), format_func=labels.hazard_name, key="p_hazard")
            st.radio("How bad", list(ReportSeverity), format_func=labels.REPORT_SEVERITY_NAMES.get,
                     horizontal=True, key="p_how_bad")
            st.text_input("What's happening here?", max_chars=reports.NOTE_MAX_BYTES, key="p_report_note")
            st.button("Send report", on_click=send_hazard, args=(phone,))

    with right:
        st.subheader("Warnings")
        items = w.warnings_on(phone)
        if not items:
            st.markdown("**No current warnings**")
            st.caption("Keep Bluetooth on. A warning reaches this phone from the internet or from any nearby "
                       "phone that has it, even with no signal.")
        for item in items:
            warning_card(item)

        st.subheader("Community reports")
        st.caption("What people nearby are reporting. These are not official warnings and nobody has checked them.")
        own = [r for r in phone.report_store.live_reports()]
        if not own:
            st.caption("No reports nearby.")
        for report in own:
            report_line(report, phone)

        told = phone.report_notifications
        if told:
            st.subheader("Calls for help it was told about")
            for n in reversed(told[-5:]):
                content = notifications.sos_content(
                    reports.CommunityReport(n.kind, b"", n.geohash, 0, None, n.note, b"", n.nickname, 0, 0, b""),
                    n.urgency)
                notification_card(content, n.urgency is Urgency.LOUD)


# --- Page -----------------------------------------------------------------------

sidebar()
console, spread, phone_view = st.tabs(["Warning console", "Map", "Phone view"])
with console:
    console_tab()
with spread:
    map_tab()
with phone_view:
    phone_tab()
