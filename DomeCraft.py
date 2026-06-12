# ==========================================================
#  Dome Points Console
#  Same geometry engine as Unified_Dome_Console, but the
#  profile is DRAWN with control points instead of a formula.
#  All math is point-based: PCHIP curve through the points,
#  chord-sum arc length (no derivatives, no singularities).
# ==========================================================
import streamlit as st
import streamlit.components.v1 as components
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import ezdxf
import subprocess, sys, tempfile, os
from scipy.interpolate import PchipInterpolator

# --- Streamlit Page Setup ---
st.set_page_config(page_title="Dome Points Console", layout="wide")

st.markdown("""
    <style>
    body {
        background-color: #fafafa;
        font-family: 'Inter', sans-serif;
        color: #111;
    }
    .main .block-container {
        padding-top: 2rem;
    }
    /* Compact sidebar: all controls visible without scrolling */
    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.3rem;
    }
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 1.2rem;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    [data-testid="stFileUploaderDropzone"] { padding: 0.3rem 0.6rem; min-height: 2.4rem; }
    </style>
""", unsafe_allow_html=True)

# ===== 1. Defaults =====
DEFAULT_POINTS = [[0.0, 1.0], [0.4, 0.98], [0.8, 0.90], [1.2, 0.72], [1.6, 0.45], [2.0, 0.0]]

# ===== 2. Helper Functions (Adjustments via +/- buttons) =====
def adjust_live(name, delta, vmin, vmax):
    push = st.session_state[f"{name}_push"]
    cur = st.session_state.get(f"{name}_now", push["value"])
    push["value"] = float(np.clip(cur + delta, vmin, vmax))
    push["nonce"] += 1

def _apply_box(name, vmin, vmax):
    """Exact numeric entry: push the typed value into the live slider."""
    push = st.session_state.setdefault(f"{name}_push", {"value": vmin, "nonce": 0})
    val = st.session_state.get(f"{name}_box", push["value"])
    push["value"] = float(np.clip(val, vmin, vmax))
    push["nonce"] += 1

# ===== 2a. Live Chart Component =====
# Renders plotly figures inside a persistent iframe that is NEVER re-created
# by Streamlit. Updates arrive as data and are applied in place with
# Plotly.react, so slider moves update the graphs continuously - no flicker
# and no camera/zoom reset.
_live_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_chart")
_plotlyjs_path = os.path.join(_live_dir, "plotly.min.js")
if not os.path.exists(_plotlyjs_path):
    from plotly.offline import get_plotlyjs
    with open(_plotlyjs_path, "w", encoding="utf-8") as _fh:
        _fh.write(get_plotlyjs())

live_chart = components.declare_component("live_chart", path=_live_dir)

def show_live(fig, key, height, default_zoom=1.0):
    fig.update_layout(height=height)
    live_chart(fig=fig.to_json(), height=height, default_zoom=default_zoom, key=key, default=None)

# Continuous slider component: emits values WHILE dragging (Streamlit's own
# slider only commits on release, which made updates look discrete).
_slider_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_slider")
live_slider = components.declare_component("live_slider", path=_slider_dir)

def live_value(name, vmin, vmax, step, decimals, default):
    """Returns the slider's current value. Two-way sync with the +/- buttons:
    Python pushes (value, nonce); the component adopts a pushed value only
    when the nonce changes, so user drags are never overwritten."""
    push = st.session_state.setdefault(f"{name}_push", {"value": default, "nonce": 0})
    push["value"] = float(np.clip(push["value"], vmin, vmax))
    ret = live_slider(value=push["value"], nonce=push["nonce"],
                      min=vmin, max=vmax, step=step, decimals=decimals,
                      key=f"{name}_ls", default={"value": default, "nonce": 0})
    if ret and ret.get("nonce") == push["nonce"]:
        return float(np.clip(ret["value"], vmin, vmax))
    return float(push["value"])

def live_control(label, name, vmin, vmax, step, decimals, default, btn_step):
    """A full control block: label + exact-entry box on one row, then a
    minus-button / live-slider / plus-button row. Used for a, t and the
    second support series so all of them share the exact same design."""
    lr = st.columns([0.55, 0.45])
    with lr[0]: st.markdown(f"**{label}**")
    row = st.columns([0.14, 0.72, 0.14], gap="small")
    with row[0]: st.button("➖", on_click=adjust_live, args=(name, -btn_step, vmin, vmax), key=f"{name}_m")
    with row[1]: val = live_value(name, vmin, vmax, step, decimals, default)
    with row[2]: st.button("➕", on_click=adjust_live, args=(name, +btn_step, vmin, vmax), key=f"{name}_p")
    st.session_state[f"{name}_now"] = val
    with lr[1]:
        st.session_state[f"{name}_box"] = float(round(val, 3))
        st.number_input(f"{label} (exact value)", min_value=float(vmin), max_value=float(vmax),
                        step=step, format="%.3f", key=f"{name}_box",
                        label_visibility="collapsed", on_change=_apply_box, args=(name, vmin, vmax))
    return val

# ===== 2b. DXF Profile Import Helpers =====
def _finish_line_chain(chain, curves):
    if chain is not None and len(chain) >= 2:
        pts_arr = np.array(chain, dtype=float)
        length = float(np.sum(np.hypot(np.diff(pts_arr[:, 0]), np.diff(pts_arr[:, 1]))))
        curves.append({"label": f"LINE chain - {len(pts_arr)} pts, length {length:.2f}",
                       "pts": pts_arr, "length": length})

@st.cache_data(show_spinner=False)
def load_dxf_curves(file_bytes):
    """Extract candidate profile curves from a DXF file.
    Consecutive LINE entities that share endpoints are joined into one chain
    (this is how the consoles' own DXF exports are written)."""
    tmp = os.path.join(tempfile.gettempdir(), "dome_profile_import.dxf")
    with open(tmp, "wb") as fh:
        fh.write(file_bytes)
    doc = ezdxf.readfile(tmp)
    curves = []
    chain = None
    tol = 1e-6
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "LINE":
            s = (e.dxf.start.x, e.dxf.start.y)
            en = (e.dxf.end.x, e.dxf.end.y)
            if chain is not None and abs(chain[-1][0] - s[0]) < tol and abs(chain[-1][1] - s[1]) < tol:
                chain.append(en)
            else:
                _finish_line_chain(chain, curves)
                chain = [s, en]
            continue
        _finish_line_chain(chain, curves)
        chain = None
        try:
            if t == "LWPOLYLINE":
                pts_arr = np.array([(p[0], p[1]) for p in e.get_points()], dtype=float)
            elif t == "POLYLINE":
                pts_arr = np.array([(v.dxf.location.x, v.dxf.location.y) for v in e.vertices], dtype=float)
            elif t in ("SPLINE", "ARC", "ELLIPSE"):
                pts_arr = np.array([(p.x, p.y) for p in e.flattening(0.01)], dtype=float)
            else:
                continue
        except Exception:
            continue
        if len(pts_arr) >= 2:
            length = float(np.sum(np.hypot(np.diff(pts_arr[:, 0]), np.diff(pts_arr[:, 1]))))
            curves.append({"label": f"{t} - {len(pts_arr)} pts, length {length:.2f}",
                           "pts": pts_arr, "length": length})
    _finish_line_chain(chain, curves)
    return curves

def dxf_curve_to_profile(pts_arr):
    """Turn a DXF curve into profile samples (r, z): r increasing, r >= 0."""
    x = pts_arr[:, 0].astype(float)
    y = pts_arr[:, 1].astype(float)
    notes = []
    if x[-1] < x[0]:
        x, y = x[::-1], y[::-1]
    if np.min(x) < 0:
        notes.append(f"Curve shifted right by {-np.min(x):.3f} so it starts at r = 0.")
        x = x - np.min(x)
    dx = np.diff(x)
    if np.any(dx <= 0):
        if np.any(dx < -1e-6 * max(1.0, float(np.ptp(x)))):
            notes.append("Curve is not a function of r (it backtracks); points were re-sorted by r.")
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
        keep = np.concatenate(([True], np.diff(x) > 1e-9))
        x, y = x[keep], y[keep]
    return x, y, notes

# ===== 3. Sidebar - All Inputs =====
with st.sidebar:
    grid_view = st.checkbox("🖥️ 2×2 Grid View (all graphs together)", value=False, key="grid_view")

    N = st.number_input("N (Sides)", min_value=3, max_value=120, value=12, step=1)
    shape_choice = st.radio("Base Shape:", ["Circular", "Polygon"], index=1, horizontal=True)
    k_mode = st.radio("Polygon Scale Mode:", ["Inscribed", "Circumscribed"], index=0, horizontal=True)

    # Visual order: checkboxes -> sliders -> DXF import -> export.
    # Execution order differs (the uploader must run before the slider range
    # is known), so placeholder containers pin each block to its visual slot.
    cont_vis = st.container()    # Supports / Dome Edges + second series
    cont_live = st.container()   # Distance (a) + Angle (t)
    cont_dxf = st.container()    # DXF import (just above Export)

    with cont_dxf:
        dxf_file = st.file_uploader(
            "📥 Profile from DXF", type=["dxf"],
            help="The curve becomes the dome profile f(r): x = radius from center, y = height. "
                 "The longest curve in the file is selected by default.",
        )
        dxf_selected_pts = None
        if dxf_file is not None:
            try:
                dxf_curves = load_dxf_curves(dxf_file.getvalue())
            except Exception as exc:
                dxf_curves = []
                st.error(f"Could not read DXF: {exc}")
            if dxf_curves:
                idx_default = int(np.argmax([c["length"] for c in dxf_curves]))
                choice = st.selectbox(
                    "Curve to use:", list(range(len(dxf_curves))),
                    index=idx_default, format_func=lambda i: dxf_curves[i]["label"],
                )
                dxf_selected_pts = dxf_curves[int(choice)]["pts"]
            else:
                st.warning("No usable curves (LINE / POLYLINE / SPLINE / ARC) found in this file.")

    # The a-slider range follows the profile extent (A = outermost radius)
    if dxf_selected_pts is not None:
        _xr = dxf_selected_pts[:, 0]
        A_est = float(np.nanmax(_xr) - min(0.0, float(np.nanmin(_xr))))
    else:
        _prev_pts = st.session_state.get("points_canvas") or DEFAULT_POINTS
        _radii = [float(p[0]) for p in _prev_pts if p is not None and np.isfinite(p[0])]
        A_est = max(_radii) if _radii else 2.0
    A_est = max(A_est, 0.1)

    with cont_vis:
        vc = st.columns(2)
        with vc[0]: show_supports = st.checkbox("Supports (3D)", value=True)
        with vc[1]: show_edges = st.checkbox("Dome Edges (3D)", value=True)

        series2 = st.checkbox("➕ Second support series", value=False, key="series2")
        if series2:
            # same design as the main Distance/Angle controls
            a2_val = live_control("Distance (a₂)", "a2", -A_est, A_est, 0.01, 2, 0.0, 0.1)
            t2_val = live_control("Angle (t₂)", "t2", 0.0, 1.0, 0.001, 3, 0.5, 0.01)
            s2r2 = st.columns(2)
            with s2r2[0]: count2 = st.number_input("Sections/Side₂", min_value=0, max_value=10, value=2, key="count2")
            with s2r2[1]: spacing2 = st.number_input("Spacing₂", min_value=0.0, max_value=5.0, value=0.5, key="spacing2")
        else:
            t2_val = a2_val = spacing2 = None
            count2 = 0

    with cont_live:
        a_val = live_control("Distance (a)", "a", -A_est, A_est, 0.01, 2, 1.0, 0.1)
        t_val = live_control("Angle (t)", "t", 0.0, 1.0, 0.001, 3, 0.25, 0.01)
        ec = st.columns(2)
        with ec[0]: num_each_side = st.number_input("Sections/Side", 0, 10, 2)
        with ec[1]: export_spacing = st.number_input("Spacing", 0.0, 5.0, 0.5)

    # Always-on display behavior - correct by default, no toggles needed
    show_all_curves = True
    show_min_curve = True
    enable_flattening = True
    mirror_flattening = True
    rotate_flattening = True

    trigger_sections = st.button("📤 Export Sections (2D Poly)", use_container_width=True)
    trigger_stencils = st.button("📤 Export Stencils (Flattened)", use_container_width=True)

# ===== 4. Layout + Profile Source =====
# In grid view all four graphs share one screen: row 1 = board + 3D dome,
# row 2 = 2D sections + flattened stencils. No scrolling needed, so the
# big title is dropped and heights are compact.
if grid_view:
    # The Streamlit header (Deploy row) is a FLOATING bar 3.75rem tall that
    # overlays the content. padding-top must clear it: 4rem puts the top
    # headers right below the bar (vs the 6rem Streamlit default).
    st.markdown("""
        <style>
        [data-testid="stMainBlockContainer"], .main .block-container {
            padding-top: 4rem !important;
            padding-bottom: 0 !important;
        }
        [data-testid="stMain"] div[data-testid="stVerticalBlock"] { gap: 0.35rem; }
        </style>
    """, unsafe_allow_html=True)
    _row1 = st.columns(2, gap="small")
    _row2 = st.columns(2, gap="small")
    cell_board, cell_3d = _row1[0], _row1[1]
    cell_2d, cell_flat = _row2[0], _row2[1]
else:
    st.markdown("<h2 style='text-align:center;'>🏟️ Dome Geometry from Control Points</h2>", unsafe_allow_html=True)
    cell_board = cell_3d = cell_2d = cell_flat = None

# The drawing-board iframe is BOARD_H+40 (toolbar), so the 3D chart gets +40
# to match. The bottom 2D charts get extra height: their internal axes and
# margins shrink the drawing area, so they need more room to LOOK the same
# size - and the values table below is pushed off-screen as a bonus.
BOARD_H = 330 if grid_view else 520
CHART3D_H = 370 if grid_view else 800
CHART2D_H = 450 if grid_view else 600
FLAT_H = 450 if grid_view else 600

with (cell_board if grid_view else st.container()):
    if grid_view:
        st.markdown("**🎯 Control Points**")
    if dxf_selected_pts is not None:
        # Imported DXF curve is the profile; the drawing board is hidden.
        r_imp, z_imp, import_notes = dxf_curve_to_profile(dxf_selected_pts)
        st.info("📥 Profile taken from the imported DXF curve. Remove the file in the sidebar to draw manually.")
        for note in import_notes:
            st.caption("ℹ️ " + note)
        pts = pd.DataFrame({"r": r_imp, "z": z_imp}).dropna()
    else:
        if not grid_view:
            st.caption("🖱️ Click on the board to add a point · drag a point to move it · right-click to delete · "
                       "wheel to zoom · Shift+drag to pan.  r = distance from center (apex at r=0), z = height.")

        _canvas_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "points_canvas")
        points_canvas = components.declare_component("points_canvas", path=_canvas_dir)

        _saved_pts = st.session_state.get("points_canvas")
        canvas_points = points_canvas(
            initial=_saved_pts if _saved_pts else DEFAULT_POINTS,
            default_points=DEFAULT_POINTS,
            height=BOARD_H,
            key="points_canvas",
            default=DEFAULT_POINTS,
        )
        pts = pd.DataFrame(canvas_points or DEFAULT_POINTS, columns=["r", "z"]).dropna()

# --- Clean and validate the points ---
pts = pts[np.isfinite(pts["r"]) & np.isfinite(pts["z"])]
pts = pts[pts["r"] >= 0].sort_values("r").drop_duplicates(subset="r", keep="first")
if len(pts) < 2:
    st.error("⚠️ Need at least 2 valid control points (with r >= 0).")
    st.stop()

r_pts = pts["r"].to_numpy(dtype=float)
z_pts = pts["z"].to_numpy(dtype=float)
A_val = float(r_pts[-1])          # domain end = outermost point
r0_prof = float(r_pts[0])         # innermost point (should be 0 = apex)
if r0_prof > 0:
    st.warning("First control point is not at r=0 - the dome will have a hole at the apex.")

# --- The profile engine: smooth monotone curve through the points ---
# PCHIP passes exactly through every control point without overshooting
# between them; outside [r0, A] it returns NaN (the dome simply ends there).
profile = PchipInterpolator(r_pts, z_pts, extrapolate=False)

def f_profile(r):
    return profile(np.asarray(r, dtype=float))

# --- Dense sampling of the profile (used for preview + arc length) ---
r_dense = np.linspace(r0_prof, A_val, 1500)
z_dense = f_profile(r_dense)
# Chord-sum arc length: works for any drawn shape, no derivatives needed
seg = np.sqrt(np.diff(r_dense) ** 2 + np.diff(z_dense) ** 2)
s_dense = np.concatenate(([0.0], np.cumsum(seg)))

with st.expander("📋 Current Control Points (values)"):
    st.dataframe(pts.round(3).reset_index(drop=True), use_container_width=True)

if dxf_selected_pts is not None:
    # Preview of the imported profile (replaces the drawing board)
    fig_imp = go.Figure()
    fig_imp.add_trace(go.Scatter(x=r_dense, y=z_dense, mode="lines",
                                 line=dict(color="#004d99", width=2), name="Imported Profile"))
    fig_imp.update_layout(height=300 if grid_view else 350, template="plotly_white",
                          xaxis_title="r", yaxis_title="z",
                          margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    fig_imp.update_yaxes(scaleanchor="x", scaleratio=1)
    with (cell_board if grid_view else st.container()):
        st.plotly_chart(fig_imp, use_container_width=True)

# ===== 5. Calculations (same engine as Unified_Dome_Console) =====
sf_factor = 1.0 / np.cos(np.pi / N) if k_mode == "Circumscribed" else 1.0
# Inside a polygon a chord can run out to the VERTEX radius (A*sf/cos(pi/N)),
# which is farther than A - sample that far so sections reach the dome edge
# and get cut exactly there, not at |x| = A.
if shape_choice == "Polygon":
    chord_half = A_val * sf_factor / np.cos(np.pi / N)
else:
    chord_half = A_val
x_min, x_max = -chord_half, chord_half
x_vals = np.linspace(x_min, x_max, 800)
d_step = 1.0 / N
i_start = int((N - (N % 2)) / 2 + (N % 2))
j_end = int((N - ((N - 1) % 2)) / 2)
i_indices = range(i_start, N)
j_indices = range(1, j_end + 1)
def facet_s_list(t_anchor):
    """Facet angles (as s in [0,1)) for a section plane anchored at t_anchor."""
    s = [t_anchor] + \
        [t_anchor - d_step * i for i in i_indices] + \
        [t_anchor - d_step * j for j in j_indices]
    return sorted([(x % 1) for x in s])

s_list = facet_s_list(t_val)

r_max = A_val

def compute_section(a_in, s_set=None):
    """Section of the dome along the vertical plane at distance a_in from center
    (at angle t, or at the angle whose facet list s_set is given).
    Returns (curves, z_min), both cut at the dome edge."""
    s_use = s_list if s_set is None else s_set
    if shape_choice == "Polygon":
        z_args = np.array([
            (a_in * np.sin(2 * np.pi * s) - x_vals * np.cos(2 * np.pi * s)) / sf_factor
            for s in s_use
        ])
        # A point belongs to the dome footprint only if it lies on the inner
        # side of ALL facet edges.
        inside = np.all(z_args <= r_max + 1e-9, axis=0)
        curves = []
        for z_arg in z_args:
            z = f_profile(z_arg)  # NaN outside [r0, A] automatically
            z = np.where((z_arg > 0) & (z_arg <= r_max + 1e-9) & np.isfinite(z), z, np.nan)
            curves.append(z)
        # The facet that OWNS a point is the nearest one = the max projection.
        # f(max dist) equals min(f(dist)) for decreasing profiles, but stays
        # correct when the drawn spline curls back up near the edge.
        d_own = np.max(z_args, axis=0)
        z_env = f_profile(d_own)
        z_env = np.where(inside & (d_own >= 0) & (d_own <= r_max + 1e-9) & np.isfinite(z_env), z_env, np.nan)
        return curves, z_env
    else:
        # Circular dome (surface of revolution)
        r_proj = np.sqrt(a_in ** 2 + x_vals ** 2)
        z = f_profile(r_proj)
        z = np.where((r_proj <= r_max + 1e-9) & np.isfinite(z), z, np.nan)
        return [z], z

Z_all, active_Z = compute_section(a_val)

# --- Flattening (stencil) data: invert the chord-sum arc length ---
k_flat = np.sin(np.pi / N) if k_mode == "Inscribed" else np.tan(np.pi / N)
s_target = np.linspace(0.0, float(s_dense[-1]), 600)
r_inv = np.interp(s_target, s_dense, r_dense)
x_flat_stencil = s_target
y_flat_stencil = r_inv * k_flat

# --- 3D Dome Data ---
# Parametric mesh exactly along the facets (like the original Function_to_Dome),
# so the rim and facet edges are crisp - no square grid, no NaN clipping.
u_prof = np.linspace(r0_prof, A_val, 140)   # facet-distance parameter
z_prof_3d = f_profile(u_prof)

if shape_choice == "Polygon":
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
    m_facet = max(7, int(np.ceil(240 / N)))
    deltas = np.linspace(-np.pi / N, np.pi / N, m_facet)   # offset from facet normal
    theta_all = np.concatenate([ang + deltas for ang in angles])
    # At angular offset delta, the point with facet-distance u sits at radius
    # u*sf/cos(delta): the exact extruded-facet (polyhedral) surface.
    scale_t = np.tile(sf_factor / np.cos(deltas), N)
    RHO = np.outer(scale_t, u_prof)
    X_dome = RHO * np.cos(theta_all[:, None])
    Y_dome = RHO * np.sin(theta_all[:, None])
    Z_dome = np.tile(z_prof_3d, (len(theta_all), 1))
else:
    th_rev = np.linspace(0, 2 * np.pi, 240)
    X_dome = np.outer(np.cos(th_rev), u_prof)
    Y_dome = np.outer(np.sin(th_rev), u_prof)
    Z_dome = np.tile(z_prof_3d, (len(th_rev), 1))

# ===== 6. Main 3D Display =====
fig3d = go.Figure()
fig3d.add_trace(go.Surface(x=X_dome, y=Y_dome, z=Z_dome, colorscale="Blues", opacity=0.6, showscale=False, name="Dome Surface"))

# Overlaid Envelope (shown together with the supports)
angle_rad = 2 * np.pi * t_val
X_line = a_val * np.sin(angle_rad) - x_vals * np.cos(angle_rad)
Y_line = a_val * np.cos(angle_rad) + x_vals * np.sin(angle_rad)
if show_supports:
    fig3d.add_trace(go.Scatter3d(x=X_line, y=Y_line, z=active_Z, mode="lines", line=dict(color="#1565c0", width=3), name="Main Envelope Path"))

# Support Lines
support_plan = []   # collected for the 2D plan view
if show_supports:
    support_a_vals = [a_val + i * export_spacing for i in range(-num_each_side, num_each_side + 1)]
    for a_sup in support_a_vals:
        if np.isclose(a_sup, a_val): continue
        Z_sup = compute_section(a_sup)[1]
        Xs_line = a_sup * np.sin(angle_rad) - x_vals * np.cos(angle_rad)
        Ys_line = a_sup * np.cos(angle_rad) + x_vals * np.sin(angle_rad)
        fig3d.add_trace(go.Scatter3d(x=Xs_line, y=Ys_line, z=Z_sup, mode="lines", line=dict(color="#1565c0", width=3), showlegend=False))
        support_plan.append((Xs_line, Ys_line, Z_sup))

# Second support series - its own angle, center, spacing and count (blue)
support_plan2 = []
if series2:
    s_list2 = facet_s_list(t2_val)
    angle2_rad = 2 * np.pi * t2_val
    for i2 in range(-int(count2), int(count2) + 1):
        a_sup2 = a2_val + i2 * spacing2
        Z_sup2 = compute_section(a_sup2, s_list2)[1]
        Xs2 = a_sup2 * np.sin(angle2_rad) - x_vals * np.cos(angle2_rad)
        Ys2 = a_sup2 * np.cos(angle2_rad) + x_vals * np.sin(angle2_rad)
        fig3d.add_trace(go.Scatter3d(x=Xs2, y=Ys2, z=Z_sup2, mode="lines",
                                     line=dict(color="#1565c0", width=3), showlegend=False))
        support_plan2.append((Xs2, Ys2, Z_sup2))

# Dome skeleton edges (ribs where adjacent facets meet + base rim)
if show_edges:
    if shape_choice == "Polygon":
        u = np.linspace(0.0, r_max, 200)
        rho = u * sf_factor / np.cos(np.pi / N)
        z_rib = f_profile(u)
        z_rib = np.where(np.isfinite(z_rib), z_rib, np.nan)
        facet_angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
        vertex_angles = facet_angles + np.pi / N
        first = True
        for phi in vertex_angles:
            fig3d.add_trace(go.Scatter3d(
                x=rho * np.cos(phi), y=rho * np.sin(phi), z=z_rib,
                mode="lines", line=dict(color="black", width=4),
                name="Dome Edges", legendgroup="edges", showlegend=first))
            first = False
        rim_rho = r_max * sf_factor / np.cos(np.pi / N)
        phis_closed = np.append(vertex_angles, vertex_angles[0])
        z_edge = float(f_profile(r_max))
        fig3d.add_trace(go.Scatter3d(
            x=rim_rho * np.cos(phis_closed), y=rim_rho * np.sin(phis_closed),
            z=np.full(phis_closed.shape, z_edge),
            mode="lines", line=dict(color="black", width=4),
            legendgroup="edges", showlegend=False))
    else:
        th = np.linspace(0, 2 * np.pi, 300)
        z_edge = float(f_profile(r_max))
        fig3d.add_trace(go.Scatter3d(
            x=r_max * np.cos(th), y=r_max * np.sin(th),
            z=np.full(th.shape, z_edge),
            mode="lines", line=dict(color="black", width=4),
            name="Dome Edges", showlegend=True))

# Manual, exactly proportional axes (like the original Function_to_Dome):
# every axis gets the same pad fraction, so 1 unit is 1 unit on x, y AND z.
x_lo3, x_hi3 = float(np.nanmin(X_dome)), float(np.nanmax(X_dome))
y_lo3, y_hi3 = float(np.nanmin(Y_dome)), float(np.nanmax(Y_dome))
z_lo3, z_hi3 = float(np.nanmin(Z_dome)), float(np.nanmax(Z_dome))
sx3 = max(x_hi3 - x_lo3, 1e-9)
sy3 = max(y_hi3 - y_lo3, 1e-9)
sz3 = max(z_hi3 - z_lo3, 1e-9)
pad3 = 0.03
m3 = max(sx3, sy3, sz3)

fig3d.update_layout(
    height=800,
    margin=dict(l=0, r=0, t=50, b=0),
    # Keep the user's camera (rotation/zoom/pan) across reruns - slider moves
    # update the geometry live without resetting the view.
    uirevision="dome-view",
    scene=dict(
        aspectmode="manual",
        aspectratio=dict(x=sx3 / m3, y=sy3 / m3, z=sz3 / m3),
        xaxis=dict(range=[x_lo3 - pad3 * sx3, x_hi3 + pad3 * sx3]),
        yaxis=dict(range=[y_lo3 - pad3 * sy3, y_hi3 + pad3 * sy3]),
        zaxis=dict(range=[z_lo3 - pad3 * sz3, z_hi3 + pad3 * sz3]),
        # Orthographic projection: uniform scale, no perspective distortion
        camera=dict(projection=dict(type="orthographic"), eye=dict(x=0.9, y=0.9, z=1.5)),
    ),
    showlegend=False,
)
with (cell_3d if grid_view else st.container()):
    if grid_view:
        st.markdown("**🏟️ 3D Dome View**")
    show_live(fig3d, "live3d", CHART3D_H, default_zoom=1.35)

# ===== 6b. Plan View - flat top view, always true scale (full layout only) =====
if not grid_view:
    st.markdown("### 🗺️ Plan View (Top, True Scale)")
    fig_plan = go.Figure()
    if shape_choice == "Polygon":
        plan_facets = np.linspace(0, 2 * np.pi, N, endpoint=False)
        plan_vertices = plan_facets + np.pi / N
        plan_rho = r_max * sf_factor / np.cos(np.pi / N)
        plan_closed = np.append(plan_vertices, plan_vertices[0])
        fig_plan.add_trace(go.Scatter(x=plan_rho * np.cos(plan_closed), y=plan_rho * np.sin(plan_closed),
                                      mode="lines", line=dict(color="black", width=2), name="Base"))
        for phi in plan_vertices:
            fig_plan.add_trace(go.Scatter(x=[0, plan_rho * np.cos(phi)], y=[0, plan_rho * np.sin(phi)],
                                          mode="lines", line=dict(color="black", width=1.2), showlegend=False))
    else:
        th_plan = np.linspace(0, 2 * np.pi, 300)
        fig_plan.add_trace(go.Scatter(x=r_max * np.cos(th_plan), y=r_max * np.sin(th_plan),
                                      mode="lines", line=dict(color="black", width=2), name="Base"))

    for (Xs_p, Ys_p, Zs_p) in support_plan:
        m_sup = np.isfinite(Zs_p)
        if np.any(m_sup):
            fig_plan.add_trace(go.Scatter(x=Xs_p[m_sup], y=Ys_p[m_sup], mode="lines",
                                          line=dict(color="#1565c0", width=1.5), showlegend=False))

    for (Xs_p, Ys_p, Zs_p) in support_plan2:
        m_sup2 = np.isfinite(Zs_p)
        if np.any(m_sup2):
            fig_plan.add_trace(go.Scatter(x=Xs_p[m_sup2], y=Ys_p[m_sup2], mode="lines",
                                          line=dict(color="#1565c0", width=1.5), showlegend=False))

    m_env = np.isfinite(active_Z)
    if show_supports and np.any(m_env):
        fig_plan.add_trace(go.Scatter(x=X_line[m_env], y=Y_line[m_env], mode="lines",
                                      line=dict(color="#1565c0", width=1.5), showlegend=False))

    fig_plan.update_layout(height=550, template="plotly_white", xaxis_title="x", yaxis_title="y",
                           uirevision="plan-view",
                           legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5))
    fig_plan.update_yaxes(scaleanchor="x", scaleratio=1)
    show_live(fig_plan, "liveplan", 550)

# ===== 7. 2D Sections =====
fig2d = go.Figure()
if show_all_curves and shape_choice == "Polygon":
    for idx, s in enumerate(s_list):
        dt = (s - t_val) % 1
        color = "red" if (dt < 1e-9 or dt > 1 - 1e-9) else "lightgray"
        fig2d.add_trace(go.Scatter(x=x_vals, y=Z_all[idx], mode="lines", line=dict(color=color, width=1.5), name=f"s={s:.3f}"))
else:
    fig2d.add_trace(go.Scatter(x=x_vals, y=active_Z, mode="lines", line=dict(color="red", width=2), name="Current Section"))
if show_min_curve:
    fig2d.add_trace(go.Scatter(x=x_vals, y=active_Z, mode="lines", line=dict(color="blue", width=2), name="Min Function"))
fig2d.update_layout(height=CHART2D_H, template="plotly_white", xaxis_title="x", yaxis_title="z",
                    uirevision="sections-view", margin=dict(l=45, r=15, t=15, b=40))
fig2d.update_yaxes(scaleanchor="x", scaleratio=1)
with (cell_2d if grid_view else st.container()):
    if grid_view:
        st.markdown("**📈 2D Polygonal Sections**")
    else:
        st.markdown("---")
        st.markdown("### 📈 2D Polygonal Sections")
    show_live(fig2d, "live2d", CHART2D_H)

# ===== 8. Flattened Stencils =====
if enable_flattening:
    fig_flat = go.Figure()
    fig_flat.add_trace(go.Scatter(x=x_flat_stencil, y=y_flat_stencil, mode="lines", line=dict(color="#004d99", width=2), name="Segment Edge"))

    stencil_components = [(x_flat_stencil, y_flat_stencil)]

    if mirror_flattening:
        fig_flat.add_trace(go.Scatter(x=x_flat_stencil, y=-y_flat_stencil, mode="lines", line=dict(color="red", width=1.5, dash="dash"), name="Mirror Edge"))
        stencil_components.append((x_flat_stencil, -y_flat_stencil))

        idx_tip = np.argmax(x_flat_stencil)
        tip_x = np.array([x_flat_stencil[idx_tip], x_flat_stencil[idx_tip]])
        tip_y = np.array([y_flat_stencil[idx_tip], -y_flat_stencil[idx_tip]])
        fig_flat.add_trace(go.Scatter(x=tip_x, y=tip_y, mode="lines", line=dict(color="black", width=2), name="Segment base"))
        stencil_components.append((tip_x, tip_y))

    if rotate_flattening:
        angle_step = 2 * np.pi / N
        for k_i in range(1, N):
            theta = angle_step * k_i
            cos_t, sin_t = np.cos(theta), np.sin(theta)
            for (xv, yv) in stencil_components:
                xr = xv * cos_t - yv * sin_t
                yr = xv * sin_t + yv * cos_t
                fig_flat.add_trace(go.Scatter(x=xr, y=yr, mode="lines", line=dict(color="orange", width=1), showlegend=False))

    fig_flat.update_layout(height=FLAT_H, template="plotly_white", xaxis_title="s (arc-length)", yaxis_title="width",
                           uirevision="flat-view", margin=dict(l=45, r=15, t=15, b=40))
    fig_flat.update_yaxes(scaleanchor="x", scaleratio=1)
    with (cell_flat if grid_view else st.container()):
        if grid_view:
            st.markdown("**✨ Flattened Segment Stencils**")
        else:
            st.markdown("---")
            st.markdown("### ✨ Flattened Segment Stencils")
        show_live(fig_flat, "liveflat", FLAT_H)

# ===== 9. Export Logic =====
def open_save_dialog(title='Save DXF'):
    dialog_code = f"""
import sys
from PyQt5.QtWidgets import QApplication, QFileDialog
app = QApplication(sys.argv)
file, _ = QFileDialog.getSaveFileName(None, '{title}', '', 'DXF Files (*.dxf)')
if file: print(file)
"""
    tmp_file = os.path.join(tempfile.gettempdir(), "qt_save_dialog.py")
    with open(tmp_file, "w", encoding="utf-8") as f: f.write(dialog_code)
    result = subprocess.run([sys.executable, tmp_file], capture_output=True, text=True)
    return result.stdout.strip()

def export_sections_dxf():
    path = open_save_dialog('Save Polygonal Sections')
    if not path: return
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    total_cuts = [a_val + i * export_spacing for i in range(-num_each_side, num_each_side + 1)]
    base_shift = 1.1 * max(1.0, 2 * A_val)

    for idx, a_cut in enumerate(total_cuts):
        offset = (idx - num_each_side) * base_shift
        curves, Z_min_cut = compute_section(a_cut)
        if shape_choice == "Polygon":
            for Z in curves:
                pts_line = [(float(x + offset), float(z)) for x, z in zip(x_vals, Z) if not np.isnan(z)]
                if pts_line: msp.add_lwpolyline(pts_line, dxfattribs={"layer": "Sections"})
        pts_min = [(float(x + offset), float(z)) for x, z in zip(x_vals, Z_min_cut) if not np.isnan(z)]
        if pts_min: msp.add_lwpolyline(pts_min, dxfattribs={"layer": "Envelopes", "color": 5})

    doc.saveas(path)
    st.success(f"✅ Sections Exported to {path}")

def export_stencils_dxf():
    if not enable_flattening:
        st.warning("Flattening is disabled.")
        return
    path = open_save_dialog('Save Flattened Stencils')
    if not path: return
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    components = [(x_flat_stencil, y_flat_stencil)]
    if mirror_flattening:
        components.append((x_flat_stencil, -y_flat_stencil))
        idx_tip = np.argmax(x_flat_stencil)
        tip_x = np.array([x_flat_stencil[idx_tip], x_flat_stencil[idx_tip]])
        tip_y = np.array([y_flat_stencil[idx_tip], -y_flat_stencil[idx_tip]])
        components.append((tip_x, tip_y))

    for (xv, yv) in components:
        for i in range(len(xv) - 1):
            msp.add_line((float(xv[i]), float(yv[i])), (float(xv[i + 1]), float(yv[i + 1])), dxfattribs={"layer": "Stencils"})

    if rotate_flattening:
        angle_step = 2 * np.pi / N
        for k_i in range(1, N):
            theta = angle_step * k_i
            cos_t, sin_t = np.cos(theta), np.sin(theta)
            for (xv, yv) in components:
                xr = xv * cos_t - yv * sin_t
                yr = xv * sin_t + yv * cos_t
                for i in range(len(xr) - 1):
                    msp.add_line((float(xr[i]), float(yr[i])), (float(xr[i + 1]), float(yr[i + 1])), dxfattribs={"layer": "Stencils"})

    doc.saveas(path)
    st.success(f"✅ Stencils Exported to {path}")

if trigger_sections:
    export_sections_dxf()
if trigger_stencils:
    export_stencils_dxf()
