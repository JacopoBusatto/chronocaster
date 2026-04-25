"""
CTD Filter Delay Calculator — Streamlit Web App
"""

import time as _time
import re as _re
from datetime import datetime as _datetime, timezone as _timezone

import streamlit as st
import streamlit.components.v1 as _components
import plotly.graph_objects as go
import pandas as pd

try:
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
    _HAS_AUTOREFRESH = True
except ImportError:
    _st_autorefresh = None
    _HAS_AUTOREFRESH = False

from calculator import CastParams, compute_delays, fmt_time, required_speed as _rspeed, travel_time as _tt

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CTD Filter Delay Calculator",
    page_icon="🌊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state — Cast Tracker
# ---------------------------------------------------------------------------
if "cast_active" not in st.session_state:
    st.session_state.cast_active = False
if "cast_t0_wall" not in st.session_state:
    st.session_state.cast_t0_wall = None
if "cast_phase_start_wall" not in st.session_state:
    st.session_state.cast_phase_start_wall = None  # wall time when current phase began
if "live_t2_depths" not in st.session_state:
    st.session_state.live_t2_depths = []
if "cast_phase_idx" not in st.session_state:
    st.session_state.cast_phase_idx = 0
if "cast_actual_trace" not in st.session_state:
    # list of (elapsed_s, depth_m, label) — one entry logged each time Done is pressed
    st.session_state.cast_actual_trace = []
if "actual_presets" not in st.session_state:
    # dict of filter_id → actual preset delay (s) as programmed on the instrument
    st.session_state.actual_presets = {}

st.title("🌊 CTD Filter Delay Calculator")
st.caption(
    "Calculates preset timer delays for each filter actuation. "
    "T=0 is the moment you start the timers (before the CTD enters the water)."
)

# ---------------------------------------------------------------------------
# Sidebar — Cast parameters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Cast Parameters")

    max_depth = st.number_input("Max cast depth (m)", min_value=1, max_value=6000, value=80, step=1)

    st.divider()
    st.subheader("CTD Dynamics")
    v_max = st.number_input("CTD speed (m/s)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, format="%.2f")
    accel = st.number_input("Acceleration (m/s²)", min_value=0.01, max_value=1.0, value=0.1, step=0.01, format="%.3f")

    st.divider()
    with st.expander("🔬 Advanced settings"):
        st.caption("Instrument behaviour and winch limits.")
        v_hard_max = st.number_input(
            "Max winch speed (m/s)", min_value=0.1, max_value=5.0, value=1.7, step=0.1, format="%.2f",
            help="Physical maximum speed of the winch. Used for 🟡 threshold in speed status.",
        )
        clock_reset = st.toggle(
            "Instrument timer resets after each filter",
            value=True,
            help=(
                "When ON: the instrument timer restarts from 0 when the previous filter ends. "
                "The displayed preset is the delay from the previous filter's end, not from T=0."
            ),
        )
        st.divider()
        st.caption("Instrument timing")

        def _mmss_to_s(text: str) -> int:
            """Parse MM:SS or M:SS or plain seconds. Returns 0 on error."""
            text = text.strip()
            parts = text.split(":")
            try:
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
                return int(float(text))
            except ValueError:
                return 0

        _deploy_raw = st.text_input("Deploy delay (MM:SS)", value="5:00", key="deploy_delay_input",
            help="Duration of the 'Lowering CTD into water' phase — from T=0 (clock started on deck) to first descent. Format MM:SS.")
        deploy_delay_s = _mmss_to_s(_deploy_raw)

        _bottom_dwell_raw = st.text_input("Time at bottom (MM:SS)", value="0:30", key="bottom_dwell_input",
            help="Dwell time at max depth before starting ascent. Format MM:SS.")
        bottom_dwell_s = _mmss_to_s(_bottom_dwell_raw)

        _homing_raw = st.text_input("Homing time (MM:SS)", value="0:30", key="homing_time_input",
            help="Instrument spin-up time after timer fires, before pumping begins. Format MM:SS.")
        homing_time_s = _mmss_to_s(_homing_raw)

        _actuation_raw = st.text_input("Actuation buffer (MM:SS)", value="0:10", key="actuation_buffer_input",
            help="Loading time after homing before actual water flow starts. Format MM:SS.")
        actuation_buffer_s = _mmss_to_s(_actuation_raw)

# ---------------------------------------------------------------------------
# Main area — Filter configuration
# ---------------------------------------------------------------------------
col_t1, col_t2 = st.columns(2)

with col_t1:
    st.subheader("🔽 Downcast filters")
    st.caption("Activate on the way down. CTD stops, filters, then continues.")
    n_t1 = st.number_input("Number of Downcast filters", min_value=0, max_value=10, value=1, key="n_t1")
    t1_depths = []
    t1_durations_s = []
    t1_margins_s = []

    def _parse_mmss(text: str, default_s: int) -> int:
        text = text.strip()
        parts = text.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            return int(float(text))
        except ValueError:
            return default_s

    for i in range(int(n_t1)):
        st.markdown(f"**Downcast filter {i+1}**")
        _fc1, _fc2, _fc3 = st.columns([2, 2, 2])
        with _fc1:
            d = st.number_input("Depth (m)", min_value=1, max_value=int(max_depth),
                value=min(5*(i+1), int(max_depth)), key=f"t1_{i}")
        with _fc2:
            _dur_raw = st.text_input("Timeout (MM:SS)", value="15:00", key=f"t1_dur_{i}",
                help="Sample Volume Timeout after — format MM:SS.")
        with _fc3:
            _margin_raw = st.text_input("Safety (MM:SS)", value="1:00", key=f"t1_margin_{i}",
                help="Extra time buffer before timer fires — format MM:SS.")
        t1_depths.append(float(d))
        t1_durations_s.append(float(_parse_mmss(_dur_raw, 900)))
        t1_margins_s.append(float(_parse_mmss(_margin_raw, 60)))

with col_t2:
    st.subheader("🔼 Upcast filters")
    st.caption("Activate on the way up. Sampling depth can be adjusted after seeing the profile.")
    n_t2 = st.number_input("Number of Upcast filters", min_value=0, max_value=10, value=1, key="n_t2")
    t2_depths = []
    t2_durations_s = []
    t2_margins_s = []
    for i in range(int(n_t2)):
        st.markdown(f"**Upcast filter {i+1}**")
        _fc1, _fc2, _fc3 = st.columns([2, 2, 2])
        with _fc1:
            d = st.number_input("Depth (m)", min_value=1, max_value=int(max_depth),
                value=min(50 + 10*i, int(max_depth)), key=f"t2_{i}")
        with _fc2:
            _dur_raw = st.text_input("Timeout (MM:SS)", value="15:00", key=f"t2_dur_{i}",
                help="Sample Volume Timeout after — format MM:SS.")
        with _fc3:
            _margin_raw = st.text_input("Safety (MM:SS)", value="1:00", key=f"t2_margin_{i}",
                help="Extra time buffer before timer fires — format MM:SS.")
        t2_depths.append(float(d))
        t2_durations_s.append(float(_parse_mmss(_dur_raw, 900)))
        t2_margins_s.append(float(_parse_mmss(_margin_raw, 60)))

# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
st.divider()

if not t1_depths and not t2_depths:
    st.warning("Add at least one filter to compute delays.")
    st.stop()

try:
    params = CastParams(
        max_depth_m=float(max_depth),
        type1_depths=t1_depths,
        type2_depths=t2_depths,
        v_max=v_max,
        accel=accel,
        filter_duration_s=900.0,     # global default (fallback)
        safety_margin_s=300.0,       # global default (fallback)
        type1_filter_durations=t1_durations_s,
        type2_filter_durations=t2_durations_s,
        type1_safety_margins=t1_margins_s,
        type2_safety_margins=t2_margins_s,
        deploy_delay_s=float(deploy_delay_s),
        bottom_dwell_s=float(bottom_dwell_s),
        homing_time_s=float(homing_time_s),
        actuation_buffer_s=float(actuation_buffer_s),
    )
    filter_stops, timeline, total_time_s = compute_delays(params)
except Exception as e:
    st.error(f"Computation error: {e}")
    st.stop()

t1_stops = [f for f in filter_stops if f.filter_type == 1]
t2_stops = [f for f in filter_stops if f.filter_type == 2]

# These are overwritten inside the active tracker with live T2 depths
_live_stops = filter_stops
_live_total = total_time_s

# Key timeline events (reused in tracker dashboard)
_bottom_evt = next((e for e in timeline if e.event_type == "bottom"), None)
_bottom_arrive_s = _bottom_evt.time_s if _bottom_evt else None
_bottom_leave_evt = next((e for e in timeline if e.event_type == "bottom_leave"), None)
_bottom_leave_s = _bottom_leave_evt.time_s if _bottom_leave_evt else _bottom_arrive_s
_surface_return_evt = next((e for e in timeline if e.event_type == "surface_return"), None)
_surface_return_s   = _surface_return_evt.time_s if _surface_return_evt else None
_surface_evt = None  # surface stop removed
_recovered_evt = next((e for e in timeline if e.label == "Recovered"), None)

# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------
st.subheader("📋 Preset Delays")

rows = []
_prev_departure_s = 0.0
for fs in filter_stops:
    _instr_s = fs.preset_delay_s - _prev_departure_s if clock_reset else fs.preset_delay_s
    rows.append({
        "Filter ID": fs.filter_id,
        "Depth (m)": round(fs.depth_m, 2),
        "Scheduled at": fmt_time(fs.preset_delay_s),
        "Instrument setting": fmt_time(_instr_s),
        "Filter ends at": fmt_time(fs.departure_time_s),
    })
    _prev_departure_s = fs.departure_time_s

df = pd.DataFrame(rows)
st.dataframe(df, width='stretch', hide_index=True)

st.metric("Total cast duration", fmt_time(total_time_s))

# ---------------------------------------------------------------------------
# 🚀 Start Cast Tracker
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🚀 Start Cast Tracker")

# Sentinel values — overwritten when cast is active
_cast_elapsed_s  = 0.0
_cast_depth      = 0.0
_cast_from_depth = 0.0
_dot_marker_color = "#28a745"   # green by default
_is_travel = False
_live_stops = filter_stops
_live_total = total_time_s
_live_t2_stops = t2_stops
_live_tl = timeline
_phases: list = []

# ---------------------------------------------------------------------------
# Helper: build ordered preset phase list from a set of filter stops
# ---------------------------------------------------------------------------
def _build_phases(live_stops, bottom_arrive_s, bottom_leave_s, recovered_evt,
                  surface_return_s=None, deploy_delay_s=0.0):
    """
    Each phase stores the time it STARTS (not ends).
    depth_m      = target/arrival depth (for graph marker, banner)
    from_depth_m = where the CTD is at the START of the phase (for speed calculations)
    """
    ph = []
    _t1 = [f for f in live_stops if f.filter_type == 1]
    _t2 = [f for f in live_stops if f.filter_type == 2]

    _prev_depart = float(deploy_delay_s)  # descent starts after deploy delay
    _prev_depth  = 0.0

    ph.append({"label": "🚀 Deployment phase",
               "time_s": 0.0, "depth_m": 0.0, "from_depth_m": 0.0})

    for _fs in _t1:
        ph.append({"label": f"🔽 Descending to {_fs.filter_id} ({_fs.depth_m:.0f} m)",
                   "time_s": _prev_depart, "depth_m": _fs.depth_m, "from_depth_m": _prev_depth})
        if _fs.preset_delay_s > _fs.arrival_time_s + 1:
            ph.append({"label": f"⏳ Waiting at {_fs.filter_id} ({_fs.depth_m:.0f} m)",
                       "time_s": _fs.arrival_time_s, "depth_m": _fs.depth_m, "from_depth_m": _fs.depth_m})
        ph.append({"label": f"🔽 Filtering at {_fs.filter_id} ({_fs.depth_m:.0f} m)",
                   "time_s": _fs.preset_delay_s, "depth_m": _fs.depth_m, "from_depth_m": _fs.depth_m})
        _prev_depart = _fs.departure_time_s
        _prev_depth  = _fs.depth_m

    # After T1 filters: return to surface, then main downcast
    if _t1 and surface_return_s is not None:
        ph.append({"label": "🔼 Returning to surface",
                   "time_s": _prev_depart, "depth_m": 0.0, "from_depth_m": _prev_depth})
        _prev_depart = surface_return_s
        _prev_depth  = 0.0

    if bottom_arrive_s is not None:
        ph.append({"label": f"🔽 Descending to bottom ({max_depth:.0f} m)",
                   "time_s": _prev_depart, "depth_m": float(max_depth), "from_depth_m": _prev_depth})
        ph.append({"label": "⚓ At bottom",
                   "time_s": bottom_arrive_s, "depth_m": float(max_depth), "from_depth_m": float(max_depth)})
        _prev_depart = bottom_leave_s   # leave after dwell
        _prev_depth  = float(max_depth)

    for _fs in _t2:
        ph.append({"label": f"🔼 Ascending to {_fs.filter_id} ({_fs.depth_m:.0f} m)",
                   "time_s": _prev_depart, "depth_m": _fs.depth_m, "from_depth_m": _prev_depth})
        if _fs.preset_delay_s > _fs.arrival_time_s + 1:
            ph.append({"label": f"⏳ Waiting at {_fs.filter_id} ({_fs.depth_m:.0f} m)",
                       "time_s": _fs.arrival_time_s, "depth_m": _fs.depth_m, "from_depth_m": _fs.depth_m})
        ph.append({"label": f"🔼 Filtering at {_fs.filter_id} ({_fs.depth_m:.0f} m)",
                   "time_s": _fs.preset_delay_s, "depth_m": _fs.depth_m, "from_depth_m": _fs.depth_m})
        _prev_depart = _fs.departure_time_s
        _prev_depth  = _fs.depth_m

    if recovered_evt:
        ph.append({"label": "🔼 Recovering to deck",
                   "time_s": _prev_depart, "depth_m": 0.0, "from_depth_m": _prev_depth})
    return ph

# Pre-cast: build phases from planned depths for the cheat sheet
_phases = _build_phases(filter_stops, _bottom_arrive_s, _bottom_leave_s, _recovered_evt,
                        surface_return_s=_surface_return_s, deploy_delay_s=deploy_delay_s)

# ---------------------------------------------------------------------------
if not st.session_state.cast_active:
    # Editable actual presets — what the operator actually programmed on the instrument
    with st.expander("🔧 Actual programmed presets (override before casting)", expanded=True):
        _clock_note = ("relative to previous filter end (clock reset ON)"
                       if clock_reset else "absolute from T=0 (clock reset OFF)")
        st.caption(
            f"Enter the value you programmed on the instrument — {_clock_note}. Format: H:MM:SS"
        )
        def _s_to_hmmss(s):
            s = int(round(s))
            return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"

        def _hmmss_to_s(text):
            """Parse H:MM:SS or MM:SS or plain seconds. Returns None on error."""
            text = text.strip()
            parts = text.split(":")
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
                else:
                    return int(float(text))
            except ValueError:
                return None

        _all_stops = [f for f in filter_stops]

        # Build per-filter computed instrument setting (absolute or relative).
        # _prev_dep_map uses *effective* (overridden) departures so that entering
        # a relative value for filter N is correctly based on filter N-1's actual departure.
        _prev_dep_orig = 0.0   # original plan departures (for _computed_instr display)
        _prev_dep_eff  = 0.0   # effective (overridden) departures (for _prev_dep_map conversion)
        _computed_instr: dict[str, float] = {}   # filter_id → seconds as shown on instrument
        _prev_dep_map:   dict[str, float] = {}   # filter_id → effective previous departure (to convert back)
        for _fs in _all_stops:
            _instr_default = _fs.preset_delay_s - _prev_dep_orig if clock_reset else _fs.preset_delay_s
            _computed_instr[_fs.filter_id] = _instr_default
            _prev_dep_map[_fs.filter_id]   = _prev_dep_eff
            _prev_dep_orig = _fs.departure_time_s
            # Use the already-stored override (if any) to advance the effective departure cursor
            _eff_abs = st.session_state.actual_presets.get(_fs.filter_id)
            if _eff_abs is None or abs(_eff_abs - _fs.preset_delay_s) > 3600:  # stale/bogus
                _eff_abs = _fs.preset_delay_s
            # dwell = homing + buffer + filter_duration (departure - preset)
            _dwell = _fs.departure_time_s - _fs.preset_delay_s
            _prev_dep_eff = _eff_abs + _dwell

        # Pre-initialize each widget's session state key from the computed instrument setting.
        # Reset if clock_reset mode changed OR if the config changed (computed values differ).
        _cr_key = "clock_reset_mode"
        _cfg_fp_key = "computed_instr_fp"
        _computed_fp = str(sorted(_computed_instr.items()))  # fingerprint of current computed values
        _mode_changed = st.session_state.get(_cr_key) != clock_reset
        _config_changed = st.session_state.get(_cfg_fp_key) != _computed_fp
        if _mode_changed or _config_changed:
            st.session_state[_cr_key] = clock_reset
            st.session_state[_cfg_fp_key] = _computed_fp
            for _fs in _all_stops:
                st.session_state[f"actual_preset_{_fs.filter_id}"] = _s_to_hmmss(_computed_instr[_fs.filter_id])

        for _fs in _all_stops:
            _wkey = f"actual_preset_{_fs.filter_id}"
            if _wkey not in st.session_state:
                st.session_state[_wkey] = _s_to_hmmss(_computed_instr[_fs.filter_id])

        _cols = st.columns(min(len(_all_stops), 6))
        for _i, _fs in enumerate(_all_stops):
            with _cols[_i % min(len(_all_stops), 6)]:
                _label = (f"{_fs.filter_id} (T1 {_fs.depth_m:.0f}m)" if _fs.filter_type == 1
                          else f"{_fs.filter_id} (T2 {_fs.depth_m:.0f}m)")
                _entered = st.text_input(
                    _label,
                    help=(f"Computed instrument setting: {fmt_time(_computed_instr[_fs.filter_id])}  "
                          f"·  absolute T+: {fmt_time(_fs.preset_delay_s)}  ·  Format H:MM:SS"),
                    key=f"actual_preset_{_fs.filter_id}",
                )
                _parsed_instr = _hmmss_to_s(_entered)
                if _parsed_instr is not None:
                    # Convert back to absolute seconds for internal storage
                    _abs_s = (_parsed_instr + _prev_dep_map[_fs.filter_id]
                              if clock_reset else float(_parsed_instr))
                    st.session_state.actual_presets[_fs.filter_id] = _abs_s
                else:
                    st.warning(f"{_fs.filter_id}: invalid format, use H:MM:SS")

    with st.expander("📋 Pre-cast reference", expanded=True):
        _r1, _r2 = st.columns(2)
        _r1.metric("Total cast", fmt_time(total_time_s))
        _r2.metric("Arrive bottom", fmt_time(_bottom_arrive_s) if _bottom_arrive_s else "—")
        _pc_rows = []
        for _pi, p in enumerate(_phases):
            _next_t = _phases[_pi + 1]["time_s"] if _pi + 1 < len(_phases) else total_time_s
            _dur_s = _next_t - p["time_s"]
            _pc_rows.append({
                "Phase": p["label"],
                "Scheduled at": fmt_time(p["time_s"]),
                "Duration": fmt_time(_dur_s) if _dur_s > 0 else "—",
                "Depth (m)": round(p["depth_m"], 2),
            })
        st.dataframe(pd.DataFrame(_pc_rows), width='stretch', hide_index=True)

    _start_col, _btn_col = st.columns([4, 1])
    with _start_col:
        st.markdown(
            """
            <div style="
                background: #1e3a5f;
                border-left: 6px solid #4fa3e0;
                border-radius: 6px;
                padding: 8px 16px;
                height: 100%;
                display: flex;
                align-items: center;
            ">
                <span style="color:#8ec8f6; font-size:0.9rem; font-weight:600;">
                    Ready — press ▶️ to start T=0
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with _btn_col:
        if st.button("▶️ Start", type="primary", key="btn_start_cast", width='stretch'):
            st.session_state.cast_active = True
            _now = _time.time()
            st.session_state.cast_t0_wall = _now
            st.session_state.cast_phase_start_wall = _now
            st.session_state.live_t2_depths = list(t2_depths)
            st.session_state.cast_phase_idx = 0
            st.session_state.cast_actual_trace = [(0.0, 0.0, "T=0 — cast started")]
            st.rerun()

else:
    # Auto-refresh every 2 seconds while cast is active
    if _HAS_AUTOREFRESH and _st_autorefresh is not None:
        _st_autorefresh(interval=2000, key="cast_clock")
    else:
        _components.html(
            "<script>setTimeout(()=>window.parent.location.href=window.parent.location.href,2000)</script>",
            height=0,
        )

    # ------------------------------------------------------------------
    # 1 — Control buttons
    # ------------------------------------------------------------------
    # We need the phase list early to label the button — build it from planned depths first;
    # it will be rebuilt with live T2 depths below, but the label is good enough here.
    _phases_early = _build_phases(filter_stops, _bottom_arrive_s, _bottom_leave_s,
                                  _recovered_evt, surface_return_s=_surface_return_s,
                                  deploy_delay_s=deploy_delay_s)
    _pidx_early = min(st.session_state.cast_phase_idx, len(_phases_early) - 1)
    _cur_phase_early = _phases_early[_pidx_early]
    _is_last_phase = _pidx_early >= len(_phases_early) - 1

    _next_label = _phases_early[_pidx_early + 1]["label"] if not _is_last_phase else ""

    def _advance_current_phase() -> None:
        _elapsed_now = _time.time() - (st.session_state.cast_t0_wall or _time.time())
        _live_t2_now = list(st.session_state.live_t2_depths)
        _planned_depth = _cur_phase_early["depth_m"]
        for _ti, _td in enumerate(t2_depths):
            if abs(_planned_depth - _td) < 0.5 and _ti < len(_live_t2_now):
                _planned_depth = _live_t2_now[_ti]
                break
        st.session_state.cast_actual_trace.append(
            (_elapsed_now, _planned_depth, _cur_phase_early["label"])
        )
        if not _is_last_phase:
            st.session_state.cast_phase_idx += 1
            st.session_state.cast_phase_start_wall = _time.time()
        else:
            st.session_state.cast_active = False

    _bc1, _bc2, _bc3 = st.columns([1, 1, 1])
    with _bc1:
        if st.button("⏹️ Stop", key="btn_stop_cast", help="Stop cast tracker"):
            st.session_state.cast_active = False
            st.session_state.cast_t0_wall = None
            st.rerun()
    with _bc2:
        if st.button("🔄 Refresh", key="btn_refresh"):
            st.rerun()
    with _bc3:
        _prev_disabled = st.session_state.cast_phase_idx == 0
        if st.button("↩️ Undo", key="btn_prev_phase",
                     disabled=_prev_disabled, help="Mark the current phase as not yet reached"):
            st.session_state.cast_phase_idx -= 1
            st.session_state.cast_phase_start_wall = _time.time()
            if len(st.session_state.cast_actual_trace) > 1:
                st.session_state.cast_actual_trace.pop()
            st.rerun()

    # ------------------------------------------------------------------
    # 2 — T2 depth corrections (compact, always visible)
    # ------------------------------------------------------------------
    if t2_stops:
        with st.expander("✏️ Correct T2 depths from downcast profile", expanded=False):
            st.caption("Update when you know the actual feature depths from the downcast CTD profile.")
            while len(st.session_state.live_t2_depths) < len(t2_stops):
                _i = len(st.session_state.live_t2_depths)
                st.session_state.live_t2_depths.append(t2_depths[_i] if _i < len(t2_depths) else 1.0)
            _t2d_cols = st.columns(min(len(t2_stops), 5))
            for _i, _fs in enumerate(t2_stops):
                with _t2d_cols[_i % min(len(t2_stops), 5)]:
                    _new_d = st.number_input(
                        f"{_fs.filter_id}",
                        min_value=1.0, max_value=float(max_depth),
                        value=float(st.session_state.live_t2_depths[_i]),
                        step=1.0, format="%.0f",
                        key=f"live_t2d_{_i}",
                        help=f"Planned: {_fs.depth_m:.0f} m",
                    )
                    st.session_state.live_t2_depths[_i] = _new_d

    # ------------------------------------------------------------------
    # 3 — Recompute with live T2 depths
    # ------------------------------------------------------------------
    _live_t2 = list(st.session_state.live_t2_depths)[:len(t2_depths)] or t2_depths
    try:
        _lparams = CastParams(
            max_depth_m=float(max_depth),
            type1_depths=t1_depths,
            type2_depths=_live_t2,
            v_max=v_max, accel=accel,
            filter_duration_s=900.0,
            safety_margin_s=300.0,
            type1_filter_durations=t1_durations_s,
            type2_filter_durations=t2_durations_s,
            type1_safety_margins=t1_margins_s,
            type2_safety_margins=t2_margins_s,
            deploy_delay_s=float(deploy_delay_s),
            bottom_dwell_s=float(bottom_dwell_s),
            homing_time_s=float(homing_time_s),
            actuation_buffer_s=float(actuation_buffer_s),
        )
        _live_stops, _live_tl, _live_total = compute_delays(_lparams)
    except Exception as _le:
        st.warning(f"Recompute failed: {_le}")
        _live_tl = timeline

    _live_t2_stops = [f for f in _live_stops if f.filter_type == 2]

    # Apply actual programmed presets (operator overrides) to all live stops.
    for _fs in _live_stops:
        _override = st.session_state.actual_presets.get(_fs.filter_id)
        if _override is not None and abs(_override - _fs.preset_delay_s) > 1:
            _dwell = _fs.departure_time_s - _fs.preset_delay_s  # homing + buffer + filter_dur
            _fs.preset_delay_s   = _override
            _fs.departure_time_s = _override + _dwell

    # Propagate departure times for T2 (upcast) stops only, chaining from bottom leave.
    # T1 stops are completed before the bottom and must not be re-sequenced here.
    _live_bl_evt = next((e for e in _live_tl if e.event_type == "bottom_leave"), None)
    _live_bl_s   = _live_bl_evt.time_s if _live_bl_evt else (_bottom_arrive_s or 0.0)
    _prev_dep       = _live_bl_s
    _prev_dep_depth = float(max_depth)
    for _fs in sorted([f for f in _live_stops if f.filter_type == 2], key=lambda f: f.arrival_time_s):
        _travel = _tt(abs(_prev_dep_depth - _fs.depth_m), params.v_max, params.accel)
        _new_arrival = _prev_dep + _travel
        if abs(_new_arrival - _fs.arrival_time_s) > 0.5:
            _fs.arrival_time_s = _new_arrival
        # Defensive clamp: preset cannot be before arrival
        if _fs.preset_delay_s < _fs.arrival_time_s:
            _dwell = _fs.departure_time_s - _fs.preset_delay_s
            _fs.preset_delay_s   = _fs.arrival_time_s
            _fs.departure_time_s = _fs.preset_delay_s + _dwell
        _prev_dep       = _fs.departure_time_s
        _prev_dep_depth = _fs.depth_m

    # Keep the Recovered event in _live_tl consistent with the propagated T2 departures.
    _live_t2_sorted = sorted([f for f in _live_stops if f.filter_type == 2], key=lambda f: f.departure_time_s)
    if _live_t2_sorted:
        _last_t2_fs = _live_t2_sorted[-1]
        _surf_travel = _tt(_last_t2_fs.depth_m, params.v_max, params.accel)
        for _evt in _live_tl:
            if _evt.label == "Recovered":
                _evt.time_s = _last_t2_fs.departure_time_s + _surf_travel
                break

    _live_surface_evt    = None  # surface stop removed
    _live_recovered_evt  = next((e for e in _live_tl if e.label == "Recovered"), None)
    _live_surface_return = next((e for e in _live_tl if e.event_type == "surface_return"), None)
    _live_surface_return_s = _live_surface_return.time_s if _live_surface_return else None
    _live_bottom_leave_evt = next((e for e in _live_tl if e.event_type == "bottom_leave"), None)
    _live_bottom_leave_s = _live_bottom_leave_evt.time_s if _live_bottom_leave_evt else _bottom_arrive_s

    # Rebuild phases with live T2 depths
    _phases = _build_phases(_live_stops, _bottom_arrive_s, _live_bottom_leave_s,
                            _live_recovered_evt,
                            surface_return_s=_live_surface_return_s,
                            deploy_delay_s=deploy_delay_s)

    # Clamp phase index in case filter count changed
    st.session_state.cast_phase_idx = min(st.session_state.cast_phase_idx, len(_phases) - 1)
    _pidx = st.session_state.cast_phase_idx
    _cur_phase = _phases[_pidx]
    _next_phase = _phases[_pidx + 1] if _pidx + 1 < len(_phases) else None

    # ------------------------------------------------------------------
    # Helper: compute 4-color T2 status + required ascent speed
    # ------------------------------------------------------------------
    _V_HARD_MAX = v_hard_max   # from advanced settings

    def _t2_status(fs, elapsed_s, from_depth):
        """
        Returns (icon, color_hex, required_ascent_speed, route_note, dist, ttp_travel, t_at_V, t_at_hard)
        Colors: 🟢 on time at V  🟡 need >V but possible  🔴 impossible  ⚫ timer already fired
        Descent leg is always at V (protocol). Only the ascent leg speed is variable.
        """
        _scheduled  = fs.preset_delay_s
        _ttp        = _scheduled - elapsed_s
        _pre_bot    = (_bottom_arrive_s is not None and elapsed_s < _bottom_arrive_s)

        # Timer already fired → station compromised
        if _ttp <= 0:
            return "⚫", "#212529", params.v_max, "—", 0, 0, elapsed_s, elapsed_s

        if _pre_bot:
            _d_down     = float(max_depth) - from_depth
            _d_up       = float(max_depth) - fs.depth_m
            _route_note = f"↓{_d_down:.0f}m + ↑{_d_up:.0f}m (via bottom)"
            # Descent at V (protocol); ascent speed is variable
            _t_fixed       = _tt(_d_down, params.v_max, params.accel)
            _t_ascent_V    = _tt(_d_up, params.v_max, params.accel)
            _t_at_V        = elapsed_s + _t_fixed + _t_ascent_V
            _t_at_hard     = elapsed_s + _t_fixed + _tt(_d_up, _V_HARD_MAX, params.accel)
            _ttp_travel    = _ttp - _t_fixed
            _dist          = _d_up
        else:
            # At bottom or already ascending — only ascent leg remains
            _dist       = abs(from_depth - fs.depth_m)
            _route_note = f"↑{_dist:.0f}m"
            _t_at_V    = elapsed_s + _tt(_dist, params.v_max, params.accel)
            _t_at_hard = elapsed_s + _tt(_dist, _V_HARD_MAX, params.accel)
            _ttp_travel = _ttp

        # At target depth already — just waiting
        if _dist < 0.5:
            return "🔔", "#28a745", params.v_max, _route_note, _dist, _ttp_travel, _t_at_V, _t_at_hard

        # Compute required speed and use it directly for color
        if _ttp_travel > 0 and _dist > 0:
            _res = _rspeed(_dist, _ttp_travel, params.accel)
            if _res["status"] == "impossible":
                _req = _V_HARD_MAX * 2  # flag as impossible
            else:
                _req = _res["v_required"]
        elif _dist <= 0:
            _req = 0.0
        else:
            _req = _V_HARD_MAX * 2  # no time left → impossible

        _req = max(0.01, _req)

        # 4-color scheme: compare required speed to thresholds
        if _req <= params.v_max:
            _icon, _color = "🟢", "#28a745"
        elif _req <= _V_HARD_MAX:
            _icon, _color = "🟡", "#f0ad4e"
        else:
            _icon, _color = "🔴", "#dc3545"

        _req = min(_req, _V_HARD_MAX)  # cap display value at hard max

        return _icon, _color, _req, _route_note, _dist, _ttp_travel, _t_at_V, _t_at_hard

    def _t1_status(fs, elapsed_s, from_depth):
        """
        Returns (icon, color_hex, required_descent_speed, route_note, dist, ttp_travel, t_at_V, t_at_hard)
        for a downcast (T1/D) station.
        Colors: 🟢 reachable at V  🟡 need >V but possible  🔴 impossible  ⚫ timer already fired
        """
        _ttp = fs.preset_delay_s - elapsed_s
        if _ttp <= 0:
            return "⚫", "#212529", params.v_max, "—", 0, 0, elapsed_s, elapsed_s

        _dist = max(fs.depth_m - from_depth, 0.0)
        _route_note = f"↓{_dist:.0f}m"

        if _dist < 0.5:
            return "🔔", "#28a745", params.v_max, _route_note, _dist, _ttp, elapsed_s + _ttp, elapsed_s + _ttp

        _t_at_V    = elapsed_s + _tt(_dist, params.v_max, params.accel)
        _t_at_hard = elapsed_s + _tt(_dist, _V_HARD_MAX, params.accel)

        _res = _rspeed(_dist, _ttp, params.accel)
        if _res["status"] == "impossible":
            _req = _V_HARD_MAX * 2
        else:
            _req = _res["v_required"]
        _req = max(0.01, _req)

        if _req <= params.v_max:
            _icon, _color = "🟢", "#28a745"
        elif _req <= _V_HARD_MAX:
            _icon, _color = "🟡", "#f0ad4e"
        else:
            _icon, _color = "🔴", "#dc3545"

        _req = min(_req, _V_HARD_MAX)
        return _icon, _color, _req, _route_note, _dist, _ttp, _t_at_V, _t_at_hard

    _cast_elapsed_s  = _time.time() - (st.session_state.cast_t0_wall or _time.time())

    # Phase boundaries
    _phase_from  = _cur_phase["from_depth_m"]
    _phase_to    = _cur_phase["depth_m"]
    _is_travel   = abs(_phase_to - _phase_from) > 0.5
    _is_descent  = _phase_to > _phase_from

    # Step 1: Compute current depth using v_max as speed estimate
    if _is_travel:
        _travel_dist = abs(_phase_to - _phase_from)
        _phase_start_wall: float = st.session_state.cast_phase_start_wall or st.session_state.cast_t0_wall or _time.time()
        _elapsed_in_phase = max(0.0, _time.time() - _phase_start_wall)
        _travel_total_vmax = _tt(_travel_dist, params.v_max, params.accel)
        _frac = min(_elapsed_in_phase / _travel_total_vmax, 1.0) if _travel_total_vmax > 0 else 1.0
        _cast_depth      = _phase_from + _frac * (_phase_to - _phase_from)
        _cast_from_depth = _cast_depth
    else:
        _cast_depth      = _phase_to
        _cast_from_depth = _phase_from

    # Step 2: station status — T1 (downcast) when pre-bottom, T2 (upcast) when post-bottom
    _live_t1_stops = sorted([f for f in _live_stops if f.filter_type == 1],
                             key=lambda f: f.preset_delay_s)
    _t2_by_ascent  = sorted(_live_t2_stops, key=lambda f: -f.depth_m)  # deepest first

    # If the last T2 filter has already completed its full run, no more time constraint.
    _last_t2_dep = _t2_by_ascent[-1].departure_time_s if _t2_by_ascent else None
    _all_filters_done = (_last_t2_dep is not None and _cast_elapsed_s >= _last_t2_dep)

    _is_post_bottom = (_bottom_arrive_s is not None and _cast_elapsed_s >= _bottom_arrive_s)

    # Next pending D station (T1 — pre-bottom)
    _next_t1 = next(
        (fs for fs in _live_t1_stops if _cast_elapsed_s < fs.preset_delay_s), None
    )

    # Next pending U station (T2 — existing logic)
    _next_t2 = None
    if not _all_filters_done:
        if _is_post_bottom:
            _next_t2 = next(
                (fs for fs in _t2_by_ascent
                 if _cast_from_depth >= fs.depth_m and _cast_elapsed_s < fs.preset_delay_s),
                None
            )
        else:
            _next_t2 = _t2_by_ascent[0] if _t2_by_ascent else None

    # Choose which station drives the dot marker color
    if not _is_post_bottom and _next_t1 is not None:
        _act_icon, _dot_marker_color, _act_req_spd, *_ = _t1_status(
            _next_t1, _cast_elapsed_s, _cast_from_depth)
        _active_station = _next_t1
    elif _next_t2 is not None:
        _act_icon, _dot_marker_color, _act_req_spd, *_ = _t2_status(
            _next_t2, _cast_elapsed_s, _cast_from_depth)
        _active_station = _next_t2
    else:
        _act_icon, _dot_marker_color, _act_req_spd = "✅", "#28a745", params.v_max
        _active_station = None

    # Step 3: Auto-record trace point every refresh (~2 s resolution)
    _trace = st.session_state.cast_actual_trace
    if not _trace or abs(_trace[-1][0] - _cast_elapsed_s) >= 1.9:
        _trace.append((_cast_elapsed_s, _cast_depth, ""))

    # Step 4: Filtering-phase timing (absolute instrument preset, not phase-start-relative)
    _is_filter_phase = "Filtering at" in _cur_phase["label"]
    _cur_filter_stop = None
    _filter_fires_in = None   # signed: positive = not fired yet, negative = already firing
    _filter_ends_in  = None   # signed: time until departure_time_s
    _arrival_offset  = None   # signed: negative = arrived early, positive = arrived late
    if _is_filter_phase:
        _cur_filter_stop = next(
            (fs for fs in _live_stops
             if abs(fs.preset_delay_s - _cur_phase["time_s"]) < 1.0),
            None,
        )
        if _cur_filter_stop is not None:
            _filter_fires_in = _cur_filter_stop.preset_delay_s - _cast_elapsed_s
            _filter_ends_in  = _cur_filter_stop.departure_time_s - _cast_elapsed_s
            if st.session_state.cast_phase_start_wall and st.session_state.cast_t0_wall:
                _entry_elapsed  = st.session_state.cast_phase_start_wall - st.session_state.cast_t0_wall
                _arrival_offset = _entry_elapsed - _cur_filter_stop.preset_delay_s


    # ---------------------------------------------------------------------------
    # Sticky info bar — fixed at top of viewport, always visible while scrolling
    # ---------------------------------------------------------------------------
    _sb_cast = fmt_time(_cast_elapsed_s)
    _sb_next = fmt_time(max(_next_phase["time_s"] - _cast_elapsed_s, 0)) if _next_phase else "—"
    _sb_next_label = "🔬 Sampling ends in" if _is_filter_phase else "⏳ Next"

    # Next filter to fire — any filter (T1 or T2) whose preset hasn't fired yet
    _all_next_filters = sorted(
        [f for f in _live_stops if f.preset_delay_s > _cast_elapsed_s],
        key=lambda f: f.preset_delay_s,
    )
    _next_any_filter = _all_next_filters[0] if _all_next_filters else None
    if _next_any_filter is not None:
        _ttp_any = max(_next_any_filter.preset_delay_s - _cast_elapsed_s, 0)
        _sb_filt = f"{_next_any_filter.filter_id} starts in: <b>{fmt_time(_ttp_any)}</b>"
    else:
        _sb_filt = "All filters complete ✅"

    st.markdown(
        f"""
        <style>
            section[data-testid="stMain"] .block-container {{
                padding-top: 4.5rem;
            }}
            .__cast_sticky {{ left: 0; transition: left 0.3s ease; }}
            html:has([data-testid="stSidebar"][aria-expanded="true"]) .__cast_sticky {{
                left: 21rem;
            }}
        </style>
        <div class="__cast_sticky" style="
            position: fixed;
            top: 56px;
            right: 0;
            z-index: 9999;
            background: #0d1b2a;
            border-bottom: 2px solid #4fa3e0;
            padding: 6px 24px;
            display: flex;
            align-items: center;
            gap: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.5);
        ">
            <span style="color:#ffffff; font-size:0.95rem; font-weight:700; flex:1 1 auto; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                Phase {_pidx + 1}/{len(_phases)}&nbsp;&nbsp;{_cur_phase['label']}
            </span>
            <span style="color:#8ec8f6; font-size:0.85rem; white-space:nowrap;">
                ⏱️ T+&nbsp;<b>{_sb_cast}</b>
            </span>
            <span style="color:#8ec8f6; font-size:0.85rem; white-space:nowrap;">
                {_sb_next_label}:&nbsp;<b>{_sb_next}</b>
            </span>
            <span style="color:#8ec8f6; font-size:0.85rem; white-space:nowrap;">
                🎣 {_sb_filt}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


    _step_parts = []
    for _si, _sp in enumerate(_phases):
        if _si < _pidx:
            _style = "color:#555; text-decoration:line-through; font-size:0.78rem;"
            _bullet = "✓"
        elif _si == _pidx:
            _style = "color:#4fa3e0; font-weight:700; font-size:0.85rem; background:#0d2137; padding:2px 6px; border-radius:4px;"
            _bullet = "●"
        else:
            _style = "color:#888; font-size:0.78rem;"
            _bullet = "○"
        _step_parts.append(f'<span style="{_style}">{_bullet} {_sp["label"]}</span>')
    st.markdown(
        '<div style="line-height:2; word-spacing:4px;">' + " &nbsp;›&nbsp; ".join(_step_parts) + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    # Key metric — recovery time only (cast time / next phase / filter countdown are in the sticky bar)
    _m_recovery, = st.columns([1])
    _m_recovery.metric("🏁 Time to recovery", fmt_time(max(_live_total - _cast_elapsed_s, 0)))

    # ---------------------------------------------------------------------------
    # Main status banner — driven by the next reachable sampling station.
    # Pre-bottom: tracks next D (T1) station; post-bottom: tracks next U (T2) station.
    # ---------------------------------------------------------------------------
    if _active_station is None:
        _banner_color = "#28a745"
        _banner_text  = "✅ All filters complete — recovering"
    elif _act_icon == "🔔":
        _banner_color = "#28a745"
        _banner_text  = (f"🔔 At {_active_station.filter_id} ({_active_station.depth_m:.0f} m) — "
                         f"starts in {fmt_time(max(_active_station.preset_delay_s - _cast_elapsed_s, 0))}")
    elif _act_icon == "⚫":
        _banner_color = "#212529"
        _banner_text  = f"⚫ {_active_station.filter_id} — timer already fired (station missed)"
    elif _act_icon == "🟢" and _act_req_spd < params.v_max * 0.99:
        _banner_color = "#28a745"
        _banner_text  = (f"🟢 {_active_station.filter_id} reachable — min speed: "
                         f"{_act_req_spd:.2f} m/s  (CTD speed: {params.v_max:.2f} m/s)")
    elif _act_icon == "🟢":
        _banner_color = "#28a745"
        _banner_text  = f"🟢 {_active_station.filter_id} reachable at CTD speed ({params.v_max:.2f} m/s)"
    elif _act_icon == "🟡":
        _banner_color = "#f0ad4e"
        _banner_text  = (f"🟡 {_active_station.filter_id} tight — need {_act_req_spd:.2f} m/s "
                         f"(CTD: {params.v_max:.2f} m/s, winch max: {v_hard_max:.2f} m/s)")
    else:  # 🔴
        _banner_color = "#dc3545"
        _banner_text  = (f"🔴 {_active_station.filter_id} unreachable — even winch max "
                         f"({v_hard_max:.2f} m/s) is not enough")

    st.markdown(
        f'<div style="background:#111d2b; border-left:6px solid {_banner_color}; '
        f'border-radius:6px; padding:8px 18px; margin:4px 0 10px 0; font-size:1.05rem; '
        f'color:{_banner_color}; font-weight:700;">{_banner_text}</div>',
        unsafe_allow_html=True,
    )

    # Filtering-phase detail card — only shown when in a filtering phase
    if _is_filter_phase and _cur_filter_stop is not None:
        _filt_dur_s = _cur_filter_stop.departure_time_s - _cur_filter_stop.preset_delay_s
        # Fire countdown: signed — positive = waiting to fire, negative = already firing
        if _filter_fires_in is not None and _filter_fires_in > 0:
            _fire_txt   = f"⏳ Fires in <b>{fmt_time(_filter_fires_in)}</b>"
            _fire_color = "#4fa3e0"
        elif _filter_fires_in is not None:
            _fire_txt   = f"🔬 Sampling — started <b>{fmt_time(-_filter_fires_in)}</b> ago"
            _fire_color = "#28a745"
        else:
            _fire_txt, _fire_color = "—", "#8ec8f6"
        # Filter end countdown
        if _filter_ends_in is not None and _filter_ends_in > 0:
            _fend_txt = f"Ends in <b>{fmt_time(_filter_ends_in)}</b>"
        elif _filter_ends_in is not None:
            _fend_txt = "✅ Sampling complete"
        else:
            _fend_txt = "—"
        # Arrival offset: how early/late the operator entered this phase vs. preset fire time
        if _arrival_offset is not None:
            if abs(_arrival_offset) < 5:
                _arr_txt, _arr_color = "Arrived on time ✓", "#28a745"
            elif _arrival_offset < 0:
                _arr_txt  = f"🟢 Arrived <b>{fmt_time(-_arrival_offset)}</b> early"
                _arr_color = "#28a745"
            else:
                _arr_txt  = f"🔴 Arrived <b>{fmt_time(_arrival_offset)}</b> late"
                _arr_color = "#dc3545"
        else:
            _arr_txt, _arr_color = "—", "#8ec8f6"
        st.markdown(
            f'<div style="background:#0d1b2a; border:1.5px solid #4fa3e0; border-radius:8px; '
            f'padding:8px 20px; margin:6px 0 10px 0; display:flex; gap:28px; '
            f'align-items:center; flex-wrap:wrap;">'
            f'<span style="color:#8ec8f6; font-size:0.85rem; white-space:nowrap;">'
            f'🎣 <b>{_cur_filter_stop.filter_id}</b>'
            f'&nbsp;|&nbsp;Preset: <b>{fmt_time(_cur_filter_stop.preset_delay_s)}</b>'
            f'&nbsp;|&nbsp;Duration: <b>{fmt_time(_filt_dur_s)}</b></span>'
            f'<span style="color:{_fire_color}; font-size:0.85rem; white-space:nowrap;">{_fire_txt}</span>'
            f'<span style="color:#8ec8f6; font-size:0.85rem; white-space:nowrap;">{_fend_txt}</span>'
            f'<span style="color:{_arr_color}; font-size:0.85rem; white-space:nowrap;">{_arr_txt}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    _all_sampling_stops = sorted(
        _live_t1_stops + _live_t2_stops,
        key=lambda f: f.preset_delay_s,
    )
    if _all_sampling_stops:
        st.markdown("**⚡ Speed needed to reach each sampling station on time:**")
        _stn_rows = []
        for _fs in _all_sampling_stops:
            if _fs.filter_type == 1:
                _icon, _color, _req_spd, _route_note, _dist, _ttp_travel, _t_at_V, _t_at_hard = \
                    _t1_status(_fs, _cast_elapsed_s, _cast_from_depth)
            else:
                _icon, _color, _req_spd, _route_note, _dist, _ttp_travel, _t_at_V, _t_at_hard = \
                    _t2_status(_fs, _cast_elapsed_s, _cast_from_depth)
            _ttp = _fs.preset_delay_s - _cast_elapsed_s

            if _ttp <= 0:
                _v_str = "started"
                _arr_str = "—"
            elif _dist < 0.5:
                _v_str = "at depth"
                _arr_str = "—"
            else:
                _v_str  = f"{_icon} {_req_spd:.2f} m/s"
                _early  = _fs.preset_delay_s - _t_at_V
                _arr_str = f"+{fmt_time(_early)}" if _early >= 0 else f"−{fmt_time(-_early)}"

            _stn_rows.append({
                "": _icon,
                "Station": _fs.filter_id,
                "Type": "Downcast (D)" if _fs.filter_type == 1 else "Upcast (U)",
                "Depth (m)": f"{_fs.depth_m:.0f}",
                "Route": _route_note,
                "Min. speed": _v_str,
                "Arrival margin @ V": _arr_str,
                "Starts at (T+)": fmt_time(_fs.preset_delay_s),
                "Countdown": fmt_time(max(_ttp, 0)),
            })
        st.dataframe(pd.DataFrame(_stn_rows), width='stretch', hide_index=True)
    else:
        st.info("No sampling stations configured.")

# ---------------------------------------------------------------------------
# Depth-Time profile chart
# ---------------------------------------------------------------------------

st.subheader("📈 Cast Timeline")

fig = go.Figure()

# Waypoints for path — show full shape: travel → arrive → wait → filter → depart
waypoints = [(0.0, 0.0, "Deploy")]
if deploy_delay_s > 0:
    waypoints.append((deploy_delay_s, 0.0, "Water entry"))
for fs in [f for f in filter_stops if f.filter_type == 1]:
    waypoints.append((fs.arrival_time_s, fs.depth_m, f"{fs.filter_id} arrive"))
    waypoints.append((fs.preset_delay_s, fs.depth_m, f"{fs.filter_id} filtering"))
    waypoints.append((fs.departure_time_s, fs.depth_m, f"{fs.filter_id} end"))
if _surface_return_s is not None:
    waypoints.append((_surface_return_s, 0.0, "Surface return"))
bottom_event = next((e for e in timeline if e.event_type == "bottom"), None)
bottom_leave_event = next((e for e in timeline if e.event_type == "bottom_leave"), None)
if bottom_event:
    waypoints.append((bottom_event.time_s, bottom_event.depth_m, "Bottom arrive"))
if bottom_leave_event:
    waypoints.append((bottom_leave_event.time_s, bottom_leave_event.depth_m, "Bottom leave"))
for fs in _live_t2_stops:
    waypoints.append((fs.arrival_time_s, fs.depth_m, f"{fs.filter_id} arrive"))
    waypoints.append((fs.preset_delay_s, fs.depth_m, f"{fs.filter_id} filtering"))
    waypoints.append((fs.departure_time_s, fs.depth_m, f"{fs.filter_id} end"))
_g_recovered = next((e for e in (_live_tl if st.session_state.cast_active else timeline)
                     if e.label == "Recovered"), None)
if _g_recovered:
    waypoints.append((_g_recovered.time_s, 0.0, "Recovered"))
waypoints.sort(key=lambda x: x[0])

# Custom x-axis ticks: every 5 min (300 s), formatted as HH:MM:SS
_x_max = max((w[0] for w in waypoints), default=600) * 1.05
_tick_step = 300  # 5 minutes
_tickvals = list(range(0, int(_x_max) + _tick_step, _tick_step))
_ticktext = [fmt_time(t) for t in _tickvals]

fig.add_trace(go.Scatter(
    x=[w[0] for w in waypoints],
    y=[w[1] for w in waypoints],
    mode="lines",
    line=dict(color="#1f77b4", width=2),
    name="CTD path",
    customdata=[[fmt_time(w[0]), w[2]] for w in waypoints],
    hovertemplate="%{customdata[1]}<br>%{y:.1f} m @ %{customdata[0]}<extra></extra>",
))

if t1_stops:
    fig.add_trace(go.Scatter(
        x=[f.preset_delay_s for f in t1_stops],
        y=[f.depth_m for f in t1_stops],
        mode="markers+text",
        marker=dict(color="green", size=12, symbol="triangle-down"),
        text=[f.filter_id for f in t1_stops],
        textposition="middle right",
        name="Downcast filters",
        customdata=[[fmt_time(f.preset_delay_s), fmt_time(f.departure_time_s)] for f in t1_stops],
        hovertemplate="<b>%{text}</b><br>Depth: %{y} m<br>Fires: %{customdata[0]}<br>Ends: %{customdata[1]}<extra></extra>",
    ))

if _live_t2_stops:
    fig.add_trace(go.Scatter(
        x=[f.preset_delay_s for f in _live_t2_stops],
        y=[f.depth_m for f in _live_t2_stops],
        mode="markers+text",
        marker=dict(color="darkorange", size=12, symbol="triangle-up"),
        text=[f.filter_id for f in _live_t2_stops],
        textposition="middle right",
        name="Upcast filters",
        customdata=[[fmt_time(f.preset_delay_s), fmt_time(f.departure_time_s)] for f in _live_t2_stops],
        hovertemplate="<b>%{text}</b><br>Depth: %{y} m<br>Fires: %{customdata[0]}<br>Ends: %{customdata[1]}<extra></extra>",
    ))

# Actual trace + current position marker (only when cast active or trace exists)
_actual = st.session_state.cast_actual_trace
if _actual:
    fig.add_trace(go.Scatter(
        x=[p[0] for p in _actual],
        y=[p[1] for p in _actual],
        mode="lines",
        line=dict(color="#888888", width=2, dash="solid"),
        name="Actual path",
        hoverinfo="skip",
    ))
    _milestones = [(p[0], p[1], p[2]) for p in _actual if p[2]]
    if _milestones:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in _milestones],
            y=[p[1] for p in _milestones],
            mode="markers",
            marker=dict(color="#888888", size=8, symbol="diamond",
                        line=dict(color="#555555", width=2)),
            name="Phase checkpoints",
            customdata=[[p[2], fmt_time(p[0])] for p in _milestones],
            hovertemplate="<b>%{customdata[0]}</b><br>%{y:.0f} m @ %{customdata[1]}<extra></extra>",
        ))

# Current position — colored dot
if st.session_state.cast_active:
    _marker_border = {"#28a745": "#145a32", "#f0ad4e": "#7d5a00", "#dc3545": "#7b1a24"}.get(_dot_marker_color, "#333")
    fig.add_trace(go.Scatter(
        x=[_cast_elapsed_s],
        y=[_cast_depth],
        mode="markers",
        marker=dict(color=_dot_marker_color, size=18, symbol="circle",
                    line=dict(color=_marker_border, width=3)),
        name="📍 Now",
        hovertemplate=(
            f"<b>{_phases[st.session_state.cast_phase_idx]['label']}</b><br>"
            f"T+: {fmt_time(_cast_elapsed_s)}<extra></extra>"
        ),
    ))

fig.update_layout(
    xaxis_title="Time from T=0",
    xaxis=dict(tickvals=_tickvals, ticktext=_ticktext, tickangle=-45),
    yaxis_title="Depth (m)",
    yaxis=dict(autorange="reversed"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    height=500,
    margin=dict(t=60, b=60),
    hovermode="closest",
    uirevision="cast_plot",
)

if st.session_state.cast_active:
    _np_label = "➡️ Next phase" if not _is_last_phase else "🏁 Complete"
    _np_help = f"Next: {_next_label}" if _next_label else None
    _np_left, _np_right = st.columns([4, 1])
    with _np_right:
        if st.button(_np_label, key="btn_next_phase", type="primary", width='stretch', help=_np_help):
            _advance_current_phase()
            st.rerun()

st.plotly_chart(fig, width='stretch')

# ---------------------------------------------------------------------------
# Detailed timeline breakdown
# ---------------------------------------------------------------------------
with st.expander("🔍 Detailed cast timeline"):
    detail_rows = []
    for _pi, p in enumerate(_phases):
        _next_t = _phases[_pi + 1]["time_s"] if _pi + 1 < len(_phases) else total_time_s
        _dur_s = _next_t - p["time_s"]
        detail_rows.append({
            "Phase": p["label"],
            "Scheduled at": fmt_time(p["time_s"]),
            "Duration": fmt_time(_dur_s) if _dur_s > 0 else "—",
            "Depth (m)": round(p["depth_m"], 2),
        })
    st.dataframe(pd.DataFrame(detail_rows), width='stretch', hide_index=True)

# ---------------------------------------------------------------------------
# CSV download — phase timetable + travel segment average speeds
# ---------------------------------------------------------------------------
st.markdown("---")
if st.session_state.cast_active or st.session_state.cast_actual_trace:
    def _strip_emoji(text):
        return _re.sub(r'[^\x00-\x7F]+', '', text).strip()

    def _build_csv():
        _trace_milestones = [(p[0], p[1], p[2]) for p in st.session_state.cast_actual_trace if p[2]]
        _csv_rows = []
        for _pi, _ph in enumerate(_phases):
            _planned_start = fmt_time(_ph["time_s"])
            _planned_depth = f"{_ph['depth_m']:.1f}"
            _actual_start = _trace_milestones[_pi][0] if _pi < len(_trace_milestones) else None
            _actual_start_fmt = fmt_time(_actual_start) if _actual_start is not None else "—"
            _is_t = abs(_ph["depth_m"] - _ph["from_depth_m"]) > 0.5
            if _is_t and _pi < len(_trace_milestones) and _pi > 0:
                _t_start = _trace_milestones[_pi - 1][0]
                _t_end   = _trace_milestones[_pi][0]
                _dist    = abs(_ph["depth_m"] - _ph["from_depth_m"])
                _dur     = _t_end - _t_start
                _avg_spd = f"{_dist / _dur:.3f} m/s" if _dur > 0 else "—"
            else:
                _avg_spd = "—"
            _csv_rows.append({
                "Phase": _strip_emoji(_ph["label"]),
                "Planned start (T+)": _planned_start,
                "Planned depth (m)": _planned_depth,
                "Actual start (T+)": _actual_start_fmt,
                "Avg travel speed (m/s)": _avg_spd,
            })
        return pd.DataFrame(_csv_rows).to_csv(index=False)

    # Cache the CSV so the download button link stays stable across auto-refresh reruns.
    # Only rebuild when the cast is stopped (active→False) or a new milestone is recorded.
    _csv_cache_key = "csv_cache"
    _csv_fname_key = "csv_filename"
    _csv_milestone_count = len([p for p in st.session_state.cast_actual_trace if p[2]])
    _csv_needs_rebuild = (
        st.session_state.get("csv_milestone_count") != _csv_milestone_count
        or not st.session_state.get(_csv_cache_key)
    )
    if _csv_needs_rebuild:
        st.session_state[_csv_cache_key] = _build_csv()
        st.session_state["csv_milestone_count"] = _csv_milestone_count
        # Fix filename at rebuild time so it stays stable across auto-refreshes
        _utc_stamp = _datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        st.session_state[_csv_fname_key] = f"cast_timetable_{_utc_stamp}.csv"

    st.download_button(
        "📥 Download phase timetable (CSV)",
        data=st.session_state[_csv_cache_key],
        file_name=st.session_state.get(_csv_fname_key, "cast_timetable.csv"),
        mime="text/csv",
        key="csv_download_btn",
    )

