"""
CTD Filter Delay Calculator
============================
Calculates the preset timer delays for each filter actuation on a CTD cast.

Workflow:
  T=0: timers activated (CTD not yet in water)
  [initial margin] → downcast through Type 1 filter stops → bottom turn → upcast through Type 2 filter stops

Travel model: symmetric trapezoidal velocity profile (0 → v_max → 0) at every stop.
"""

import math
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Travel-time model
# ---------------------------------------------------------------------------

def travel_time(distance_m: float, v_max: float, accel: float) -> float:
    """
    Time to travel `distance_m` with symmetric acceleration/deceleration ramps.

    Trapezoidal profile:
      - If distance allows reaching v_max: ramp-up + cruise + ramp-down
      - Otherwise: triangular profile (never reaches v_max)

    Parameters
    ----------
    distance_m : float  Distance in metres (non-negative)
    v_max      : float  Maximum speed in m/s
    accel      : float  Acceleration / deceleration magnitude in m/s²

    Returns
    -------
    float  Travel time in seconds
    """
    if distance_m <= 0:
        return 0.0

    # Distance covered during one full ramp (0 → v_max or v_max → 0)
    ramp_dist = (v_max ** 2) / (2 * accel)
    full_ramp_dist = 2 * ramp_dist  # both ramps together

    if distance_m >= full_ramp_dist:
        # Trapezoidal: ramp up + cruise + ramp down
        ramp_time = v_max / accel          # time for one ramp
        cruise_dist = distance_m - full_ramp_dist
        cruise_time = cruise_dist / v_max
        return 2 * ramp_time + cruise_time
    else:
        # Triangular: v_peak = sqrt(a * d), t = 2 * v_peak / a
        v_peak = math.sqrt(accel * distance_m)
        return 2 * v_peak / accel


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FilterStop:
    """A single filter actuation stop."""
    filter_id: str
    filter_type: int          # 1 = downcast, 2 = upcast
    depth_m: float
    arrival_time_s: float     # exact cumulative time from T=0
    departure_time_s: float   # exact time CTD leaves this depth
    preset_delay_s: float     # = arrival_time_s + safety_margin (what you program into the device)
    filter_duration_s: float = 900.0  # timeout for THIS filter (excludes homing/buffer)


@dataclass
class CastEvent:
    """Any event in the cast timeline (for the chart)."""
    label: str
    time_s: float
    depth_m: float
    event_type: str  # 'filter_start', 'filter_end', 'bottom', 'surface', 'travel'


@dataclass
class CastParams:
    max_depth_m: float
    type1_depths: List[float]        # downcast filter depths, shallow→deep
    type2_depths: List[float]        # upcast filter depths, deep→shallow (expected/predicted)
    v_max: float = 1.0               # m/s
    accel: float = 0.1               # m/s²
    filter_duration_s: float = 900.0 # global default filter timeout (fallback)
    safety_margin_s: float = 300.0   # global default safety margin (fallback)
    n_bottles_bottom: int = 0
    n_bottles_dcm: int = 0
    n_bottles_surface: int = 0
    bottle_close_time_s: float = 5.0
    # Per-filter overrides (lists, one entry per filter in order). Empty = use global default.
    type1_filter_durations: List[float] = field(default_factory=list)
    type2_filter_durations: List[float] = field(default_factory=list)
    type1_safety_margins: List[float] = field(default_factory=list)
    type2_safety_margins: List[float] = field(default_factory=list)
    # New timing parameters (global)
    deploy_delay_s: float = 0.0       # T=0 to water entry (CTD on deck before descent)
    bottom_dwell_s: float = 5.0       # time spent at max depth before ascending
    homing_time_s: float = 30.0       # instrument spin-up after timer fires
    actuation_buffer_s: float = 10.0 # loading time after homing before actual pumping


# ---------------------------------------------------------------------------
# Core delay computation
# ---------------------------------------------------------------------------

def compute_delays(p: CastParams):
    """
    Compute preset delays for all filters and build the full cast timeline.

    Timing model per filter:
      - CTD arrives at depth           → arrival_time_s
      - After safety_margin_s, timer fires → preset_delay_s = arrival + margin
      - After timer fires: homing_time → activation_buffer → filter_duration (all sequential dwell)
      - CTD departs                    → departure_time_s = preset + homing + buffer + filter_dur

    Returns
    -------
    filter_stops : list[FilterStop]
    timeline     : list[CastEvent]   – all events for the depth-time chart
    total_cast_time_s : float
    """
    # Validate inputs
    if not p.type1_depths and not p.type2_depths:
        raise ValueError("At least one filter depth must be provided.")

    t1 = sorted(p.type1_depths)   # shallow → deep
    t2 = sorted(p.type2_depths, reverse=True)  # deep → shallow

    filter_stops: List[FilterStop] = []
    timeline: List[CastEvent] = []

    # Per-filter value helpers
    def _dur(filter_list, i):
        return filter_list[i] if i < len(filter_list) else p.filter_duration_s

    def _margin(margin_list, i):
        return margin_list[i] if i < len(margin_list) else p.safety_margin_s

    # Current position (depth) and time
    current_depth = 0.0
    current_time = p.deploy_delay_s  # start after deck delay

    timeline.append(CastEvent("Deploy", 0.0, 0.0, "surface"))
    if p.deploy_delay_s > 0:
        timeline.append(CastEvent("Water entry", p.deploy_delay_s, 0.0, "water_entry"))

    # ------------------------------------------------------------------
    # DOWNCAST: Downcast filter stops (D_flt) (shallow → deep)
    # ------------------------------------------------------------------
    for i, depth in enumerate(t1):
        seg_time = travel_time(abs(depth - current_depth), p.v_max, p.accel)
        current_time += seg_time
        current_depth = depth

        dur = _dur(p.type1_filter_durations, i)
        margin = _margin(p.type1_safety_margins, i)
        arrival = current_time
        preset = arrival + margin
        departure = preset + p.homing_time_s + p.actuation_buffer_s + dur

        fs = FilterStop(
            filter_id=f"D-{i+1}",
            filter_type=1,
            depth_m=depth,
            arrival_time_s=arrival,
            departure_time_s=departure,
            preset_delay_s=preset,
            filter_duration_s=dur,
        )
        filter_stops.append(fs)

        timeline.append(CastEvent(f"D-{i+1} start", arrival, depth, "filter_start"))
        timeline.append(CastEvent(f"D-{i+1} end", departure, depth, "filter_end"))

        current_time = departure

    # ------------------------------------------------------------------
    # After T1 filters: return to surface before main downcast
    # ------------------------------------------------------------------
    if t1:
        seg_time = travel_time(abs(current_depth - 0.0), p.v_max, p.accel)
        current_time += seg_time
        current_depth = 0.0
        timeline.append(CastEvent("Surface return", current_time, 0.0, "surface_return"))

    # ------------------------------------------------------------------
    # DOWNCAST: Continue to bottom
    # ------------------------------------------------------------------
    seg_time = travel_time(abs(p.max_depth_m - current_depth), p.v_max, p.accel)
    current_time += seg_time
    current_depth = p.max_depth_m

    bottom_arrive = current_time
    timeline.append(CastEvent("Bottom", bottom_arrive, p.max_depth_m, "bottom"))
    bottom_leave = bottom_arrive + p.bottom_dwell_s
    if p.bottom_dwell_s > 0:
        timeline.append(CastEvent("Bottom leave", bottom_leave, p.max_depth_m, "bottom_leave"))
    current_time = bottom_leave

    # ------------------------------------------------------------------
    # UPCAST: Upcast filter stops (U_flt) (deep → shallow)
    # ------------------------------------------------------------------
    for i, depth in enumerate(t2):
        seg_time = travel_time(abs(current_depth - depth), p.v_max, p.accel)
        current_time += seg_time
        current_depth = depth

        dur = _dur(p.type2_filter_durations, i)
        margin = _margin(p.type2_safety_margins, i)
        arrival = current_time
        preset = arrival + margin
        departure = preset + p.homing_time_s + p.actuation_buffer_s + dur

        fs = FilterStop(
            filter_id=f"U-{i+1}",
            filter_type=2,
            depth_m=depth,
            arrival_time_s=arrival,
            departure_time_s=departure,
            preset_delay_s=preset,
            filter_duration_s=dur,
        )
        filter_stops.append(fs)

        timeline.append(CastEvent(f"U-{i+1} start", arrival, depth, "filter_start"))
        timeline.append(CastEvent(f"U-{i+1} end", departure, depth, "filter_end"))

        current_time = departure

    # ------------------------------------------------------------------
    # UPCAST: Recover directly to deck
    # ------------------------------------------------------------------
    seg_time = travel_time(current_depth, p.v_max, p.accel)
    current_time += seg_time
    timeline.append(CastEvent("Recovered", current_time, 0.0, "surface"))

    total_cast_time_s = current_time

    return filter_stops, timeline, total_cast_time_s


def fmt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Live upcast speed solver
# ---------------------------------------------------------------------------

def required_speed(distance_m: float, time_avail_s: float, accel: float):
    """
    Given a distance to travel and the time available (until the preset timer fires),
    compute the winch speed needed to arrive exactly on time.

    Uses the trapezoidal ramp model: t = v/a + d/v  →  v² - a·t·v + a·d = 0
    Minimum possible time (triangular profile): t_min = 2·√(d/a)

    Parameters
    ----------
    distance_m   : float  Distance to travel (m, positive)
    time_avail_s : float  Time available (s)
    accel        : float  Acceleration magnitude (m/s²)

    Returns
    -------
    dict with keys:
        status       : 'impossible' | 'ok'
        v_required   : float | None   Required speed (m/s) to arrive exactly on time
        t_min_s      : float          Minimum possible travel time (physics limit)
        t_at_vmax    : float | None   Travel time at current v_max (for comparison)
        early_s      : float | None   How many seconds early you'd arrive at v_max
    """
    if distance_m <= 0:
        return {"status": "ok", "v_required": 0.0, "t_min_s": 0.0,
                "t_at_vmax": 0.0, "early_s": time_avail_s}

    t_min = 2.0 * math.sqrt(distance_m / accel)

    if time_avail_s < t_min:
        return {
            "status": "impossible",
            "v_required": None,
            "t_min_s": t_min,
            "t_at_vmax": None,
            "early_s": None,
        }

    # Solve v² - a·t·v + a·d = 0  (take the smaller positive root)
    discriminant = (accel * time_avail_s) ** 2 - 4 * accel * distance_m
    v_req = (accel * time_avail_s - math.sqrt(max(discriminant, 0.0))) / 2.0

    return {
        "status": "ok",
        "v_required": v_req,
        "t_min_s": t_min,
        "t_at_vmax": None,   # filled in by the caller who knows v_max
        "early_s": None,
    }
