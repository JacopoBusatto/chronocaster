import sys
sys.path.insert(0, r'c:\Users\Jacopo\Documents\GitHub\castingPrediction')
from calculator import CastParams, compute_delays, fmt_time

params = CastParams(
    max_depth_m=80.0,
    type1_depths=[5.0],
    type2_depths=[50.0],
    v_max=1.0,
    accel=0.1,
    filter_duration_s=900.0,
    safety_margin_s=300.0,
    homing_time_s=30.0,
    actuation_buffer_s=10.0,
    deploy_delay_s=0.0,
    bottom_dwell_s=5.0,
)
filter_stops, timeline, total = compute_delays(params)
for fs in filter_stops:
    print(f"{fs.filter_id} | depth={fs.depth_m}m | arrival={fmt_time(fs.arrival_time_s)} | preset={fmt_time(fs.preset_delay_s)} | ends={fmt_time(fs.departure_time_s)} | filter_dur={fs.filter_duration_s}s")
print(f"Total cast: {fmt_time(total)}")

# Verify new timing model: departure = preset + homing + buffer + filter_dur
for fs in filter_stops:
    expected_dep = fs.preset_delay_s + params.homing_time_s + params.actuation_buffer_s + fs.filter_duration_s
    assert abs(fs.departure_time_s - expected_dep) < 0.001, \
        f"{fs.filter_id}: departure {fs.departure_time_s} != {expected_dep}"
    assert abs(fs.preset_delay_s - (fs.arrival_time_s + params.safety_margin_s)) < 0.001, \
        f"{fs.filter_id}: preset {fs.preset_delay_s} != arrival+margin"
print("All assertions passed.")

# Test per-filter overrides
params2 = CastParams(
    max_depth_m=80.0,
    type1_depths=[5.0, 10.0],
    type2_depths=[50.0, 30.0],
    v_max=1.0,
    accel=0.1,
    filter_duration_s=900.0,   # global default
    safety_margin_s=300.0,     # global default
    type1_filter_durations=[600.0, 1200.0],   # per-filter overrides
    type2_filter_durations=[450.0],           # only first T2 overridden
    type1_safety_margins=[120.0],             # only first T1 overridden
    homing_time_s=30.0,
    actuation_buffer_s=10.0,
)
stops2, tl2, total2 = compute_delays(params2)
# T1-1: margin=120, duration=600
assert abs(stops2[0].preset_delay_s - stops2[0].arrival_time_s - 120.0) < 0.001
assert abs(stops2[0].filter_duration_s - 600.0) < 0.001
# T1-2: margin=300 (global default), duration=1200
assert abs(stops2[1].preset_delay_s - stops2[1].arrival_time_s - 300.0) < 0.001
assert abs(stops2[1].filter_duration_s - 1200.0) < 0.001
# T2-1: duration=450
t2_stops = [f for f in stops2 if f.filter_type == 2]
assert abs(t2_stops[0].filter_duration_s - 450.0) < 0.001
# T2-2: duration=900 (global default)
assert abs(t2_stops[1].filter_duration_s - 900.0) < 0.001
print("Per-filter override assertions passed.")

# Verify bottom_leave event
bottom_leave_evts = [e for e in tl2 if e.event_type == "bottom_leave"]
assert len(bottom_leave_evts) == 1, "Expected exactly one bottom_leave event"
print(f"Bottom leave event: {bottom_leave_evts[0]}")
print("All tests passed.")

