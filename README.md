# 🌊 ChronoCaster

A Streamlit web app for planning and tracking **CTD (Conductivity, Temperature, Depth)** oceanographic casts. ChronoCaster calculates the precise preset timer delays for each filter actuation, then lets you follow the cast in real time.

---

## What it does

During a CTD cast, water samplers (filters) must be triggered at exact depths. Because the instruments use pre-set countdown timers started **before** the CTD enters the water (T=0), every delay must account for:

- Travel time to each filter depth (trapezoidal velocity profile)
- A safety margin before the timer fires
- Instrument homing time after the timer fires
- Actuation buffer before pumping begins
- Filter pumping duration

ChronoCaster handles all of this math and produces a per-filter preset table plus an interactive depth–time chart.

---

## Features

- **Pre-cast planner** — enter cast parameters and instantly see all preset delays in a table and on a depth–time plot
- **Per-filter overrides** — set individual duration and safety margin for each filter, independent of the global defaults
- **Advanced timing controls** — configure homing time, actuation buffer, bottom dwell, and deploy delay
- **Live cast tracker** — start a cast timer at T=0 and step through phases; the app shows:
  - Current phase and time to next phase
  - Required winch speed to arrive on time
  - Live lateness indicator
  - Actual vs. predicted depth–time trace
- **CSV export** — download the full preset table as a CSV
- **Live speed solver** — computes the exact winch speed needed at any point during ascent/descent

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
| Type 1 filter depths | Downcast filter stop depths (shallow → deep) |
| Type 2 filter depths | Upcast filter stop depths (deep → shallow) |
| Max speed (m/s) | Maximum CTD descent/ascent speed |
| Acceleration (m/s²) | Winch acceleration magnitude |
| Filter duration (s) | Default pumping time per filter |
| Safety margin (s) | Default buffer added before timer fires |
| Deploy delay (s) | Time on deck from T=0 to water entry |
| Bottom dwell (s) | Time spent at max depth before ascending |
| Homing time (s) | Instrument spin-up after timer fires |
| Actuation buffer (s) | Loading time after homing before pumping |

Per-filter overrides for duration and safety margin are available in the **Advanced Settings** expander.

---

## Project structure

```
chronocaster/
├── app.py            # Streamlit UI and live cast tracker
├── calculator.py     # Core physics & delay calculation logic
├── test_calculator.py# Unit/integration tests for calculator
├── requirements.txt  # Python dependencies
└── TO_DO.md          # Development notes
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
