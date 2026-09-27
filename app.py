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

from alertmesh import labels, metrics, places, viz, world
from alertmesh.console import AREA_SIZE_NAMES, PROBLEM_TEXT, AreaSize, IssueError, outcome_text, toggle_area
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


# --- Page -----------------------------------------------------------------------

sidebar()
console, spread = st.tabs(["Warning console", "Map"])
with console:
    console_tab()
with spread:
    map_tab()
