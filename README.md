# 🌊 ChronoCaster

ChronoCaster is a tool for determining the **preset values** needed to correctly trigger oceanographic instruments — such as the **SoloPuffer** — that actuate when specific conditions are met. At the moment it focuses on **time-delayed triggers**, computing the exact countdown preset for each actuation while accounting for filtering time, actuation and homing time, casting delays, and safety margins. It also provides a real-time cast tracker to follow operations as they happen.

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

## Platforms

ChronoCaster currently includes two interfaces:

- **Streamlit app** — the original desktop/browser version in Python
- **PWA (Progressive Web App)** — a standalone installable web app designed for phones and tablets, with offline support after the first load

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

### PWA-specific capabilities
- Installable on Android and iPhone from the browser
- Offline-capable after first load through a service worker cache
- Mobile-first planner/tracker workflow
- Local storage of cast settings on the device

---

## Installation

### Python / Streamlit version

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

### PWA version

No Python packages are needed to run the PWA itself. It is a static app in the `pwa/` folder.

For local testing, serve that folder over HTTP:

```bash
python -m http.server 8000 -d pwa
```

Then open:

```text
http://127.0.0.1:8000/index.html
```

Note: the service worker works on `localhost` during development, but for real installation on phones the app must be hosted over **HTTPS**.

---

## Usage

### Streamlit version

```bash
streamlit run app.py
```

Then open the URL shown in the terminal (usually `http://localhost:8501`).


## 📱 Use ChronoCaster on your phone (PWA)

ChronoCaster is available as a mobile web app that you can install directly on your phone — no app store needed.

### 🌐 Open the app

Go to:

https://JacopoBusatto.github.io/chronocaster/

Open this link in your mobile browser.

---

### 📥 Install the app

#### Android (Chrome)
- Tap the menu (⋮)
- Tap **Install app** or **Add to Home screen**

#### iPhone (Safari)
- Tap the **Share** button
- Tap **Add to Home Screen**

Once installed, the app will appear like a normal app on your phone.

---

### 🔌 Use it offline

The app works offline after the first load.

1. Open the app once while connected to the internet  
2. Close it  
3. You can now reopen it without Wi-Fi or mobile data  

---

### ⚠️ Important notes

- You must open the app **once online** before using it offline  
- If the app is updated, you need to open it online again to get the latest version  
- Offline mode stores data locally on your device  

---

### 🚀 What you can do

- Plan CTD casts and compute instrument trigger delays  
- Visualize the depth–time profile  
- Track the cast live during operations  
- Use it directly onboard, even without internet connection  

---

### 🧪 Troubleshooting

- If the app does not install:
  - Make sure you are using Chrome (Android) or Safari (iPhone)
- If offline mode does not work:
  - Open the app again while online to refresh the cache

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
├── pwa/               # Installable offline mobile web app
│   ├── index.html     # PWA entry point
│   ├── manifest.json  # Install metadata
│   ├── sw.js          # Offline cache service worker
│   ├── css/           # PWA styles
│   ├── js/            # PWA logic and chart renderer
│   └── icons/         # App icons
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

**`pwa/js/calculator.js`**
- JavaScript port of the timing and physics calculations used by the mobile app

**`pwa/js/app.js`**
- PWA planner/tracker state, rendering, persistence, and installable offline workflow

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

## PWA Deployment Tutorial

This section covers how to go from the current repository to a version that users can open on their phone and install.

### What "download ready" means for this project

For the PWA, "download ready" means:

- the app is hosted online over **HTTPS**
- the browser can read `manifest.json`
- the service worker `sw.js` is served correctly
- users can open the URL and choose **Install app** / **Add to Home Screen**
- the app finishes one successful online load so its files are cached for offline use

For a PWA there is no app-store package to upload. The hosted website itself is what users install.

### Recommended deployment path

The simplest route is:

1. Keep the existing Python/Streamlit app as-is
2. Deploy the `pwa/` folder as a static website
3. Test install + offline behavior on your own phone
4. Share the public URL with users

Good static hosts for this are:

- **GitHub Pages**
- **Netlify**
- **Cloudflare Pages**

If you want the least friction, **Netlify** or **Cloudflare Pages** is the easiest. If you want everything inside GitHub, use **GitHub Pages**.

### Option A: Deploy with GitHub Pages

1. Push this repository to GitHub.
2. In the repository, go to **Settings > Pages**.
3. Set the source to the branch you want to publish from.
4. Important: GitHub Pages publishes from the repository root or `/docs`, not directly from `pwa/`.
5. Because of that, do one of these:
- copy the contents of `pwa/` into a `docs/` folder and publish `docs/`
- or create a separate branch dedicated to the PWA contents
6. Wait for the Pages URL to be generated.
7. Open the URL on desktop and phone.
8. Confirm these files load without 404 errors:
- `/manifest.json`
- `/sw.js`
- `/js/app.js`
- `/css/style.css`
9. Install the app from the phone browser.
10. Put the phone in airplane mode and reopen the app to confirm offline behavior.

### Option B: Deploy with Netlify

1. Push the repository to GitHub.
2. Log into Netlify.
3. Choose **Add new site > Import an existing project**.
4. Select the GitHub repository.
5. Set the publish directory to:

```text
pwa
```

6. Leave the build command empty, because this is a static app.
7. Deploy the site.
8. Open the generated HTTPS URL.
9. Test installability and offline mode on a phone.

This is usually the fastest way to get the current PWA online.

### Option C: Deploy with Cloudflare Pages

1. Push the repository to GitHub.
2. Create a new Pages project in Cloudflare.
3. Connect the repository.
4. Set the output directory to:

```text
pwa
```

5. No build command is required.
6. Deploy.
7. Test the live HTTPS URL on mobile.

### Local validation before upload

Before publishing, run this locally:

```bash
python -m http.server 8000 -d pwa
```

Then verify:

1. `index.html` opens correctly
2. the preset table renders
3. the chart renders
4. you can start the cast tracker
5. `manifest.json` is reachable
6. `sw.js` is reachable

### Phone validation checklist

Once the app is online over HTTPS:

1. Open the URL on the phone
2. Use it once while online
3. Install it to the home screen
4. Close it completely
5. Disable Wi-Fi and mobile data
6. Reopen it from the installed icon
7. Confirm that the app still starts and that the planner/tracker interface loads

### Important limitations of offline mode

The app is offline-capable after the first successful online load, but keep these points in mind:

- if you change the PWA files, users need to load the new version online once to receive the update
- service worker updates are controlled by the cache name in `pwa/sw.js`
- if you make a release and users still see old files, increase the cache name version in `sw.js`

### Release workflow for future updates

When you want to publish a new mobile version:

1. Update the files in `pwa/`
2. If the asset list changed, update `ASSETS` in `pwa/sw.js`
3. Bump the cache version in `pwa/sw.js` (for example `chronocaster-v1` to `chronocaster-v2`)
4. Deploy again
5. Open the deployed site once to verify the new version is live
6. Test install/offline behavior again

---

## How We Should Proceed Now

The clean path from here is:

1. **Stabilize the PWA feature set**
Add the remaining Streamlit parity items you care about most and test the planner/tracker flow thoroughly.

2. **Choose the first hosting target**
For speed, deploy the current `pwa/` folder to Netlify or Cloudflare Pages.

3. **Test on real phones**
Check Android Chrome and iPhone Safari installation, then verify offline startup.

4. **Decide whether GitHub Pages is enough**
If you want a simple GitHub-only workflow, we can restructure publishing around `docs/` or a PWA-only branch.

5. **Prepare a first public release**
Add polished app icons, final app name/title, and a short in-app version label.

6. **Only after that, think about app stores**
If the PWA covers the field workflow well, you may not need stores at all.

---

## License

This project is not yet licensed. All rights reserved by the author.
