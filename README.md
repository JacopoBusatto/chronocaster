# 🌊 ChronoCaster

A Streamlit web app for determining the **preset values** needed to correctly trigger oceanographic instruments — such as the **SoloPuffer** — that actuate when specific conditions are met. ChronoCaster currently handles **time-delayed triggers**, computing the exact countdown preset for each actuation while accounting for filtering time, actuation and homing time, casting delays, and safety margins. It also provides a real-time cast tracker to follow operations as they happen.

---

## What it does

Instruments like the **SoloPuffer** are deployed on CTD casts and triggered via pre-programmed countdown timers started **before** the CTD enters the water (T=0). The preset must be set in advance and must account for all the time that elapses between T=0 and the moment the instrument should actuate:

- Deployment delay (time on deck from T=0 to water entry)
- Travel time to the target depth (trapezoidal velocity profile)
- Safety margin before the timer fires
- Instrument homing time after the timer fires
- Actuation buffer before sampling begins
- Sampling (filtering) duration

ChronoCaster handles all of this math and produces a per-instrument preset table plus an interactive depth–time chart. During the cast it also works as a **live operations tracker**, showing reachability status and required winch speeds for every upcoming sampling station in real time.

---

## Features

### Pre-cast planner
- Enter cast parameters and instantly see all preset delays in a table and on a depth–time plot
- Per-station overrides for duration and safety margin, independent of global defaults
- Configurable advanced timing: homing time, actuation buffer, bottom dwell, deployment delay
- CSV export of the full preset table

### Live cast tracker
Start the cast at T=0 and step through phases manually. The app shows:

- **Fixed status bar** — always visible; displays current phase, cast time (T+), time to next phase/filter end, and the next filter countdown
- **Reachability banner** — colour-coded 🟢/🟡/🔴/⚫ status for the next sampling station (D station pre-bottom, U station post-bottom), with the minimum required winch speed
- **Filtering phase info card** — while the instrument is sampling, shows:
  - Instrument preset fire time (absolute from T=0, instrument-anchored — does not shift if you arrive early or late)
  - Countdown to when the filter fires (goes negative if you arrived late — the device is already sampling)
  - Time until sampling ends
  - Arrival offset: how early or late you reached the target depth vs. the scheduled preset time
- **Sampling station speed table** — required winch speed for every D and U station, with route, arrival margin, and countdown
- **Depth–time plot** — planned CTD path, actual trace, phase checkpoints, and live position marker

---

## Installation

```bash
# Clone the repository
git clone https://github.com/JacopoBusatto/chronocaster.git
cd chronocaster

# (Recommended) create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Usage

```bash
streamlit run app.py
```

Then open the URL shown in the terminal (usually `http://localhost:8501`).

### Cast parameters (sidebar)

| Parameter | Description |
|---|---|
| Max depth (m) | Target bottom depth of the cast |
| Downcast (D) filter depths | Downcast sampling stop depths (shallow → deep) |
| Upcast (U) filter depths | Upcast sampling stop depths (deep → shallow) |
| CTD speed (m/s) | Maximum CTD descent/ascent speed |
| Acceleration (m/s²) | Winch acceleration magnitude |
| Filter duration (s) | Default pumping time per station |
| Safety margin (s) | Default buffer added before timer fires |

#### Advanced settings

| Parameter | Default | Description |
|---|---|---|
| Max winch speed (m/s) | 1.7 | Physical winch limit — used for 🟡 threshold in speed status |
| Instrument timer resets after each filter | on | Whether the device clock restarts after each actuation |
| Deploy delay (MM:SS) | 5:00 | Time on deck from T=0 to water entry |
| Homing time (s) | 30 | Instrument spin-up after the timer fires |
| Filtering activation buffer (s) | 10 | Loading time after homing before pumping begins |
| Time at the bottom (s) | 5 | Dwell time at max depth before ascending |

Per-station overrides for duration and safety margin are available in the **Filter settings** expander.

---

## Project structure

```
chronocaster/
├── app.py             # Streamlit UI and live cast tracker
├── calculator.py      # Core physics & delay calculation logic
├── test_calculator.py # Unit/integration tests for calculator
├── requirements.txt   # Python dependencies
└── TO_DO.md           # Development notes
```

### Core modules

**`calculator.py`**
- `travel_time(distance_m, v_max, accel)` — trapezoidal velocity profile travel-time model
- `compute_delays(CastParams)` → `(filter_stops, timeline, total_cast_time_s)`
- `required_speed(distance_m, time_avail_s, accel)` — live winch speed solver

**`app.py`**
- Streamlit page with sidebar parameter input, preset table, depth–time chart, and live cast tracker

---

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI framework |
| `plotly` | Interactive depth–time chart |
| `pandas` | Tabular data and CSV export |
| `streamlit-autorefresh` | Auto-refresh during live cast tracking |

---

## Running the tests

```bash
python test_calculator.py
```

---

## License

This project is not yet licensed. All rights reserved by the author.
