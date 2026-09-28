"""Alert Mesh — the warning app: the Bureau's side.

Run from this folder:

    streamlit run warning_app.py

or use Run and Debug -> "Warning app" in VS Code.

Write and send official warnings (Warning console), watch one spread through a
simulated town (Map), and see the evacuation centre's wall display (Hub board).

Each warning goes two ways:
- into the simulated town: about 300 phones, a few with internet, and an evacuation
  centre (a Mac) in the middle. Time there only moves when you press a "+ minutes"
  button in the sidebar;
- to real phone apps (phone_app.py) on the same local network or computer, signed
  again with the real time (see `console.NetworkShare`);
- with "Send over the internet" on, the same real-time copies also go to public Nostr
  relays, where iPhones running Alert Mesh and phone apps anywhere pick them up (see
  `alertmesh.internet`).

This is free and unencumbered software released into the public domain.
"""
import html
import threading

import streamlit as st

from alertmesh import hub, internet, labels, lan, metrics, places, style, viz, world
from alertmesh.console import (
    AREA_SIZE_NAMES, PROBLEM_TEXT, AreaSize, IssueError, NetworkShare, outcome_text, toggle_area,
)
from alertmesh.signer import DURATION_RANGE, WarningDraft
from alertmesh.wire import ACTION_TEXT_MAX_BYTES, HEADLINE_MAX_BYTES, HazardType, Severity

st.set_page_config(page_title="Alert Mesh warnings", layout="wide")

state = st.session_state

# The mouse wheel scrolls the page, not the map; the maps zoom with their + and - buttons.
MAP_CONFIG = {"scrollZoom": False}


# --- The town -----------------------------------------------------------------


@st.cache_resource
def network() -> lan.Broadcaster:
    """One sender for the whole program, shared by every browser tab."""
    return lan.Broadcaster()


@st.cache_resource
def internet_sender() -> internet.WarningSender:
    """The internet link, off until switched on. One for the whole program."""
    from alertmesh.relays import RelayPool

    return internet.WarningSender(RelayPool(), internet.RelayChoice.from_environment())


def share(payload: bytes) -> bool:
    """Real phone apps get each warning on the local network and, when switched on, on
    the internet. True if it went on the local network (the console's outcome line)."""
    internet_sender().send(payload)
    return network().send(payload)


@st.cache_resource
def network_share() -> NetworkShare:
    return NetworkShare(share)


def new_town(scenario: metrics.Scenario) -> None:
    # A new town (also: a new browser tab, or reloading the page) cannot see the warnings
    # the old one sent, so it could never cancel them: withdraw them from phone apps.
    network_share().withdraw_all()
    state.world = world.build(scenario, share=network_share())
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


CONSOLE, MAP, BOARD = "Warning console", "Map", "Hub board"


def town_settings() -> None:
    """Build a new simulated town. Tucked into the sidebar: most people never change it."""
    s = w.scenario
    with st.sidebar.expander(f"Simulated town: {s.town}, {s.n_phones} phones"):
        with st.form("town", border=False):
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
        st.caption("A simulated town, plus real phone apps on this network. Nothing here uses the real internet "
                   "unless \"Send over the internet\" is on.")
        st.caption(places.CREDIT)


def set_internet() -> None:
    sender = internet_sender()
    sender.enabled = state.internet_on
    if sender.enabled:
        # Warnings already live go out too, and the relay list is brought up to date.
        for payload in network().live():
            sender.send(payload)
        threading.Thread(target=sender.choice.refresh, name="relay-list", daemon=True).start()


def internet_switch() -> None:
    sender = internet_sender()
    state.internet_on = sender.enabled  # the same for every browser tab
    st.sidebar.toggle("Send over the internet", key="internet_on", on_change=set_internet,
                      disabled=not sender.pool.available,
                      help="Also send each warning to public Nostr relays, as the Bureau's Mac does. iPhones "
                           "running Alert Mesh (a Debug build) and phone apps anywhere get it. Anyone can read "
                           "what is sent there." if sender.pool.available
                      else "Needs the websockets library: python3 -m pip install -r requirements.txt")


def clock_box() -> None:
    """The simulated clock at the foot of the sidebar. Time there only moves when asked."""
    with st.sidebar.container(key="am_foot"):
        st.markdown(f'<div class="am-muted am-hide-compact" style="font-size:12px">Simulated time · minute '
                    f'{w.minutes:g}</div><div class="am-clock">{labels.clock(w.mesh.now_ms)}</div>',
                    unsafe_allow_html=True)
        with st.container(horizontal=True, gap="small", key="am_advance"):
            for minutes in (1, 5, 15):
                st.button(f"+{minutes}", key=f"advance_{minutes}", on_click=w.advance, args=(minutes,),
                          help=f"Let {minutes} simulated minutes pass")


def internet_words(sender: internet.WarningSender) -> tuple[bool, str]:
    if not sender.pool.available:
        return False, "Internet off · needs the websockets library"
    if not sender.enabled:
        return False, "Internet off"
    connected, total = sender.pool.status()
    words = f"Internet on · {connected} of {total} relays connected" if total else "Internet on"
    taken = sender.status()
    if taken is not None:
        words += f" · last warning taken by {taken[0]} of {taken[1]}"
    return connected > 0, words


@st.fragment(run_every=2)
def status_bar() -> None:
    """Redrawn every 2 seconds on its own: relays answer after the page has run."""
    on = network().status == "on"
    words = ("Local network on · warnings go to phone apps on this network" if on
             else f"Local network {network().status}")
    style.status_bar([(on, words), internet_words(internet_sender())], "Signed with the development key")


# --- Warning console (IssueWarningView) -----------------------------------------

CONFIRM_BODY = ("It goes to nearby devices over Bluetooth and to phones in the area over the internet, and "
                "to phone apps on this network. Phones treat it as an official warning.")
CONFIRM_INTERNET = ("**\"Send over the internet\" is on:** it also goes to public relays, where iPhones and "
                    "phone apps anywhere get it.")


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
    """The warning as a phone in the area shows it: the solid block in the level's colour
    (NowView.affectedBlock), then what to do."""
    level = style.LEVEL[draft.severity]
    headline = style.esc(draft.headline.strip()) or '<span style="opacity:.6">Headline</span>'
    action = style.esc(draft.action_text.strip()) or '<span style="opacity:.6">What to do</span>'
    st.markdown(hub.one_line(f"""
<div class="am-block am-fill-{level}">{style.symbol_on_fill(draft.severity)}
<span class="am-lvl">{labels.SEVERITY_NAMES[draft.severity]}</span>
<span class="am-stand">You are in this area</span>
<span class="am-headline">{headline}</span>
<span class="am-meta"><span>{labels.hazard_name(draft.hazard)}</span><span>For {int(draft.duration_hours)} hours</span></span>
</div>
<div class="am-card am-border-{level}"><div class="am-section">What to do</div>
<div class="am-action">{action}</div></div>"""), unsafe_allow_html=True)


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

    if w.console.last_outcome is not None:
        st.info(outcome_text(w.console.last_outcome), icon=":material/send:")
    st.caption("You play the Bureau or a government agency. Write a warning, pick its area, check the "
               "preview, send. It is signed with the development key, which phones in this demo trust.")
    left, right = st.columns([5, 6], gap="large")
    with left:
        st.markdown(f'<div class="am-section">{"Update warning" if state.c_editing else "New warning"}</div>',
                    unsafe_allow_html=True)
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

        st.markdown('<div class="am-section">Area</div>', unsafe_allow_html=True)
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
            body = CONFIRM_BODY + ("\n\n" + CONFIRM_INTERNET if internet_sender().enabled else "")
            st.warning(f"**{verb} {level} {where}**\n\n{body}")
            with st.container(horizontal=True):
                for draw in style.button_order(
                        lambda: st.button("Send update" if updating else "Send warning", type="primary", on_click=send),
                        lambda: st.button("Back", on_click=lambda: state.update(c_confirm=False))):
                    draw()

    with right:
        st.markdown('<div class="am-section">As phones in the area show it</div>', unsafe_allow_html=True)
        preview_card(draft)
        st.caption("The area picked so far. The black dot is the evacuation centre.")
        st.plotly_chart(viz.area_map(draft.area_cells, labels.SEVERITY_FILL[draft.severity], w.centre),
                        width="stretch", key="console_map", config=MAP_CONFIG)
        live_list()


def live_list() -> None:
    st.markdown('<div class="am-section">Live warnings</div>', unsafe_allow_html=True)
    alerts = w.live_warnings()
    if not alerts:
        st.caption("No live warnings.")
    for alert in alerts:
        level = style.LEVEL[alert.severity]
        st.markdown(hub.one_line(f"""
<div class="am-card am-other" style="margin-bottom:0"><span class="am-colourbar am-bar-{level}"></span><div>
<div class="am-level am-t-{level}">{style.symbol(alert.severity, "var(--am-card)")}{labels.title(alert)}</div>
<div class="am-headline">{style.esc(alert.headline)}</div>
<div class="am-muted">{labels.until(alert.expires_at, w.mesh.now_ms)} · {", ".join(alert.area_cells)}</div>
</div></div>"""), unsafe_allow_html=True)
        key = alert.alert_id.hex()
        if state.c_cancelling == alert.alert_id:
            st.warning("**Cancel this warning on every phone?**")
            with st.container(horizontal=True):
                for draw in style.button_order(
                        lambda: st.button("Cancel warning", key=f"cancel_yes_{key}", type="primary", on_click=cancel,
                                          args=(alert,)),
                        lambda: st.button("Keep it", key=f"cancel_no_{key}",
                                          on_click=lambda: state.update(c_cancelling=None))):
                    draw()
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


# --- Hub board (HubBoardView) -------------------------------------------------------


def hub_tab() -> None:
    st.caption("The evacuation centre's wall display: every live warning its Mac holds, the most serious in "
               "large type. It stays black whatever the system's setting, for a projector in a hall. It changes "
               "only when time passes or something is sent.")
    st.markdown(hub.board_html(w.board(), w.mesh.now_ms), unsafe_allow_html=True)


# --- Page -----------------------------------------------------------------------

style.inject()
PAGES = [(CONSOLE, ":material/edit_note:"), (MAP, ":material/map:"), (BOARD, ":material/tv:")]
view = style.nav(PAGES, {}, "Warnings")
style.shortcuts(style.nav_shortcuts(PAGES))  # ⌘1-3 (Ctrl on Windows) for the tabs
town_settings()
internet_switch()
clock_box()
status_bar()
style.page_title(view)
if view == MAP:
    map_tab()
elif view == BOARD:
    hub_tab()
else:
    console_tab()
