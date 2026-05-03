/* ===================================================================
   chart.js — ChronoCaster PWA
   Canvas-based depth-time chart renderer (no external dependencies)
   =================================================================== */
'use strict';

/**
 * Draw the depth-time chart on a canvas element.
 *
 * @param {string} canvasId  ID of the <canvas> element
 * @param {object} data
 *   data.waypoints    [{timeS, depthM, label}]  — planned path
 *   data.t1Stops      FilterStop[]              — downcast filter markers
 *   data.t2Stops      FilterStop[]              — upcast filter markers
 *   data.actualTrace  [{elapsedS, depthM, label}] — recorded trace (may be empty)
 *   data.currentPos   {elapsedS, depthM, color} | null — live position
 *   data.maxDepthM    number
 *   data.totalTimeS   number
 */
function drawChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const { waypoints = [], t1Stops = [], t2Stops = [],
          actualTrace = [], currentPos = null,
          maxDepthM = 100, totalTimeS = 3600 } = data;

  // ---------- DPI-aware sizing ----------
  const dpr = window.devicePixelRatio || 1;
  const W   = canvas.clientWidth  || 400;
  const H   = canvas.clientHeight || 300;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  // ---------- Margins & scales ----------
  const ML = 54, MR = 14, MT = 18, MB = 54;
  const CW = Math.max(W - ML - MR, 10);
  const CH = Math.max(H - MT - MB, 10);

  const xMax = (totalTimeS || 600) * 1.05;
  // Add 15% padding above the surface so the 0 m line sits well inside the chart
  // area, leaving enough room for surface markers, dots, and labels.
  const yPad = (maxDepthM || 100) * 0.15;
  const yMin = -yPad;
  const yMax = (maxDepthM  || 100) * 1.08;
  const yRange = yMax - yMin;

  const sx = t => ML + (t / xMax) * CW;                         // seconds → pixel X
  const sy = d => MT + ((d - yMin) / yRange) * CH;              // metres  → pixel Y (0 is ~8% from top)

  // ---------- Background ----------
  ctx.fillStyle = '#0d1b2a';
  ctx.fillRect(0, 0, W, H);

  // ---------- Grid & Axes ----------
  ctx.save();
  ctx.font = `${10}px monospace`;

  // Y-axis grid  (depth) — iterate over the visible range (yMin → yMax)
  const yStep = niceStep(yMax, 7);
  for (let d = Math.ceil(yMin / yStep) * yStep; d <= yMax + yStep * 0.01; d += yStep) {
    const y = sy(d);
    if (y < MT || y > MT + CH + 1) continue;
    ctx.strokeStyle = '#1e3a5f';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(ML, y); ctx.lineTo(ML + CW, y); ctx.stroke();
    ctx.fillStyle = '#8ec8f6';
    ctx.textAlign = 'right';
    ctx.fillText(d.toFixed(0), ML - 4, y + 3.5);
  }

  // X-axis grid  (time, every 5 min = 300 s)
  const xStep = 300;
  for (let t = 0; t <= xMax + xStep * 0.01; t += xStep) {
    const x = sx(t);
    if (x < ML - 1 || x > ML + CW + 1) continue;
    ctx.strokeStyle = '#1e3a5f';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, MT); ctx.lineTo(x, MT + CH); ctx.stroke();
    // Rotated time label
    ctx.save();
    ctx.fillStyle = '#8ec8f6';
    ctx.textAlign = 'right';
    ctx.translate(x, MT + CH + 8);
    ctx.rotate(-Math.PI / 4);
    ctx.fillText(fmtTime(t), 0, 0);
    ctx.restore();
  }

  // Axis border
  ctx.strokeStyle = '#4fa3e0';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(ML, MT, CW, CH);

  // Axis labels
  ctx.fillStyle = '#8ec8f6';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Time from T=0', ML + CW / 2, H - 2);
  ctx.save();
  ctx.translate(10, MT + CH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Depth (m)', 0, 0);
  ctx.restore();

  ctx.restore();

  // ---------- Clip to chart area for path drawing ----------
  ctx.save();
  ctx.beginPath();
  ctx.rect(ML, MT, CW, CH);
  ctx.clip();

  // --- Planned CTD path ---
  if (waypoints.length > 1) {
    ctx.beginPath();
    ctx.strokeStyle = '#4fa3e0';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    waypoints.forEach((w, i) => {
      const x = sx(w.timeS), y = sy(w.depthM);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // --- Actual trace ---
  if (actualTrace.length > 1) {
    ctx.beginPath();
    ctx.strokeStyle = '#888888';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    actualTrace.forEach((p, i) => {
      const x = sx(p.elapsedS), y = sy(p.depthM);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Milestone diamonds
    actualTrace.filter(p => p.label).forEach(p => {
      const x = sx(p.elapsedS), y = sy(p.depthM);
      ctx.fillStyle = '#aaaaaa';
      drawDiamond(ctx, x, y, 5);
    });
  }

  // --- T1 filter markers (▼ green) ---
  t1Stops.forEach(fs => {
    const x = sx(fs.presetDelayS), y = sy(fs.depthM);
    ctx.fillStyle = '#28a745';
    drawTriangle(ctx, x, y, 8, false);
    ctx.fillStyle = '#28a745';
    ctx.font = 'bold 10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(fs.filterId, x + 10, y + 4);
  });

  // --- T2 filter markers (▲ orange) ---
  t2Stops.forEach(fs => {
    const x = sx(fs.presetDelayS), y = sy(fs.depthM);
    ctx.fillStyle = '#fd7e14';
    drawTriangle(ctx, x, y, 8, true);
    ctx.fillStyle = '#fd7e14';
    ctx.font = 'bold 10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(fs.filterId, x + 10, y + 4);
  });

  // --- Current position dot ---
  if (currentPos) {
    const x = sx(currentPos.elapsedS);
    const y = sy(currentPos.depthM);
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.fillStyle = currentPos.color || '#28a745';
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2.5;
    ctx.stroke();
  }

  ctx.restore(); // end clip
}

// =====================================================================
// Shape helpers
// =====================================================================

/** Downward triangle (upward = false) or upward triangle (upward = true) */
function drawTriangle(ctx, x, y, r, upward) {
  ctx.beginPath();
  if (upward) {
    ctx.moveTo(x,     y - r);
    ctx.lineTo(x - r, y + r * 0.6);
    ctx.lineTo(x + r, y + r * 0.6);
  } else {
    ctx.moveTo(x,     y + r);
    ctx.lineTo(x - r, y - r * 0.6);
    ctx.lineTo(x + r, y - r * 0.6);
  }
  ctx.closePath();
  ctx.fill();
}

function drawDiamond(ctx, x, y, r) {
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y);
  ctx.lineTo(x, y + r);
  ctx.lineTo(x - r, y);
  ctx.closePath();
  ctx.fill();
}

function niceStep(maxVal, targetTicks) {
  const raw = maxVal / targetTicks;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / pow;
  let rounded;
  if (norm < 1.5)      rounded = 1;
  else if (norm < 3.5) rounded = 2;
  else if (norm < 7.5) rounded = 5;
  else                 rounded = 10;
  return Math.max(rounded * pow, 1);
}
