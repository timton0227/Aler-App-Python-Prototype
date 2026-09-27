"""Maps and charts for the notebook and the Streamlit page.

New code, with no Swift equivalent. Shared by demo.ipynb and app.py so both show the
same pictures. Maps use Plotly's MapLibre maps with OpenStreetMap tiles; without
internet the background stays blank, but the phones still show.

This is free and unencumbered software released into the public domain.
"""
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from alertmesh import metrics
from alertmesh.console import corners
from alertmesh.mesh_sim import Mesh

# Colours: red only for the official warning reaching someone, as in the app, where
# red belongs to Emergency Warnings.
STATUS_COLOURS = {
    "warned by internet": "#1f77b4",
    "warned by Bluetooth": "#d62728",
    "not warned yet": "#9e9e9e",
}


def phone_status(mesh: Mesh, alert_id: bytes) -> list[dict]:
    """One row per phone: where it is and whether (and how) it has the warning."""
    rows = []
    for phone in mesh.phones.values():
        if alert_id not in phone.first_heard_ms:
            status = "not warned yet"
        elif phone.has_internet:
            status = "warned by internet"
        else:
            status = "warned by Bluetooth"
        rows.append({"phone": phone.id, "lat": phone.lat, "lon": phone.lon, "status": status,
                     "moving": bool(phone.route)})
    return rows


def spread_frames(mesh: Mesh, alert_id: bytes, minutes: int, every_min: int = 1) -> pd.DataFrame:
    """Run the mesh for `minutes`, recording every phone's status every `every_min`
    minutes (minute 0 first). The warning must already have been published."""
    frames = []
    for minute in range(0, minutes + 1, every_min):
        if minute:
            mesh.run(every_min * 60)
        for row in phone_status(mesh, alert_id):
            frames.append({**row, "minute": minute})
    return pd.DataFrame(frames)


def spread_map(frames: pd.DataFrame, title: str = "", zoom: float = 13.5):
    """Animated map: press play to watch the warning spread, minute by minute."""
    fig = px.scatter_map(
        frames, lat="lat", lon="lon", color="status", animation_frame="minute",
        hover_name="phone", hover_data={"moving": True, "lat": False, "lon": False, "minute": False},
        color_discrete_map=STATUS_COLOURS, category_orders={"status": list(STATUS_COLOURS)},
        zoom=zoom, height=560, title=title,
    )
    fig.update_traces(marker={"size": 8})
    fig.update_layout(map_style="open-street-map", legend_title_text="", margin={"l": 0, "r": 0, "t": 40, "b": 0})
    return fig


def share_by_minute(frames: pd.DataFrame) -> pd.DataFrame:
    """Share of phones warned at each recorded minute."""
    warned = frames.assign(warned=frames["status"] != "not warned yet")
    return warned.groupby("minute", as_index=False)["warned"].mean().rename(columns={"warned": "share warned"})


def curves_chart(comparison: "metrics.Comparison", title: str = ""):
    """Share warned over time, with the mesh and internet only, on one chart."""
    rows = []
    for label, result in (("with mesh", comparison.with_mesh), ("internet only", comparison.without_mesh)):
        rows += [{"minutes": t / 60, "share warned": s, "network": label}
                 for t, s in zip(result.times_s, result.warned_share)]
    fig = px.line(pd.DataFrame(rows), x="minutes", y="share warned", color="network", markers=True, title=title,
                  color_discrete_map={"with mesh": "#d62728", "internet only": "#1f77b4"})
    fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    return fig


def sweep_chart(table: list[dict], parameter: str, label: str, title: str = ""):
    """Bar chart of a sweep's averages: with mesh vs internet only, per value."""
    rows = []
    for row in table:
        for kind in ("with mesh", "internet only"):
            rows.append({label: str(row[parameter]), "share warned": row[kind], "network": kind})
    fig = px.bar(pd.DataFrame(rows), x=label, y="share warned", color="network", barmode="group", title=title,
                 color_discrete_map={"with mesh": "#d62728", "internet only": "#1f77b4"})
    fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    return fig


# --- Warning areas ------------------------------------------------------------


def area_traces(cells, colour: str, name: str = "warning area") -> list:
    """One filled outline per area cell, for any map figure."""
    traces = []
    for i, cell in enumerate(cells):
        points = corners(cell) + corners(cell)[:1]
        traces.append(go.Scattermap(
            lat=[lat for lat, _ in points], lon=[lon for _, lon in points], mode="lines",
            fill="toself", fillcolor=_with_alpha(colour, 0.18), line={"color": colour, "width": 2},
            name=name, legendgroup=name, showlegend=i == 0, hoverinfo="text", text=cell,
        ))
    return traces


def fit_zoom(points: list[tuple[float, float]], minimum: float = 3.0, maximum: float = 14.0) -> tuple[tuple[float, float], float]:
    """The centre and a map zoom level that shows every (lat, lon) point."""
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    centre = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    # A web map at zoom z shows about 360 / 2**z degrees across a 512-pixel-wide view.
    span = max(max(lons) - min(lons), (max(lats) - min(lats)) * 1.6, 1e-4)
    return centre, max(minimum, min(maximum, math.log2(360 / span) - 0.3))


def area_map(cells, colour: str, centre: tuple[float, float], centre_label: str = "Evacuation centre", height: int = 420):
    """The picked warning area around the evacuation centre, as the console's map shows it."""
    points = [centre] + [c for cell in cells for c in corners(cell)]
    view, zoom = fit_zoom(points, maximum=13.5)
    fig = go.Figure(area_traces(cells, colour))
    # Hover text only: the OpenStreetMap style has no font for text drawn on the map.
    fig.add_trace(go.Scattermap(lat=[centre[0]], lon=[centre[1]], mode="markers", name=centre_label,
                                hoverinfo="name", marker={"size": 14, "color": "#222222"}))
    fig.update_layout(map={"style": "open-street-map", "center": {"lat": view[0], "lon": view[1]}, "zoom": zoom},
                      height=height, margin={"l": 0, "r": 0, "t": 0, "b": 0},
                      legend={"x": 0, "y": 1, "bgcolor": "rgba(255,255,255,0.7)"})
    return fig


def _with_alpha(hex_colour: str, alpha: float) -> str:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"
