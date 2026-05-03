/* ===================================================================
   app.js — ChronoCaster PWA
   Main application logic: state, computation, rendering, events.
   Depends on: calculator.js, chart.js
   =================================================================== */
'use strict';

// =====================================================================
// GLOBAL STATE
// =====================================================================
const S = {
  // ---- Parameters (persisted) ----
  maxDepthM:       80,
  vMax:            1.0,
  accel:           0.1,
  deployDelayS:    300,   // 5:00
  bottomDwellS:    30,
  homingTimeS:     30,
  actuationBufferS: 10,
  clockReset:      true,
  vHardMax:        1.7,
  t1Filters: [{ depthM: 10, durationS: 900, marginS: 60 }],
  t2Filters: [{ depthM: 50, durationS: 900, marginS: 60 }],
  actualPresets:   {},   // filterId → absolute preset seconds

  // ---- Computed results ----
  filterStops:     [],
  timeline:        [],
  totalCastTimeS:  0,
  phases:          [],
  bottomArriveS:   null,
  bottomLeaveS:    null,
  surfaceReturnS:  null,
  recoveredTimeS:  null,
  computed:        false,

  // ---- Tracker state ----
  castActive:         false,
  t0WallMs:           null,
  phaseIdx:           0,
  actualTrace:        [],   // [{elapsedS, depthM, label}]
  liveT2Depths:       [],   // corrected T2 depths during cast
  phaseStartWallMs:   null,
  clockIntervalId:    null,

  // ---- UI ----
  currentView: 'planner',
};

// =====================================================================
// PERSISTENCE
// =====================================================================
function saveState() {
  const d = {
    maxDepthM: S.maxDepthM, vMax: S.vMax, accel: S.accel,
    deployDelayS: S.deployDelayS, bottomDwellS: S.bottomDwellS,
    homingTimeS: S.homingTimeS, actuationBufferS: S.actuationBufferS,
    clockReset: S.clockReset, vHardMax: S.vHardMax,
    t1Filters: S.t1Filters, t2Filters: S.t2Filters,
    actualPresets: S.actualPresets,
  };
  try { localStorage.setItem('cc_v1', JSON.stringify(d)); } catch (e) {}
}

function loadState() {
  try {
    const raw = localStorage.getItem('cc_v1');
    if (!raw) return;
    const d = JSON.parse(raw);
    Object.keys(d).forEach(k => { if (k in S) S[k] = d[k]; });
  } catch (e) {}
}

// =====================================================================
// COMPUTATION
// =====================================================================
function makeCastParams(t1Depths, t1Durs, t1Margins, t2Depths, t2Durs, t2Margins) {
  return {
    maxDepthM: S.maxDepthM, vMax: S.vMax, accel: S.accel,
    filterDurationS: 900, safetyMarginS: 300,
    type1Depths: t1Depths, type1FilterDurations: t1Durs, type1SafetyMargins: t1Margins,
    type2Depths: t2Depths, type2FilterDurations: t2Durs, type2SafetyMargins: t2Margins,
    deployDelayS: S.deployDelayS, bottomDwellS: S.bottomDwellS,
    homingTimeS: S.homingTimeS, actuationBufferS: S.actuationBufferS,
  };
}

function recompute() {
  const t1d = S.t1Filters.map(f => f.depthM);
  const t1u = S.t1Filters.map(f => f.durationS);
  const t1m = S.t1Filters.map(f => f.marginS);
  const t2d = S.t2Filters.map(f => f.depthM);
  const t2u = S.t2Filters.map(f => f.durationS);
  const t2m = S.t2Filters.map(f => f.marginS);

  if (!t1d.length && !t2d.length) { S.computed = false; return; }

  try {
    const p = makeCastParams(t1d, t1u, t1m, t2d, t2u, t2m);
    const { filterStops, timeline, totalCastTimeS } = computeDelays(p);
    S.filterStops    = filterStops;
    S.timeline       = timeline;
    S.totalCastTimeS = totalCastTimeS;

    const ev = type => timeline.find(e => e.eventType === type);
    const byLabel = lbl => timeline.find(e => e.label === lbl);

    S.bottomArriveS  = ev('bottom')        ? ev('bottom').timeS        : null;
    S.bottomLeaveS   = ev('bottom_leave')  ? ev('bottom_leave').timeS  : S.bottomArriveS;
    S.surfaceReturnS = ev('surface_return')? ev('surface_return').timeS : null;
    S.recoveredTimeS = byLabel('Recovered')? byLabel('Recovered').timeS : totalCastTimeS;

    S.phases = buildPhases(filterStops);

    // Initialise actual presets from computed values (only for new filters)
    let prevDepS = 0;
    filterStops.forEach(fs => {
      if (!(fs.filterId in S.actualPresets)) {
        S.actualPresets[fs.filterId] = fs.presetDelayS;
      }
      prevDepS = fs.departureTimeS;
    });

    S.computed = true;
  } catch (e) {
    console.error('Compute error:', e);
    S.computed = false;
  }
}

/** Build ordered phase list for the tracker. */
function buildPhases(filterStops) {
  const t1 = filterStops.filter(f => f.filterType === 1);
  const t2 = filterStops.filter(f => f.filterType === 2);
  const milestones = getWaypointsMilestones(filterStops);
  const ph = [];

  let prevDepart = S.deployDelayS;
  let prevDepth  = 0;

  ph.push({ label: '🚀 Deployment phase', timeS: 0, depthM: 0, fromDepthM: 0 });

  t1.forEach(fs => {
    ph.push({ label: `🔽 Descending to ${fs.filterId} (${fs.depthM.toFixed(0)} m)`,
               timeS: prevDepart, depthM: fs.depthM, fromDepthM: prevDepth });
    if (fs.presetDelayS > fs.arrivalTimeS + 1) {
      ph.push({ label: `⏳ Waiting at ${fs.filterId} (${fs.depthM.toFixed(0)} m)`,
                 timeS: fs.arrivalTimeS, depthM: fs.depthM, fromDepthM: fs.depthM });
    }
    ph.push({ label: `🔽 Filtering at ${fs.filterId} (${fs.depthM.toFixed(0)} m)`,
               timeS: fs.presetDelayS, depthM: fs.depthM, fromDepthM: fs.depthM });
    prevDepart = fs.departureTimeS;
    prevDepth  = fs.depthM;
  });

  if (t1.length > 0 && milestones.surfaceReturnS !== null) {
    ph.push({ label: '🔼 Returning to surface',
               timeS: prevDepart, depthM: 0, fromDepthM: prevDepth });
    prevDepart = milestones.surfaceReturnS;
    prevDepth  = 0;
  }

  if (milestones.bottomArriveS !== null) {
    ph.push({ label: `🔽 Descending to bottom (${S.maxDepthM.toFixed(0)} m)`,
               timeS: prevDepart, depthM: S.maxDepthM, fromDepthM: prevDepth });
    ph.push({ label: '⚓ At bottom',
               timeS: milestones.bottomArriveS, depthM: S.maxDepthM, fromDepthM: S.maxDepthM });
    prevDepart = milestones.bottomLeaveS;
    prevDepth  = S.maxDepthM;
  }

  t2.forEach(fs => {
    ph.push({ label: `🔼 Ascending to ${fs.filterId} (${fs.depthM.toFixed(0)} m)`,
               timeS: prevDepart, depthM: fs.depthM, fromDepthM: prevDepth });
    if (fs.presetDelayS > fs.arrivalTimeS + 1) {
      ph.push({ label: `⏳ Waiting at ${fs.filterId} (${fs.depthM.toFixed(0)} m)`,
                 timeS: fs.arrivalTimeS, depthM: fs.depthM, fromDepthM: fs.depthM });
    }
    ph.push({ label: `🔼 Filtering at ${fs.filterId} (${fs.depthM.toFixed(0)} m)`,
               timeS: fs.presetDelayS, depthM: fs.depthM, fromDepthM: fs.depthM });
    prevDepart = fs.departureTimeS;
    prevDepth  = fs.depthM;
  });

  if (milestones.recoveredTimeS !== null) {
    ph.push({ label: '🔼 Recovering to deck', timeS: prevDepart, depthM: 0, fromDepthM: prevDepth });
  }
  return ph;
}

// ---- Live tracker: recompute with corrected T2 depths + apply actual presets ----
function getLiveFilterStops() {
  const t1d = S.t1Filters.map(f => f.depthM);
  const t1u = S.t1Filters.map(f => f.durationS);
  const t1m = S.t1Filters.map(f => f.marginS);
  const t2d = S.liveT2Depths.length > 0
    ? S.liveT2Depths
    : S.t2Filters.map(f => f.depthM);
  const t2u = S.t2Filters.map(f => f.durationS);
  const t2m = S.t2Filters.map(f => f.marginS);

  let stops;
  try {
    const p = makeCastParams(t1d, t1u, t1m, t2d, t2u, t2m);
    stops = computeDelays(p).filterStops;
  } catch (e) {
    stops = [...S.filterStops];
  }

  // Apply actual preset overrides
  stops.forEach(fs => {
    const ov = S.actualPresets[fs.filterId];
    if (ov !== undefined) {
      const dwell = fs.departureTimeS - fs.presetDelayS;
      fs.presetDelayS   = ov;
      fs.departureTimeS = ov + dwell;
    }
  });

  // Propagate T2 departure times starting from bottomLeaveS
  const blS     = S.bottomLeaveS || 0;
  let prevDep   = blS;
  let prevDepth = S.maxDepthM;
  const t2Stops = stops.filter(f => f.filterType === 2)
                       .sort((a, b) => a.arrivalTimeS - b.arrivalTimeS);
  t2Stops.forEach(fs => {
    const travel    = travelTime(Math.abs(prevDepth - fs.depthM), S.vMax, S.accel);
    const newArr    = prevDep + travel;
    if (Math.abs(newArr - fs.arrivalTimeS) > 0.5) fs.arrivalTimeS = newArr;
    if (fs.presetDelayS < fs.arrivalTimeS) {
      const dwell = fs.departureTimeS - fs.presetDelayS;
      fs.presetDelayS   = fs.arrivalTimeS;
      fs.departureTimeS = fs.presetDelayS + dwell;
    }
    prevDep   = fs.departureTimeS;
    prevDepth = fs.depthM;
  });

  return stops;
}

// ---- Elapsed seconds from T=0 ----
function getElapsedS() {
  if (!S.t0WallMs) return 0;
  return (Date.now() - S.t0WallMs) / 1000;
}

// ---- Estimated current depth ----
function getCurrentDepth(elapsedS, phases = S.phases) {
  const phase = phases[S.phaseIdx];
  if (!phase) return 0;
  const from = phase.fromDepthM, to = phase.depthM;
  if (Math.abs(to - from) < 0.5) return to;
  const dist = Math.abs(to - from);
  const totalT = travelTime(dist, S.vMax, S.accel);
  const phaseElapsed = S.phaseStartWallMs
    ? Math.max(0, (Date.now() - S.phaseStartWallMs) / 1000) : 0;
  const frac = totalT > 0 ? Math.min(phaseElapsed / totalT, 1.0) : 1.0;
  return from + frac * (to - from);
}

// =====================================================================
// STATION STATUS CALCULATION
// =====================================================================
function stationStatus(fs, elapsedS, fromDepth, bottomArriveS = S.bottomArriveS) {
  return fs.filterType === 1
    ? calcT1Status(fs, elapsedS, fromDepth)
    : calcT2Status(fs, elapsedS, fromDepth, bottomArriveS);
}

function calcT1Status(fs, elapsedS, fromDepth) {
  const ttp = fs.presetDelayS - elapsedS;
  if (ttp <= 0) return { icon: '⚫', color: '#6c757d', reqSpd: S.vMax, routeNote: '—', dist: 0, tAtV: elapsedS };

  const dist = Math.max(fs.depthM - fromDepth, 0);
  const routeNote = `↓${dist.toFixed(0)} m`;
  if (dist < 0.5) return { icon: '🔔', color: '#28a745', reqSpd: S.vMax, routeNote, dist, tAtV: elapsedS + ttp };

  const tAtV    = elapsedS + travelTime(dist, S.vMax,     S.accel);
  const tAtHard = elapsedS + travelTime(dist, S.vHardMax, S.accel);
  const res = requiredSpeed(dist, ttp, S.accel);
  let req = res.status === 'impossible' ? S.vHardMax * 2 : res.vRequired;
  req = Math.max(0.01, req);
  const { icon, color } = speedToStatus(req);
  return { icon, color, reqSpd: Math.min(req, S.vHardMax), routeNote, dist, tAtV, tAtHard };
}

function calcT2Status(fs, elapsedS, fromDepth, bottomArriveS = S.bottomArriveS) {
  const ttp   = fs.presetDelayS - elapsedS;
  const preBot = bottomArriveS !== null && elapsedS < bottomArriveS;
  if (ttp <= 0) return { icon: '⚫', color: '#6c757d', reqSpd: S.vMax, routeNote: '—', dist: 0, tAtV: elapsedS };

  let dist, routeNote, tAtV, tAtHard, ttpTravel;
  if (preBot) {
    const dDown = S.maxDepthM - fromDepth;
    const dUp   = S.maxDepthM - fs.depthM;
    routeNote = `↓${dDown.toFixed(0)}m + ↑${dUp.toFixed(0)}m`;
    const tFixed  = travelTime(dDown, S.vMax, S.accel);
    tAtV          = elapsedS + tFixed + travelTime(dUp, S.vMax,     S.accel);
    tAtHard       = elapsedS + tFixed + travelTime(dUp, S.vHardMax, S.accel);
    ttpTravel     = ttp - tFixed;
    dist          = dUp;
  } else {
    dist       = Math.abs(fromDepth - fs.depthM);
    routeNote  = `↑${dist.toFixed(0)} m`;
    tAtV       = elapsedS + travelTime(dist, S.vMax,     S.accel);
    tAtHard    = elapsedS + travelTime(dist, S.vHardMax, S.accel);
    ttpTravel  = ttp;
  }

  if (dist < 0.5) return { icon: '🔔', color: '#28a745', reqSpd: S.vMax, routeNote, dist, tAtV };

  let req;
  if (ttpTravel > 0 && dist > 0) {
    const res = requiredSpeed(dist, ttpTravel, S.accel);
    req = res.status === 'impossible' ? S.vHardMax * 2 : res.vRequired;
  } else {
    req = S.vHardMax * 2;
  }
  req = Math.max(0.01, req);
  const { icon, color } = speedToStatus(req);
  return { icon, color, reqSpd: Math.min(req, S.vHardMax), routeNote, dist, tAtV, tAtHard };
}

function speedToStatus(req) {
  if (req <= S.vMax)     return { icon: '🟢', color: '#28a745' };
  if (req <= S.vHardMax) return { icon: '🟡', color: '#f0ad4e' };
  return                        { icon: '🔴', color: '#dc3545' };
}

// =====================================================================
// ACTUAL PRESETS HELPERS
// =====================================================================
/** Effective departure of the filter BEFORE filterId (accounting for overrides). */
function prevEffectiveDep(filterId) {
  let prevDep = 0;
  for (const fs of S.filterStops) {
    if (fs.filterId === filterId) return prevDep;
    const ov = S.actualPresets[fs.filterId];
    const dwell = fs.departureTimeS - fs.presetDelayS;
    prevDep = (ov !== undefined ? ov : fs.presetDelayS) + dwell;
  }
  return prevDep;
}

/** Absolute seconds from instrument display value */
function instrToAbsolute(instrS, filterId) {
  return S.clockReset ? instrS + prevEffectiveDep(filterId) : instrS;
}

/** Instrument display value from absolute seconds */
function absoluteToInstr(absS, filterId) {
  return S.clockReset ? absS - prevEffectiveDep(filterId) : absS;
}

// =====================================================================
// PLANNER RENDERING
// =====================================================================
let _recomputeTimer = null;
function scheduleRecompute() {
  clearTimeout(_recomputeTimer);
  _recomputeTimer = setTimeout(() => {
    readFormIntoState();
    recompute();
    renderPlannerResults();
    saveState();
  }, 250);
}

function readFormIntoState() {
  S.maxDepthM       = +q('#inp-max-depth').value  || 80;
  S.vMax            = +q('#inp-vmax').value        || 1.0;
  S.accel           = +q('#inp-accel').value       || 0.1;
  S.deployDelayS    = parseMMSS(q('#inp-deploy-delay').value);
  S.bottomDwellS    = parseMMSS(q('#inp-bottom-dwell').value);
  S.homingTimeS     = parseMMSS(q('#inp-homing-time').value);
  S.actuationBufferS= parseMMSS(q('#inp-actuation-buffer').value);
  S.vHardMax        = +q('#inp-vhard-max').value   || 1.7;
  S.clockReset      = q('#inp-clock-reset').checked;

  // Filter rows
  S.t1Filters = readFilterRows('t1');
  S.t2Filters = readFilterRows('t2');
}

function readFilterRows(type) {
  const rows = qAll(`[data-filter-type="${type}"]`);
  return Array.from(rows).map(row => ({
    depthM:    +row.querySelector('.f-depth').value   || 10,
    durationS: parseMMSS(row.querySelector('.f-dur').value),
    marginS:   parseMMSS(row.querySelector('.f-margin').value),
  }));
}

function renderFilterRows() {
  renderFilterSection('t1', S.t1Filters, '🔽 Downcast Filter', 'D');
  renderFilterSection('t2', S.t2Filters, '🔼 Upcast Filter', 'U');
}

function renderFilterSection(type, filters, labelPrefix, _shortPrefix) {
  const container = q(`#${type}-filters`);
  container.innerHTML = filters.map((f, i) => `
    <div class="filter-row" data-filter-type="${type}">
      <div class="filter-row-label">${labelPrefix} ${i + 1}</div>
      <div class="form-row three-col">
        <label>Depth (m)
          <input type="number" class="f-depth" min="1" max="${S.maxDepthM}" value="${f.depthM}">
        </label>
        <label>Timeout (MM:SS)
          <input type="text" class="f-dur" value="${minsec(f.durationS)}" placeholder="15:00">
        </label>
        <label>Safety (MM:SS)
          <input type="text" class="f-margin" value="${minsec(f.marginS)}" placeholder="1:00">
        </label>
      </div>
    </div>
  `).join('');
}

function renderPlannerResults() {
  const el = q('#planner-results');
  if (!S.computed) {
    el.innerHTML = `<div class="info-box">Add at least one filter above to compute preset delays.</div>`;
    return;
  }

  const { filterStops, totalCastTimeS, clockReset } = S;
  const t1Stops = filterStops.filter(f => f.filterType === 1);
  const t2Stops = filterStops.filter(f => f.filterType === 2);

  // Build table rows
  let prevDepS = 0;
  const tableRows = filterStops.map(fs => {
    const instrS = S.clockReset ? fs.presetDelayS - prevDepS : fs.presetDelayS;
    const typeClass = fs.filterType === 1 ? 'td-d' : 'td-u';
    const row = `
      <tr>
        <td class="${typeClass} bold">${fs.filterId}</td>
        <td>${fs.depthM.toFixed(0)}</td>
        <td class="td-mono">${fmtTime(fs.presetDelayS)}</td>
        <td class="td-mono bold">${fmtTime(instrS)}</td>
        <td class="td-mono">${fmtTime(fs.departureTimeS)}</td>
      </tr>`;
    prevDepS = fs.departureTimeS;
    return row;
  }).join('');

  // Actual presets form
  prevDepS = 0;
  const presetOverrides = filterStops.map(fs => {
    const absVal = S.actualPresets[fs.filterId] !== undefined
      ? S.actualPresets[fs.filterId] : fs.presetDelayS;
    const instrDisp = S.clockReset ? absVal - prevDepS : absVal;
    const prevDepForThis = prevDepS;
    prevDepS = (S.actualPresets[fs.filterId] !== undefined
      ? S.actualPresets[fs.filterId] : fs.presetDelayS)
      + (fs.departureTimeS - fs.presetDelayS);

    return `
      <label style="flex:1 1 120px;">
        <span class="${fs.filterType === 1 ? 'text-green' : 'text-yellow'}">${fs.filterId}</span>
        &nbsp;<span class="text-dim" style="font-size:0.75rem">(${fs.depthM.toFixed(0)} m)</span>
        <input type="text" class="actual-preset-input" data-filter-id="${fs.filterId}"
               value="${sToHMMSS(Math.max(instrDisp, 0))}" placeholder="H:MM:SS">
      </label>`;
  }).join('');

  // Chart waypoints for planner
  const waypoints = buildWaypoints(filterStops, S.timeline);
  const chartId = 'planner-chart';

  el.innerHTML = `
    <!-- Preset table -->
    <div class="section">
      <button class="section-header" data-collapse="preset-tbl-body">
        📋 Preset Delays <span class="section-chevron open">▼</span>
      </button>
      <div id="preset-tbl-body" class="section-body">
        <div class="preset-table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Filter</th>
                <th>Depth (m)</th>
                <th>Fires at (T+)</th>
                <th>Instrument set</th>
                <th>Ends at (T+)</th>
              </tr>
            </thead>
            <tbody>${tableRows}</tbody>
          </table>
        </div>
        <div class="metric-row" style="margin-top:10px">
          <div class="metric-card">
            <div class="metric-label">Total cast</div>
            <div class="metric-value">${fmtTime(totalCastTimeS)}</div>
          </div>
          ${S.bottomArriveS !== null ? `
          <div class="metric-card">
            <div class="metric-label">Arrive bottom</div>
            <div class="metric-value">${fmtTime(S.bottomArriveS)}</div>
          </div>` : ''}
        </div>
        <div class="btn-row" style="margin-top:6px">
          <button class="btn btn-outline btn-sm" id="btn-export-csv">⬇ Export CSV</button>
        </div>
      </div>
    </div>

    <!-- Actual preset overrides -->
    <div class="section">
      <button class="section-header" data-collapse="preset-override-body">
        🔧 Programmed Instrument Settings
        <span class="section-chevron open">▼</span>
      </button>
      <div id="preset-override-body" class="section-body">
        <p class="text-dim" style="font-size:0.8rem; margin-bottom:8px;">
          ${S.clockReset
            ? 'Values relative to previous filter end (clock-reset ON). Format: H:MM:SS'
            : 'Absolute from T=0 (clock-reset OFF). Format: H:MM:SS'}
        </p>
        <div style="display:flex; flex-wrap:wrap; gap:8px;">${presetOverrides}</div>
      </div>
    </div>

    <!-- Depth-time chart -->
    <div class="section">
      <button class="section-header" data-collapse="planner-chart-body">
        📈 Depth–Time Chart <span class="section-chevron open">▼</span>
      </button>
      <div id="planner-chart-body" class="section-body" style="padding:0">
        <div class="chart-container" style="margin:0; border:none; border-radius:0">
          <canvas id="${chartId}"></canvas>
        </div>
      </div>
    </div>

    <!-- Start button -->
    <div class="start-section">
      <button class="btn btn-primary btn-full" id="btn-start-cast" style="font-size:1rem; min-height:52px;">
        ▶ Start Cast (T = 0)
      </button>
    </div>
  `;

  // Draw chart
  requestAnimationFrame(() => {
    drawChart(chartId, {
      waypoints,
      t1Stops: filterStops.filter(f => f.filterType === 1),
      t2Stops: filterStops.filter(f => f.filterType === 2),
      actualTrace: [],
      currentPos: null,
      maxDepthM: S.maxDepthM,
      totalTimeS: S.totalCastTimeS,
    });
  });

  // Hook up collapsible sections
  setupCollapseHandlers();

  // Hook up actual preset inputs
  qAll('.actual-preset-input').forEach(inp => {
    inp.addEventListener('change', () => {
      const fid  = inp.dataset.filterId;
      const instrS = parseMMSS(inp.value);
      S.actualPresets[fid] = instrToAbsolute(instrS, fid);
      saveState();
    });
  });

  // CSV export
  const csvBtn = q('#btn-export-csv');
  if (csvBtn) csvBtn.addEventListener('click', exportCSV);

  // Start cast
  const startBtn = q('#btn-start-cast');
  if (startBtn) startBtn.addEventListener('click', startCast);
}

function buildWaypoints(filterStops, timeline) {
  return buildWaypointsFromStops(filterStops);
}

function getWaypointsMilestones(filterStops) {
  const t1Stops = filterStops
    .filter(f => f.filterType === 1)
    .sort((a, b) => a.arrivalTimeS - b.arrivalTimeS);
  const t2Stops = filterStops
    .filter(f => f.filterType === 2)
    .sort((a, b) => a.arrivalTimeS - b.arrivalTimeS);

  let currentDepth = 0;
  let currentTime = S.deployDelayS;
  let surfaceReturnS = null;

  if (t1Stops.length > 0) {
    const lastT1 = t1Stops[t1Stops.length - 1];
    currentDepth = lastT1.depthM;
    currentTime = lastT1.departureTimeS;
    currentTime += travelTime(currentDepth, S.vMax, S.accel);
    currentDepth = 0;
    surfaceReturnS = currentTime;
  }

  currentTime += travelTime(Math.abs(S.maxDepthM - currentDepth), S.vMax, S.accel);
  const bottomArriveS = currentTime;
  const bottomLeaveS = bottomArriveS + S.bottomDwellS;

  currentDepth = S.maxDepthM;
  currentTime = bottomLeaveS;

  if (t2Stops.length > 0) {
    const lastT2 = t2Stops[t2Stops.length - 1];
    currentDepth = lastT2.depthM;
    currentTime = lastT2.departureTimeS;
  }

  const recoveredTimeS = currentTime + travelTime(currentDepth, S.vMax, S.accel);

  return { surfaceReturnS, bottomArriveS, bottomLeaveS, recoveredTimeS };
}

/** Build chart waypoints from any set of filter stops (planned or live). */
function buildWaypointsFromStops(filterStops) {
  const wps = [];
  const t1Stops = filterStops.filter(f => f.filterType === 1);
  const t2Stops = filterStops.filter(f => f.filterType === 2);
  const milestones = getWaypointsMilestones(filterStops);

  wps.push({ timeS: 0, depthM: 0, label: 'Deploy' });
  if (S.deployDelayS > 0)
    wps.push({ timeS: S.deployDelayS, depthM: 0, label: 'Water entry' });

  t1Stops.forEach(fs => {
    wps.push({ timeS: fs.arrivalTimeS,   depthM: fs.depthM, label: `${fs.filterId} arrive` });
    wps.push({ timeS: fs.presetDelayS,   depthM: fs.depthM, label: `${fs.filterId} firing` });
    wps.push({ timeS: fs.departureTimeS, depthM: fs.depthM, label: `${fs.filterId} end` });
  });

  if (milestones.surfaceReturnS !== null)
    wps.push({ timeS: milestones.surfaceReturnS, depthM: 0, label: 'Surface return' });

  if (milestones.bottomArriveS !== null) {
    wps.push({ timeS: milestones.bottomArriveS, depthM: S.maxDepthM, label: 'Bottom' });
    wps.push({ timeS: milestones.bottomLeaveS,  depthM: S.maxDepthM, label: 'Leave bottom' });
  }

  t2Stops.forEach(fs => {
    wps.push({ timeS: fs.arrivalTimeS,   depthM: fs.depthM, label: `${fs.filterId} arrive` });
    wps.push({ timeS: fs.presetDelayS,   depthM: fs.depthM, label: `${fs.filterId} firing` });
    wps.push({ timeS: fs.departureTimeS, depthM: fs.depthM, label: `${fs.filterId} end` });
  });

  if (milestones.recoveredTimeS !== null)
    wps.push({ timeS: milestones.recoveredTimeS, depthM: 0, label: 'Recovered' });

  wps.sort((a, b) => a.timeS - b.timeS);
  return wps;
}

// =====================================================================
// TRACKER
// =====================================================================
function startCast() {
  if (!S.computed) return;
  const now = Date.now();
  S.castActive        = true;
  S.t0WallMs          = now;
  S.phaseStartWallMs  = now;
  S.phaseIdx          = 0;
  S.actualTrace       = [{ elapsedS: 0, depthM: 0, label: 'T=0 — cast started' }];
  S.liveT2Depths      = S.t2Filters.map(f => f.depthM);
  S.phases            = buildPhases(getLiveFilterStops());
  S.phases.forEach(ph => { if (ph.timeS === undefined) ph.timeS = 0; });

  switchView('tracker');
  renderTrackerShell();
  startTrackerClock();
}

function stopCast() {
  S.castActive = false;
  S.t0WallMs   = null;
  clearInterval(S.clockIntervalId);
  S.clockIntervalId = null;
  const floatBtn = q('#float-next-btn');
  if (floatBtn) floatBtn.classList.add('hidden');
  switchView('planner');
}

function nextPhase() {
  S.phases = buildPhases(getLiveFilterStops());
  if (S.phaseIdx >= S.phases.length) S.phaseIdx = Math.max(S.phases.length - 1, 0);
  const elapsedS    = getElapsedS();
  const curPhase    = S.phases[S.phaseIdx];
  const curDepth    = curPhase ? curPhase.depthM : 0;
  S.actualTrace.push({ elapsedS, depthM: curDepth, label: curPhase ? curPhase.label : '' });
  if (S.phaseIdx < S.phases.length - 1) {
    S.phaseIdx++;
    S.phaseStartWallMs = Date.now();
  } else {
    S.castActive = false;
    clearInterval(S.clockIntervalId);
    toast('Cast complete!');
  }
  updateTrackerDisplay();
}

function undoPhase() {
  if (S.phaseIdx > 0) {
    S.phaseIdx--;
    S.phaseStartWallMs = Date.now();
    if (S.actualTrace.length > 1) S.actualTrace.pop();
    updateTrackerDisplay();
  }
}

function startTrackerClock() {
  clearInterval(S.clockIntervalId);
  S.clockIntervalId = setInterval(updateTrackerDisplay, 2000);
  updateTrackerDisplay();
}

function renderTrackerShell() {
  const el = q('#view-tracker');
  el.innerHTML = `
    <div id="tracker-sticky-bar" class="tracker-sticky"></div>
    <div id="tracker-controls" style="padding:10px; display:flex; gap:8px; flex-wrap:wrap;">
      <button class="btn btn-danger btn-sm" id="btn-stop-cast">⏹ Stop</button>
      <button class="btn btn-outline btn-sm" id="btn-undo-phase" disabled>↩ Undo</button>
    </div>

    <!-- T2 depth corrections -->
    <div class="section" id="t2-corr-section" style="${S.liveT2Depths.length === 0 ? 'display:none' : ''}">
      <button class="section-header" data-collapse="t2-corr-body">
        ✏️ Correct T2 depths from downcast profile <span class="section-chevron">▼</span>
      </button>
      <div id="t2-corr-body" class="section-body hidden">
        <p class="text-dim" style="font-size:0.8rem; margin-bottom:8px;">Update when you know actual feature depths from the CTD profile.</p>
        <div id="t2-corr-inputs" style="display:flex; flex-wrap:wrap; gap:8px;">
          ${S.liveT2Depths.map((d, i) => `
            <label style="flex:1 1 100px;">
              U-${i+1} depth (m)
              <input type="number" class="t2-live-depth" data-idx="${i}"
                     min="1" max="${S.maxDepthM}" value="${d}">
            </label>`).join('')}
        </div>
      </div>
    </div>

    <!-- Live status (rebuilt by updateTrackerDisplay) -->
    <div id="tracker-live"></div>

    <!-- Chart -->
    <div class="section" style="margin-top:6px">
      <button class="section-header" data-collapse="tracker-chart-body">
        📈 Cast Chart <span class="section-chevron open">▼</span>
      </button>
      <div id="tracker-chart-body" class="section-body" style="padding:0">
        <div class="chart-container" style="margin:0; border:none; border-radius:0">
          <canvas id="tracker-chart"></canvas>
        </div>
      </div>
    </div>
  `;

  // Wire up controls
  q('#btn-stop-cast').addEventListener('click', () => { if (confirm('Stop cast?')) stopCast(); });
  q('#btn-undo-phase').addEventListener('click', undoPhase);

  // Floating next-phase button (persists across updateTrackerDisplay calls)
  let floatBtn = q('#float-next-btn');
  if (!floatBtn) {
    floatBtn = document.createElement('button');
    floatBtn.id = 'float-next-btn';
    floatBtn.className = 'btn btn-primary float-next-btn';
    floatBtn.textContent = '➡ Next Phase';
    document.body.appendChild(floatBtn);
  }
  floatBtn.classList.remove('hidden');
  floatBtn.addEventListener('click', nextPhase);

  // T2 live depth inputs
  el.addEventListener('change', e => {
    const inp = e.target.closest('.t2-live-depth');
    if (!inp) return;
    const idx = +inp.dataset.idx;
    S.liveT2Depths[idx] = +inp.value || S.liveT2Depths[idx];
  });

  setupCollapseHandlers();
}

function updateTrackerDisplay() {
  if (!document.getElementById('tracker-live')) return;

  const elapsedS    = getElapsedS();
  const liveStops = getLiveFilterStops();
  const liveMilestones = getWaypointsMilestones(liveStops);
  S.phases = buildPhases(liveStops);
  if (S.phaseIdx >= S.phases.length) S.phaseIdx = Math.max(S.phases.length - 1, 0);

  const phases      = S.phases;
  const curPhase    = phases[Math.min(S.phaseIdx, phases.length - 1)];
  const nextPhaseEv = phases[S.phaseIdx + 1];
  const isLastPhase = S.phaseIdx >= phases.length - 1;

  // Current depth estimate
  const fromDepth = curPhase ? curPhase.fromDepthM : 0;
  const curDepth  = getCurrentDepth(elapsedS, phases);

  // Live filter stops (with T2 corrections + actual preset overrides)
  const t1Live = liveStops.filter(f => f.filterType === 1).sort((a, b) => a.presetDelayS - b.presetDelayS);
  const t2Live = liveStops.filter(f => f.filterType === 2).sort((a, b) => -b.arrivalTimeS + a.arrivalTimeS);
  // t2 deepest first for pre-bottom, shallowest-next for post-bottom
  const t2ByAscent = [...liveStops.filter(f => f.filterType === 2)].sort((a, b) => b.depthM - a.depthM);

  const isPostBottom = liveMilestones.bottomArriveS !== null && elapsedS >= liveMilestones.bottomArriveS;

  // Auto-record trace every ~2s
  const tr = S.actualTrace;
  if (!tr.length || Math.abs(tr[tr.length - 1].elapsedS - elapsedS) >= 1.9)
    S.actualTrace.push({ elapsedS, depthM: curDepth, label: '' });

  // Next pending T1 / T2 station
  const nextT1 = t1Live.find(fs => elapsedS < fs.presetDelayS);
  let nextT2 = null;
  const allDone = t2ByAscent.length > 0 && elapsedS >= t2ByAscent[t2ByAscent.length - 1].departureTimeS;
  if (!allDone) {
    if (isPostBottom) {
      nextT2 = t2ByAscent.find(fs => curDepth >= fs.depthM - 0.5 && elapsedS < fs.presetDelayS);
    } else {
      nextT2 = t2ByAscent[0] || null;
    }
  }

  // Active station for dot color
  let activeStation = null, dotColor = '#28a745';
  if (!isPostBottom && nextT1) {
    const st = calcT1Status(nextT1, elapsedS, curDepth);
    dotColor = st.color; activeStation = nextT1;
  } else if (nextT2) {
    const st = calcT2Status(nextT2, elapsedS, curDepth);
    dotColor = st.color; activeStation = nextT2;
  }

  // Is current phase a filter phase?
  const label = curPhase ? curPhase.label : '';
  const isFilterPhase = label.includes('Filtering at');
  let curFilterStop = null, filterFiresIn = null, filterEndsIn = null, arrivalOffset = null;
  if (isFilterPhase) {
    curFilterStop = liveStops.find(fs => Math.abs(fs.presetDelayS - (curPhase ? curPhase.timeS : 0)) < 1.5);
    if (curFilterStop) {
      filterFiresIn = curFilterStop.presetDelayS - elapsedS;
      filterEndsIn  = curFilterStop.departureTimeS - elapsedS;
      if (S.phaseStartWallMs && S.t0WallMs) {
        const entryElapsed = (S.phaseStartWallMs - S.t0WallMs) / 1000;
        arrivalOffset = entryElapsed - curFilterStop.presetDelayS;
      }
    }
  }

  // Next filter countdown (any filter not yet fired)
  const nextFilter = [...liveStops].sort((a, b) => a.presetDelayS - b.presetDelayS)
    .find(fs => fs.presetDelayS > elapsedS);

  // ---- Sticky bar ----
  const stickyBar = q('#tracker-sticky-bar');
  if (stickyBar) {
    const toNextPhase = nextPhaseEv ? Math.max(nextPhaseEv.timeS - elapsedS, 0) : null;
    const nextLabel   = isFilterPhase ? '🔬 Sampling ends in' : '⏳ Next';
    const nextVal     = isFilterPhase && curFilterStop
      ? fmtTime(Math.max(curFilterStop.departureTimeS - elapsedS, 0))
      : (toNextPhase !== null ? fmtTime(toNextPhase) : '—');
    const filterTxt   = nextFilter
      ? `🎣 ${nextFilter.filterId} in: <b>${fmtTime(Math.max(nextFilter.presetDelayS - elapsedS, 0))}</b>`
      : 'All filters complete ✅';

    stickyBar.innerHTML = `
      <span class="sticky-phase">
        Phase ${S.phaseIdx + 1}/${phases.length} — ${label}
      </span>
      <span class="sticky-stat">⏱ T+ <b>${fmtTime(elapsedS)}</b></span>
      <span class="sticky-stat">${nextLabel}: <b>${nextVal}</b></span>
      <span class="sticky-stat">${filterTxt}</span>
    `;
  }

  // ---- Floating Next Phase button label ----
  const floatBtn = q('#float-next-btn');
  if (floatBtn) {
    floatBtn.textContent = isLastPhase ? '🏁 Complete' : '➡ Next Phase';
  }
  const undoBtn = q('#btn-undo-phase');
  if (undoBtn) undoBtn.disabled = S.phaseIdx === 0;

  // ---- Main status banner ----
  let bannerClass = 'banner-green', bannerText = '';
  if (!activeStation) {
    bannerText = '✅ All filters complete — recovering';
    bannerClass = 'banner-green';
  } else {
    const st = stationStatus(activeStation, elapsedS, curDepth, liveMilestones.bottomArriveS);
    if (st.icon === '⚫') {
      bannerClass = 'banner-dark';
      bannerText  = `⚫ ${activeStation.filterId} — timer already fired (station missed)`;
    } else if (st.icon === '🔔') {
      bannerClass = 'banner-green';
      bannerText  = `🔔 At ${activeStation.filterId} (${activeStation.depthM.toFixed(0)} m) — starts in ${fmtTime(Math.max(activeStation.presetDelayS - elapsedS, 0))}`;
    } else if (st.icon === '🟢') {
      bannerClass = 'banner-green';
      bannerText  = `🟢 ${activeStation.filterId} reachable — min speed: ${st.reqSpd.toFixed(2)} m/s`;
    } else if (st.icon === '🟡') {
      bannerClass = 'banner-yellow';
      bannerText  = `🟡 ${activeStation.filterId} tight — need ${st.reqSpd.toFixed(2)} m/s (max ${S.vHardMax.toFixed(1)} m/s)`;
    } else {
      bannerClass = 'banner-red';
      bannerText  = `🔴 ${activeStation.filterId} unreachable — even winch max (${S.vHardMax.toFixed(1)} m/s) not enough`;
    }
  }

  // ---- Filter-phase info card ----
  let filterCardHtml = '';
  if (isFilterPhase && curFilterStop) {
    const dur = curFilterStop.departureTimeS - curFilterStop.presetDelayS;
    let fireTxt, fireColor;
    if (filterFiresIn !== null && filterFiresIn > 0) {
      fireTxt = `⏳ Fires in <b>${fmtTime(filterFiresIn)}</b>`;
      fireColor = '#4fa3e0';
    } else if (filterFiresIn !== null) {
      fireTxt = `🔬 Sampling — started <b>${fmtTime(-filterFiresIn)}</b> ago`;
      fireColor = '#28a745';
    } else {
      fireTxt = '—'; fireColor = '#8ec8f6';
    }
    let fendTxt = filterEndsIn !== null && filterEndsIn > 0
      ? `Ends in <b>${fmtTime(filterEndsIn)}</b>` : '✅ Sampling complete';
    let arrTxt, arrColor;
    if (arrivalOffset !== null) {
      if (Math.abs(arrivalOffset) < 5)      { arrTxt = 'Arrived on time ✓'; arrColor = '#28a745'; }
      else if (arrivalOffset < 0)           { arrTxt = `🟢 Early by <b>${fmtTime(-arrivalOffset)}</b>`; arrColor = '#28a745'; }
      else                                  { arrTxt = `🔴 Late by <b>${fmtTime(arrivalOffset)}</b>`;  arrColor = '#dc3545'; }
    } else { arrTxt = '—'; arrColor = '#8ec8f6'; }

    filterCardHtml = `
      <div class="filter-card">
        <div class="filter-card-item">🎣 <b>${curFilterStop.filterId}</b>
          &nbsp;|&nbsp;Preset: <b>${fmtTime(curFilterStop.presetDelayS)}</b>
          &nbsp;|&nbsp;Duration: <b>${fmtTime(dur)}</b></div>
        <div class="filter-card-item" style="color:${fireColor}">${fireTxt}</div>
        <div class="filter-card-item">${fendTxt}</div>
        <div class="filter-card-item" style="color:${arrColor}">${arrTxt}</div>
      </div>`;
  }

  // ---- Speed table ----
  const allStops = [...t1Live, ...t2Live].sort((a, b) => a.presetDelayS - b.presetDelayS);
  const speedRows = allStops.map(fs => {
    const st  = stationStatus(fs, elapsedS, curDepth, liveMilestones.bottomArriveS);
    const ttp = fs.presetDelayS - elapsedS;
    const earlyS = fs.presetDelayS - st.tAtV;
    let vStr, arrStr;
    if (ttp <= 0)            { vStr = 'started'; arrStr = '—'; }
    else if (st.dist < 0.5) { vStr = 'at depth'; arrStr = '—'; }
    else {
      vStr   = `${st.icon} ${st.reqSpd.toFixed(2)} m/s`;
      arrStr = earlyS >= 0 ? `+${fmtTime(earlyS)}` : `−${fmtTime(-earlyS)}`;
    }
    const idClass   = fs.filterType === 1 ? 'td-d' : 'td-u';
    return `<tr>
      <td class="${idClass} bold">${fs.filterId}</td>
      <td>${fs.depthM.toFixed(0)} m</td>
      <td class="mono">${vStr}</td>
      <td class="mono">${arrStr !== '—' ? arrStr : '—'}</td>
      <td class="mono">${fmtTime(Math.max(ttp, 0))}</td>
    </tr>`;
  }).join('');

  const liveTotalTimeS = liveMilestones.recoveredTimeS || S.totalCastTimeS;
  const recoveryLeft = Math.max(liveTotalTimeS - elapsedS, 0);

  // ---- Phase breadcrumb ----
  const breadcrumb = phases.map((ph, i) => {
    if (i < S.phaseIdx)      return `<span class="phase-done">${ph.label}</span>`;
    if (i === S.phaseIdx)    return `<span class="phase-active">● ${ph.label}</span>`;
    return `<span class="phase-future">○ ${ph.label}</span>`;
  }).join(' › ');

  // Inject live section — save scroll positions of scrollable children before rebuilding
  const _liveEl = q('#tracker-live');
  const _tableScrollLeft = _liveEl.querySelector('.preset-table-wrapper')?.scrollLeft ?? 0;
  const _breadcrumbScrollLeft = _liveEl.querySelector('.phase-breadcrumb')?.scrollLeft ?? 0;
  _liveEl.innerHTML = `
    <div class="status-banner ${bannerClass}" style="margin:6px 10px">${bannerText}</div>

    ${filterCardHtml}

    <div class="metric-row" style="padding:0 10px">
      <div class="metric-card">
        <div class="metric-label">🏁 Time to recovery</div>
        <div class="metric-value">${fmtTime(recoveryLeft)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">⏱ Elapsed</div>
        <div class="metric-value">${fmtTime(elapsedS)}</div>
      </div>
    </div>

    <p class="speed-table-title">⚡ Required speed per station:</p>
    <div class="preset-table-wrapper" style="margin:0 10px 10px">
      <table>
        <thead><tr>
          <th>Station</th><th>Depth</th>
          <th>Min. speed</th><th>Arrival @V</th><th>Countdown</th>
        </tr></thead>
        <tbody>${speedRows || '<tr><td colspan="5" class="text-dim" style="text-align:center;padding:10px">No stations configured</td></tr>'}</tbody>
      </table>
    </div>

    <div class="phase-breadcrumb">${breadcrumb}</div>
  `;

  // Restore scroll positions after DOM rebuild
  _liveEl.querySelector('.preset-table-wrapper')?.scrollTo({ left: _tableScrollLeft, behavior: 'instant' });
  _liveEl.querySelector('.phase-breadcrumb')?.scrollTo({ left: _breadcrumbScrollLeft, behavior: 'instant' });

  // Redraw chart — use liveStops so corrected T2 depths update the planned path line
  const waypoints = buildWaypointsFromStops(liveStops);
  const liveT2 = liveStops.filter(f => f.filterType === 2);
  requestAnimationFrame(() => {
    drawChart('tracker-chart', {
      waypoints,
      t1Stops: liveStops.filter(f => f.filterType === 1),
      t2Stops: liveT2,
      actualTrace: S.actualTrace,
      currentPos: S.castActive ? { elapsedS, depthM: curDepth, color: dotColor } : null,
      maxDepthM: S.maxDepthM,
      totalTimeS: liveTotalTimeS,
    });
  });
}

// =====================================================================
// CSV EXPORT
// =====================================================================
function exportCSV() {
  if (!S.computed) return;
  let prevDepS = 0;
  const lines = [
    ['Filter ID', 'Depth (m)', 'Fires at (T+)', 'Instrument setting', 'Ends at (T+)'].join(',')
  ];
  S.filterStops.forEach(fs => {
    const instrS = S.clockReset ? fs.presetDelayS - prevDepS : fs.presetDelayS;
    lines.push([fs.filterId, fs.depthM.toFixed(0), fmtTime(fs.presetDelayS), fmtTime(instrS), fmtTime(fs.departureTimeS)].join(','));
    prevDepS = fs.departureTimeS;
  });
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'chronocaster_presets.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

// =====================================================================
// UI HELPERS
// =====================================================================
const q  = sel => document.querySelector(sel);
const qAll = sel => document.querySelectorAll(sel);

function switchView(view) {
  S.currentView = view;
  qAll('.view').forEach(v => v.classList.remove('active'));
  qAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const viewEl = q(`#view-${view}`);
  const btnEl  = q(`[data-tab="${view}"]`);
  if (viewEl) viewEl.classList.add('active');
  if (btnEl)  btnEl.classList.add('active');
}

function setupCollapseHandlers() {
  qAll('[data-collapse]').forEach(btn => {
    btn.removeEventListener('click', collapseToggle);
    btn.addEventListener('click', collapseToggle);
  });
}

function collapseToggle(e) {
  const btn    = e.currentTarget;
  const target = q(`#${btn.dataset.collapse}`);
  const chev   = btn.querySelector('.section-chevron');
  if (!target) return;
  const isHidden = target.classList.toggle('hidden');
  if (chev) chev.classList.toggle('open', !isHidden);
}

function minsec(s) {
  s = Math.round(s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// =====================================================================
// EVENT SETUP
// =====================================================================
function setupEvents() {
  // Tab navigation
  qAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.tab === 'tracker' && !S.castActive) {
        toast('Start a cast from the Planner tab first.');
        return;
      }
      switchView(btn.dataset.tab);
    });
  });

  // Global parameter inputs (use event delegation on the params panel)
  q('#params-content').addEventListener('change', scheduleRecompute);
  q('#params-content').addEventListener('input',  scheduleRecompute);

  // Add / remove filter buttons
  q('#add-t1').addEventListener('click', () => {
    const prev = S.t1Filters[S.t1Filters.length - 1];
    S.t1Filters.push({ depthM: prev ? Math.min(prev.depthM + 10, S.maxDepthM) : 10, durationS: 900, marginS: 60 });
    renderFilterRows();
    scheduleRecompute();
  });
  q('#remove-t1').addEventListener('click', () => {
    if (S.t1Filters.length > 0) { S.t1Filters.pop(); renderFilterRows(); scheduleRecompute(); }
  });
  q('#add-t2').addEventListener('click', () => {
    const prev = S.t2Filters[S.t2Filters.length - 1];
    S.t2Filters.push({ depthM: prev ? Math.min(prev.depthM + 10, S.maxDepthM) : 50, durationS: 900, marginS: 60 });
    renderFilterRows();
    scheduleRecompute();
  });
  q('#remove-t2').addEventListener('click', () => {
    if (S.t2Filters.length > 0) { S.t2Filters.pop(); renderFilterRows(); scheduleRecompute(); }
  });

  // Collapse toggles on params panel
  setupCollapseHandlers();
}

// =====================================================================
// FORM POPULATION FROM STATE (on load)
// =====================================================================
function populateFormFromState() {
  q('#inp-max-depth').value       = S.maxDepthM;
  q('#inp-vmax').value            = S.vMax;
  q('#inp-accel').value           = S.accel;
  q('#inp-deploy-delay').value    = minsec(S.deployDelayS);
  q('#inp-bottom-dwell').value    = minsec(S.bottomDwellS);
  q('#inp-homing-time').value     = minsec(S.homingTimeS);
  q('#inp-actuation-buffer').value= minsec(S.actuationBufferS);
  q('#inp-vhard-max').value       = S.vHardMax;
  q('#inp-clock-reset').checked   = S.clockReset;
  renderFilterRows();
}

// =====================================================================
// INIT
// =====================================================================
function init() {
  loadState();
  populateFormFromState();
  recompute();
  renderPlannerResults();
  setupEvents();
  setupCollapseHandlers();

  // Service worker registration
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }

  // Redraw chart on orientation / resize
  window.addEventListener('resize', () => {
    if (S.computed && S.currentView === 'planner') {
      drawChart('planner-chart', {
        waypoints: buildWaypoints(S.filterStops, S.timeline),
        t1Stops: S.filterStops.filter(f => f.filterType === 1),
        t2Stops: S.filterStops.filter(f => f.filterType === 2),
        actualTrace: [], currentPos: null,
        maxDepthM: S.maxDepthM, totalTimeS: S.totalCastTimeS,
      });
    }
    if (S.castActive && S.currentView === 'tracker') updateTrackerDisplay();
  });
}

window.addEventListener('DOMContentLoaded', init);
