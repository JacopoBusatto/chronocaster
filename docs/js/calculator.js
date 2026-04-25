/* ===================================================================
   calculator.js — ChronoCaster PWA
   Exact JavaScript port of calculator.py
   =================================================================== */
'use strict';

/**
 * Travel time for a symmetric trapezoidal velocity profile.
 * @param {number} distanceM  Distance in metres (non-negative)
 * @param {number} vMax       Maximum speed m/s
 * @param {number} accel      Acceleration/deceleration m/s²
 * @returns {number} Time in seconds
 */
function travelTime(distanceM, vMax, accel) {
  if (distanceM <= 0) return 0.0;
  const rampDist = (vMax * vMax) / (2 * accel);
  const fullRampDist = 2 * rampDist;
  if (distanceM >= fullRampDist) {
    const rampTime = vMax / accel;
    const cruiseDist = distanceM - fullRampDist;
    return 2 * rampTime + cruiseDist / vMax;
  } else {
    const vPeak = Math.sqrt(accel * distanceM);
    return 2 * vPeak / accel;
  }
}

/**
 * Required winch speed to travel distanceM in timeAvailS seconds.
 * Solves v² − a·t·v + a·d = 0 (smaller positive root).
 * @returns {{status:'ok'|'impossible', vRequired:number|null, tMinS:number}}
 */
function requiredSpeed(distanceM, timeAvailS, accel) {
  if (distanceM <= 0)
    return { status: 'ok', vRequired: 0.0, tMinS: 0.0 };

  const tMin = 2.0 * Math.sqrt(distanceM / accel);
  if (timeAvailS < tMin)
    return { status: 'impossible', vRequired: null, tMinS: tMin };

  const discriminant = Math.pow(accel * timeAvailS, 2) - 4 * accel * distanceM;
  const vReq = (accel * timeAvailS - Math.sqrt(Math.max(discriminant, 0.0))) / 2.0;
  return { status: 'ok', vRequired: vReq, tMinS: tMin };
}

/**
 * Compute preset delays for all filters and build the full cast timeline.
 *
 * @param {object} p  CastParams object with fields:
 *   maxDepthM, type1Depths[], type2Depths[], vMax, accel,
 *   filterDurationS, safetyMarginS,
 *   type1FilterDurations[], type2FilterDurations[],
 *   type1SafetyMargins[], type2SafetyMargins[],
 *   deployDelayS, bottomDwellS, homingTimeS, actuationBufferS
 *
 * @returns {{ filterStops: FilterStop[], timeline: Event[], totalCastTimeS: number }}
 */
function computeDelays(p) {
  if (!p.type1Depths.length && !p.type2Depths.length)
    throw new Error('At least one filter depth must be provided.');

  const t1 = [...p.type1Depths].sort((a, b) => a - b);   // shallow → deep
  const t2 = [...p.type2Depths].sort((a, b) => b - a);   // deep → shallow

  const getDur    = (list, i) => (i < list.length) ? list[i] : p.filterDurationS;
  const getMargin = (list, i) => (i < list.length) ? list[i] : p.safetyMarginS;

  const filterStops = [];
  const timeline    = [];

  let currentDepth = 0.0;
  let currentTime  = p.deployDelayS;    // start after deck delay

  timeline.push({ label: 'Deploy', timeS: 0.0, depthM: 0.0, eventType: 'surface' });
  if (p.deployDelayS > 0)
    timeline.push({ label: 'Water entry', timeS: p.deployDelayS, depthM: 0.0, eventType: 'water_entry' });

  // ---- Downcast filter stops (T1) ----
  t1.forEach((depth, i) => {
    currentTime  += travelTime(Math.abs(depth - currentDepth), p.vMax, p.accel);
    currentDepth  = depth;

    const dur     = getDur(p.type1FilterDurations, i);
    const margin  = getMargin(p.type1SafetyMargins, i);
    const arrival   = currentTime;
    const preset    = arrival + margin;
    const departure = preset + p.homingTimeS + p.actuationBufferS + dur;

    filterStops.push({
      filterId: `D-${i + 1}`, filterType: 1, depthM: depth,
      arrivalTimeS: arrival, departureTimeS: departure,
      presetDelayS: preset, filterDurationS: dur,
    });
    timeline.push({ label: `D-${i+1} start`, timeS: arrival,    depthM: depth, eventType: 'filter_start' });
    timeline.push({ label: `D-${i+1} end`,   timeS: departure,  depthM: depth, eventType: 'filter_end'   });
    currentTime = departure;
  });

  // ---- After T1 filters: return to surface before main downcast ----
  if (t1.length > 0) {
    currentTime  += travelTime(currentDepth, p.vMax, p.accel);
    currentDepth  = 0.0;
    timeline.push({ label: 'Surface return', timeS: currentTime, depthM: 0.0, eventType: 'surface_return' });
  }

  // ---- Main downcast to bottom ----
  currentTime  += travelTime(Math.abs(p.maxDepthM - currentDepth), p.vMax, p.accel);
  currentDepth  = p.maxDepthM;

  const bottomArrive = currentTime;
  timeline.push({ label: 'Bottom', timeS: bottomArrive, depthM: p.maxDepthM, eventType: 'bottom' });

  const bottomLeave = bottomArrive + p.bottomDwellS;
  if (p.bottomDwellS > 0)
    timeline.push({ label: 'Bottom leave', timeS: bottomLeave, depthM: p.maxDepthM, eventType: 'bottom_leave' });
  currentTime = bottomLeave;

  // ---- Upcast filter stops (T2) ----
  t2.forEach((depth, i) => {
    currentTime  += travelTime(Math.abs(currentDepth - depth), p.vMax, p.accel);
    currentDepth  = depth;

    const dur     = getDur(p.type2FilterDurations, i);
    const margin  = getMargin(p.type2SafetyMargins, i);
    const arrival   = currentTime;
    const preset    = arrival + margin;
    const departure = preset + p.homingTimeS + p.actuationBufferS + dur;

    filterStops.push({
      filterId: `U-${i + 1}`, filterType: 2, depthM: depth,
      arrivalTimeS: arrival, departureTimeS: departure,
      presetDelayS: preset, filterDurationS: dur,
    });
    timeline.push({ label: `U-${i+1} start`, timeS: arrival,    depthM: depth, eventType: 'filter_start' });
    timeline.push({ label: `U-${i+1} end`,   timeS: departure,  depthM: depth, eventType: 'filter_end'   });
    currentTime = departure;
  });

  // ---- Recover to deck ----
  currentTime += travelTime(currentDepth, p.vMax, p.accel);
  timeline.push({ label: 'Recovered', timeS: currentTime, depthM: 0.0, eventType: 'surface' });

  return { filterStops, timeline, totalCastTimeS: currentTime };
}

// =====================================================================
// Formatting utilities
// =====================================================================

/** Format seconds as HH:MM:SS (handles negative with a leading −) */
function fmtTime(seconds) {
  if (isNaN(seconds) || !isFinite(seconds)) return '--:--:--';
  const neg = seconds < 0;
  seconds = Math.round(Math.abs(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const str = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return neg ? '−' + str : str;
}

/** Parse MM:SS, M:SS, H:MM:SS, or plain seconds. Returns 0 on failure. */
function parseMMSS(text) {
  text = (text || '').trim();
  const parts = text.split(':');
  try {
    if (parts.length === 3) return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseInt(parts[2]);
    if (parts.length === 2) return parseInt(parts[0]) * 60 + parseInt(parts[1]);
    return Math.round(parseFloat(text)) || 0;
  } catch (e) { return 0; }
}

/** Seconds → "H:MM:SS" (no zero-padding on hours) */
function sToHMMSS(s) {
  s = Math.round(Math.max(s, 0));
  return `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
