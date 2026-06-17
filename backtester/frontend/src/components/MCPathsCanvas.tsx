/**
 * MCPathsCanvas — high-performance canvas-based Monte Carlo equity paths chart.
 *
 * Renders up to 1000+ equity paths using HTML Canvas (not SVG/Recharts),
 * giving the multicolored "spaghetti fan" look from the reference image.
 *
 * Each path is colored on a hue spectrum based on its return:
 *   deep red (large loss) → orange → yellow → green → cyan (large gain)
 *
 * Features:
 *  - Hover nearest path → tooltip with run metrics
 *  - Click path → pin selection, show stats panel
 *  - Baseline shown as thick blue dashed line
 *  - Capital reference horizontal line
 *  - Live / incremental drawing: new runs are appended without full redraw
 */
import React, {
  useRef, useEffect, useLayoutEffect, useCallback, useMemo, useState,
} from 'react';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MCRun {
  run_idx:    number;
  return_pct: number;
  max_dd_pct: number;
  sharpe:     number;
  win_rate:   number;
  equity:     number[]; // ≤200 points (same length for all runs)
}

interface Props {
  runs:           MCRun[];
  baselineEquity: number[];
  timestamps:     string[];      // full timestamp list (used for x-axis labels)
  tsIndices:      number[];      // which positions in `timestamps` each equity point maps to
  capital:        number;
  currency:       string;
  locale:         string;
  height?:        number;
  /** When true, skip the "draw all at once" flash — runs were appended incrementally */
  isLive?:        boolean;
  totalExpected?: number;        // for progress label
  /** Crisis / dark-mode: dark background, warm path colours, dark tooltip */
  darkMode?:      boolean;
}

// ─── Color helpers ────────────────────────────────────────────────────────────

function returnToHSL(ret: number, alpha = 0.28): string {
  // Map return% to hue: -50%→0° (red), 0%→55° (yellow), +50%→160° (teal)
  const t = Math.max(0, Math.min(1, (ret + 50) / 100));
  const hue = Math.round(t * 160);
  return `hsla(${hue},80%,48%,${alpha})`;
}
function returnToSolid(ret: number): string {
  const t = Math.max(0, Math.min(1, (ret + 50) / 100));
  const hue = Math.round(t * 160);
  return `hsl(${hue},80%,45%)`;
}

// ─── Canvas chart component ───────────────────────────────────────────────────

const PAD = { top: 24, right: 16, bottom: 36, left: 72 };

export default function MCPathsCanvas({
  runs, baselineEquity, timestamps, tsIndices, capital,
  currency, locale, height = 400, isLive = false, totalExpected, darkMode = false,
}: Props) {
  const canvasRef     = useRef<HTMLCanvasElement>(null);
  const containerRef  = useRef<HTMLDivElement>(null);
  const drawnCountRef = useRef(0);    // incremental draw tracking
  const widthRef      = useRef(800);

  const [hovered,   setHovered]   = useState<number | null>(null);
  const [selected,  setSelected]  = useState<number | null>(null);
  const [mousePos,  setMousePos]  = useState<{ x: number; y: number } | null>(null);
  const [deltaMode, setDeltaMode] = useState(false);  // show stressed−baseline delta

  // ── Delta transformation (stressed equity minus baseline at each point) ─────
  const displayRuns = useMemo(() => {
    if (!deltaMode || baselineEquity.length === 0) return runs;
    return runs.map(r => ({
      ...r,
      equity: r.equity.map((v, i) => {
        const base = baselineEquity[i] ?? baselineEquity[baselineEquity.length - 1];
        return base > 0 ? ((v - base) / base) * 100 : 0;  // % delta vs baseline
      }),
    }));
  }, [runs, baselineEquity, deltaMode]);

  const displayBaseline = useMemo(() =>
    deltaMode ? baselineEquity.map(() => 0) : baselineEquity,
    [baselineEquity, deltaMode]
  );

  const displayCapital = deltaMode ? 0 : capital;

  // ── Derived bounds ──────────────────────────────────────────────────────────
  const { minY, maxY } = useMemo(() => {
    const src = deltaMode ? displayRuns : runs;
    let lo = displayCapital, hi = displayCapital;
    for (const r of src) for (const v of r.equity) { if (v < lo) lo = v; if (v > hi) hi = v; }
    for (const v of displayBaseline) { if (v < lo) lo = v; if (v > hi) hi = v; }
    const pad = (hi - lo) * 0.08 || (deltaMode ? 2 : capital * 0.05);
    return { minY: lo - pad, maxY: hi + pad };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayRuns, displayBaseline, displayCapital, deltaMode]);

  const nPoints = useMemo(() =>
    displayRuns.length > 0 ? displayRuns[0].equity.length : displayBaseline.length,
    [displayRuns, displayBaseline]
  );

  // ── Scale helpers (use closure over current width) ──────────────────────────
  const scaleX = useCallback((i: number, W: number) =>
    PAD.left + (i / Math.max(nPoints - 1, 1)) * (W - PAD.left - PAD.right),
    [nPoints]
  );
  const scaleY = useCallback((v: number, H: number) =>
    PAD.top + (1 - (v - minY) / (maxY - minY)) * (H - PAD.top - PAD.bottom),
    [minY, maxY]
  );

  // ── Draw axes + grid (called once per full redraw) ──────────────────────────
  const drawAxes = useCallback((ctx: CanvasRenderingContext2D, W: number, H: number) => {
    // Background
    ctx.fillStyle = darkMode ? '#080c10' : '#ffffff';
    ctx.fillRect(0, 0, W, H);

    // Grid lines
    ctx.strokeStyle = darkMode ? '#141c24' : '#f1f5f9';
    ctx.lineWidth   = 1;
    const gridRows = 5;
    for (let r = 0; r <= gridRows; r++) {
      const y = PAD.top + (r / gridRows) * (H - PAD.top - PAD.bottom);
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
    }
    const gridCols = 6;
    for (let c = 0; c <= gridCols; c++) {
      const x = PAD.left + (c / gridCols) * (W - PAD.left - PAD.right);
      ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, H - PAD.bottom); ctx.stroke();
    }

    // Y axis labels
    ctx.fillStyle  = darkMode ? '#6b7280' : '#94a3b8';
    ctx.font       = '11px system-ui, sans-serif';
    ctx.textAlign  = 'right';
    for (let r = 0; r <= gridRows; r++) {
      const v = maxY - (r / gridRows) * (maxY - minY);
      const y = PAD.top + (r / gridRows) * (H - PAD.top - PAD.bottom);
      const label = deltaMode
        ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
        : Math.abs(v) >= 1000
          ? `${currency}${(v / 1000).toFixed(1)}k`
          : `${currency}${v.toFixed(0)}`;
      ctx.fillText(label, PAD.left - 6, y + 4);
    }

    // X axis labels (dates)
    ctx.textAlign = 'center';
    ctx.fillStyle = darkMode ? '#4b5563' : '#94a3b8';
    const xLabels = Math.min(6, tsIndices.length);
    for (let c = 0; c <= xLabels; c++) {
      const di   = Math.round((c / xLabels) * (nPoints - 1));
      const tsI  = tsIndices[di] ?? 0;
      const label = (timestamps[tsI] ?? '').slice(0, 10);
      const x    = scaleX(di, W);
      ctx.fillText(label, x, H - 4);
    }

    // Capital reference line
    const capY = scaleY(capital, H);
    ctx.strokeStyle  = darkMode ? '#1e3a5f' : '#cbd5e1';
    ctx.lineWidth    = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(PAD.left, capY); ctx.lineTo(W - PAD.right, capY); ctx.stroke();
    ctx.setLineDash([]);

    // Loss zone tint in dark mode
    if (darkMode) {
      const lossGrad = ctx.createLinearGradient(0, capY, 0, H - PAD.bottom);
      lossGrad.addColorStop(0, 'rgba(220,38,38,0.04)');
      lossGrad.addColorStop(1, 'rgba(220,38,38,0)');
      ctx.fillStyle = lossGrad;
      ctx.fillRect(PAD.left, capY, W - PAD.left - PAD.right, Math.max(0, H - PAD.bottom - capY));
    }
  }, [darkMode, maxY, minY, currency, tsIndices, timestamps, nPoints, capital, scaleX, scaleY]);

  // ── Draw a single run path ──────────────────────────────────────────────────
  const drawRun = useCallback((
    ctx: CanvasRenderingContext2D,
    run: MCRun,
    W: number, H: number,
    highlight: boolean,
    dimmed: boolean,
  ) => {
    const alpha = highlight ? 1.0
      : dimmed   ? (darkMode ? 0.04 : 0.06)
      : (darkMode ? 0.38 : 0.28);
    ctx.strokeStyle = highlight
      ? '#f97316'
      : returnToHSL(run.return_pct, alpha);
    ctx.lineWidth   = highlight ? 2.5 : dimmed ? 0.5 : (darkMode ? 1.0 : 0.9);
    ctx.beginPath();
    run.equity.forEach((v, i) => {
      const x = scaleX(i, W), y = scaleY(v, H);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  }, [darkMode, scaleX, scaleY]);

  // ── Draw baseline ──────────────────────────────────────────────────────────
  const drawBaseline = useCallback((ctx: CanvasRenderingContext2D, W: number, H: number) => {
    if (!displayBaseline.length) return;
    ctx.strokeStyle = deltaMode ? '#94a3b8' : '#3b82f6';
    ctx.lineWidth   = deltaMode ? 1.5 : 2.5;
    ctx.setLineDash([8, 4]);
    ctx.beginPath();
    const len = Math.min(displayBaseline.length, nPoints);
    for (let i = 0; i < len; i++) {
      const x = scaleX(i, W), y = scaleY(displayBaseline[i], H);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    // Zero line in delta mode
    if (deltaMode) {
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth   = 1;
      ctx.beginPath();
      const zeroY = scaleY(0, H);
      ctx.moveTo(PAD.left, zeroY); ctx.lineTo(W - PAD.right, zeroY);
      ctx.stroke();
    }
  }, [displayBaseline, nPoints, scaleX, scaleY, deltaMode]);

  // ── Full redraw (used on selection/hover change, or initial static render) ──
  const fullRedraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const W = widthRef.current;
    const H = height;
    const ctx = canvas.getContext('2d')!;
    const dpr = window.devicePixelRatio || 1;
    ctx.save();
    ctx.scale(dpr, dpr);

    drawAxes(ctx, W, H);

    const hasSel  = selected !== null;
    const hasHov  = hovered  !== null;
    const focused = selected ?? hovered;

    displayRuns.forEach((run, ri) => {
      if (ri === focused) return;
      drawRun(ctx, run, W, H, false, (hasSel || hasHov) && ri !== focused);
    });
    if (focused !== null && displayRuns[focused]) {
      drawRun(ctx, displayRuns[focused], W, H, true, false);
    }
    drawBaseline(ctx, W, H);
    ctx.restore();
  }, [displayRuns, selected, hovered, height, drawAxes, drawRun, drawBaseline]);

  // ── Incremental draw for live streaming ────────────────────────────────────
  const incrementalDraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const W   = widthRef.current;
    const H   = height;
    const ctx = canvas.getContext('2d')!;
    const dpr = window.devicePixelRatio || 1;
    ctx.save();
    ctx.scale(dpr, dpr);

    if (drawnCountRef.current === 0) drawAxes(ctx, W, H);

    for (let ri = drawnCountRef.current; ri < displayRuns.length; ri++) {
      drawRun(ctx, displayRuns[ri], W, H, false, false);
    }
    drawnCountRef.current = displayRuns.length;

    // Always redraw baseline on top
    drawBaseline(ctx, W, H);
    ctx.restore();
  }, [displayRuns, height, drawAxes, drawRun, drawBaseline]);

  // ── Initial sizing (synchronous, before any draw calls) ────────────────────
  useLayoutEffect(() => {
    const el  = containerRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;
    const W   = el.clientWidth || 800;
    const dpr = window.devicePixelRatio || 1;
    widthRef.current   = W;
    canvas.width       = W   * dpr;
    canvas.height      = height * dpr;
    canvas.style.width  = `${W}px`;
    canvas.style.height = `${height}px`;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Resize observer ─────────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const W   = entry.contentRect.width;
      const dpr = window.devicePixelRatio || 1;
      widthRef.current = W;
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width  = W   * dpr;
        canvas.height = height * dpr;
        canvas.style.width  = `${W}px`;
        canvas.style.height = `${height}px`;
      }
      drawnCountRef.current = 0;
      fullRedraw();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [height, fullRedraw]);

  // ── Trigger draw when runs change ──────────────────────────────────────────
  useEffect(() => {
    if (selected !== null || hovered !== null) {
      fullRedraw();
      drawnCountRef.current = displayRuns.length;
    } else if (isLive) {
      incrementalDraw();
    } else {
      drawnCountRef.current = 0;
      fullRedraw();
      drawnCountRef.current = displayRuns.length;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.length, deltaMode]);

  // ── Redraw when selection / hover / deltaMode changes ────────────────────
  useEffect(() => {
    drawnCountRef.current = 0;
    fullRedraw();
    drawnCountRef.current = displayRuns.length;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, hovered, deltaMode]);

  // ── Mouse hit-testing ──────────────────────────────────────────────────────
  const findNearestRun = useCallback((
    clientX: number, clientY: number, rect: DOMRect,
  ): number | null => {
    const W  = widthRef.current;
    const H  = height;
    const cx = (clientX - rect.left);
    const cy = (clientY - rect.top);

    const ratio = (cx - PAD.left) / (W - PAD.left - PAD.right);
    const di    = Math.round(ratio * (nPoints - 1));
    if (di < 0 || di >= nPoints) return null;

    let nearest: number | null = null;
    let minDist = 28;

    displayRuns.forEach((run, ri) => {
      const v = run.equity[di];
      if (v == null) return;
      const y    = scaleY(v, H);
      const dist = Math.abs(cy - y);
      if (dist < minDist) { minDist = dist; nearest = ri; }
    });
    return nearest;
  }, [displayRuns, nPoints, height, scaleY]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    const near = findNearestRun(e.clientX, e.clientY, rect);
    setHovered(near !== selected ? near : null);
  }, [findNearestRun, selected]);

  const handleMouseLeave = useCallback(() => {
    setHovered(null);
    setMousePos(null);
  }, []);

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const near = findNearestRun(e.clientX, e.clientY, rect);
    setSelected(prev => (prev === near || near === null) ? null : near);
    setHovered(null);
  }, [findNearestRun]);

  // ── Tooltip run (uses original runs for display metrics) ────────────────
  const tooltipRun = hovered !== null ? runs[hovered] : selected !== null ? runs[selected] : null;

  const dm = darkMode;

  return (
    <div ref={containerRef} className="relative w-full select-none"
      style={{ height, borderRadius: dm ? 16 : 0, overflow: dm ? 'hidden' : undefined, background: dm ? '#080c10' : undefined }}>
      {/* Delta mode toggle */}
      {baselineEquity.length > 0 && !isLive && (
        <button
          onClick={() => setDeltaMode(d => !d)}
          className={`absolute top-1 right-1 z-10 px-2.5 py-1 rounded-lg text-[10px] font-semibold border transition-all ${
            deltaMode
              ? 'bg-indigo-600 text-white border-indigo-600'
              : dm
                ? 'bg-[#141c24] text-gray-400 border-[#1e293b] hover:border-orange-700 hover:text-orange-400'
                : 'bg-white text-gray-500 border-gray-200 hover:border-indigo-300 hover:text-indigo-600'
          }`}
          title="Toggle: absolute equity vs % impact vs baseline"
        >
          {deltaMode ? 'Δ% vs baseline' : 'Absolute equity'}
        </button>
      )}
      <canvas
        ref={canvasRef}
        style={{ cursor: hovered !== null ? 'pointer' : 'crosshair', display: 'block' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
      />

      {/* Tooltip */}
      {tooltipRun && mousePos && (
        <div
          className="pointer-events-none absolute z-20 rounded-xl shadow-lg px-3 py-2 text-xs"
          style={{
            left: mousePos.x + (mousePos.x > (containerRef.current?.offsetWidth ?? 400) * 0.6 ? -175 : 14),
            top:  Math.max(4, mousePos.y - 70),
            minWidth: 160,
            background: dm ? '#0f172a' : '#fff',
            border: `1px solid ${dm ? '#1e293b' : '#e5e7eb'}`,
            color: dm ? '#e2e8f0' : undefined,
            boxShadow: dm ? '0 4px 16px rgba(0,0,0,0.6)' : undefined,
          }}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ background: returnToSolid(tooltipRun.return_pct) }} />
            <span className="font-bold" style={{ color: dm ? '#f1f5f9' : '#374151' }}>Run #{tooltipRun.run_idx}</span>
            {selected !== null && hovered === null && (
              <span className="ml-auto text-orange-500 font-semibold">● pinned</span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <span style={{ color: dm ? '#6b7280' : '#9ca3af' }}>Return</span>
            <span className={`font-bold text-right ${tooltipRun.return_pct >= 0 ? 'text-green-500' : 'text-red-400'}`}>
              {tooltipRun.return_pct >= 0 ? '+' : ''}{tooltipRun.return_pct.toFixed(2)}%
            </span>
            <span style={{ color: dm ? '#6b7280' : '#9ca3af' }}>Max DD</span>
            <span className="font-semibold text-right text-orange-400">{tooltipRun.max_dd_pct.toFixed(2)}%</span>
            <span style={{ color: dm ? '#6b7280' : '#9ca3af' }}>Sharpe</span>
            <span className="font-semibold text-right" style={{ color: dm ? '#d1d5db' : '#374151' }}>{tooltipRun.sharpe.toFixed(3)}</span>
            <span style={{ color: dm ? '#6b7280' : '#9ca3af' }}>Win %</span>
            <span className="font-semibold text-right" style={{ color: dm ? '#d1d5db' : '#374151' }}>{tooltipRun.win_rate.toFixed(1)}%</span>
          </div>
          {selected === null && (
            <p className="mt-1.5 text-[10px] italic" style={{ color: dm ? '#374151' : '#9ca3af' }}>Click to pin</p>
          )}
        </div>
      )}

      {/* Selected run detail chip */}
      {selected !== null && !mousePos && runs[selected] && (
        <div className={`absolute top-2 right-2 z-10 rounded-xl px-2.5 py-1.5 text-xs shadow ${
          dm ? 'bg-orange-900/40 border border-orange-700' : 'bg-orange-50 border border-orange-200'
        }`}>
          <span className="font-bold text-orange-400">Run #{runs[selected].run_idx} pinned</span>
          <span className={`ml-2 cursor-pointer ${dm ? 'text-gray-500 hover:text-red-400' : 'text-gray-400 hover:text-red-500'}`}
            onClick={() => setSelected(null)}>✕</span>
        </div>
      )}

      {/* Live progress badge */}
      {isLive && totalExpected != null && (
        <div className={`absolute bottom-10 left-[76px] text-[11px] ${dm ? 'text-gray-600' : 'text-gray-400'}`}>
          {runs.length} / {totalExpected} paths
        </div>
      )}

      {/* Legend */}
      <div className={`absolute top-2 left-[76px] flex items-center gap-3 text-[10px] ${dm ? 'text-gray-600' : 'text-gray-400'}`}>
        <span className="flex items-center gap-1">
          <span className="w-6 border-t-2 border-blue-400 border-dashed inline-block" /> Baseline
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-full inline-block" style={{ background: returnToSolid(-40) }} /> Loss
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-full inline-block" style={{ background: returnToSolid(40) }} /> Gain
        </span>
      </div>
    </div>
  );
}
