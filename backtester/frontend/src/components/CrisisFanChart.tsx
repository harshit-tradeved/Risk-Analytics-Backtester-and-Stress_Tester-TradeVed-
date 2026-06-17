import React from 'react';

interface FanRun {
  equity: number[];
  return_pct: number;
}

interface Props {
  runs: FanRun[];
  baselineEquity: number[];
  capital: number;
  currency?: string;
  height?: number;
}

function quantile(arr: number[], p: number): number {
  const s = [...arr].sort((a, b) => a - b);
  const i = (p / 100) * (s.length - 1);
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}

function fmtY(v: number, currency: string): string {
  if (Math.abs(v) >= 1e6) return `${currency}${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1000) return `${currency}${(v / 1000).toFixed(0)}k`;
  return `${currency}${v.toFixed(0)}`;
}

export default function CrisisFanChart({ runs, baselineEquity, capital, currency = '$', height = 340 }: Props) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || runs.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = height;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext('2d')!;
    ctx.scale(dpr, dpr);

    // Align all run equity arrays to same length
    const maxLen = Math.max(...runs.map(r => r.equity.length), baselineEquity.length);
    if (maxLen < 2) return;

    const get = (arr: number[], i: number) => arr[Math.min(i, arr.length - 1)] ?? capital;

    // Compute percentile bands per time step
    const bands = { p5: [] as number[], p25: [] as number[], p50: [] as number[], p75: [] as number[], p95: [] as number[] };
    for (let t = 0; t < maxLen; t++) {
      const vals = runs.map(r => get(r.equity, t)).filter(Number.isFinite);
      if (vals.length === 0) continue;
      bands.p5.push(quantile(vals, 5));
      bands.p25.push(quantile(vals, 25));
      bands.p50.push(quantile(vals, 50));
      bands.p75.push(quantile(vals, 75));
      bands.p95.push(quantile(vals, 95));
    }

    const n = bands.p50.length;
    if (n < 2) return;

    // Y range
    const allV = [...bands.p5, ...bands.p95, ...baselineEquity.filter(Number.isFinite)];
    const rawMin = Math.min(...allV);
    const rawMax = Math.max(...allV);
    const pad5   = (rawMax - rawMin) * 0.06;
    const minV   = rawMin - pad5;
    const maxV   = rawMax + pad5;
    const rng    = maxV - minV || 1;

    const pad = { t: 24, b: 40, l: 62, r: 16 };
    const pW = W - pad.l - pad.r;
    const pH = H - pad.t - pad.b;

    const xOf = (i: number) => pad.l + (i / (n - 1)) * pW;
    const yOf = (v: number) => pad.t + (1 - (v - minV) / rng) * pH;

    // ── Background
    ctx.fillStyle = '#080c10';
    ctx.fillRect(0, 0, W, H);

    // ── Grid
    const nGrid = 5;
    for (let i = 0; i <= nGrid; i++) {
      const v = minV + rng * (i / nGrid);
      const y = yOf(v);
      ctx.beginPath();
      ctx.strokeStyle = '#141c24';
      ctx.lineWidth = 1;
      ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y);
      ctx.stroke();
    }

    // ── Capital "break-even" line
    const yCapital = yOf(capital);
    ctx.beginPath(); ctx.setLineDash([4, 4]); ctx.strokeStyle = '#1e3a5f'; ctx.lineWidth = 1;
    ctx.moveTo(pad.l, yCapital); ctx.lineTo(W - pad.r, yCapital);
    ctx.stroke(); ctx.setLineDash([]);

    // Helper: draw closed polygon path
    const polygon = (top: number[], bottom: number[]) => {
      ctx.beginPath();
      top.forEach((v, i) => i === 0 ? ctx.moveTo(xOf(i), yOf(v)) : ctx.lineTo(xOf(i), yOf(v)));
      [...bottom].reverse().forEach((v, i) => ctx.lineTo(xOf(bottom.length - 1 - i), yOf(v)));
      ctx.closePath();
    };

    // ── P5–P95 outer band
    polygon(bands.p5, bands.p95);
    ctx.fillStyle = 'rgba(234,88,12,0.07)';
    ctx.fill();

    // ── P25–P75 inner band
    polygon(bands.p25, bands.p75);
    ctx.fillStyle = 'rgba(234,88,12,0.16)';
    ctx.fill();

    // ── Band edge lines (P5 / P95)
    ([bands.p5, bands.p95] as number[][]).forEach(band => {
      ctx.beginPath();
      band.forEach((v, i) => i === 0 ? ctx.moveTo(xOf(i), yOf(v)) : ctx.lineTo(xOf(i), yOf(v)));
      ctx.strokeStyle = 'rgba(234,88,12,0.3)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.stroke(); ctx.setLineDash([]);
    });

    // ── Baseline equity
    if (baselineEquity.length > 1) {
      const bLen = baselineEquity.length;
      ctx.beginPath();
      baselineEquity.forEach((v, i) => {
        const x = pad.l + (i / (bLen - 1)) * pW;
        i === 0 ? ctx.moveTo(x, yOf(v)) : ctx.lineTo(x, yOf(v));
      });
      ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
      ctx.stroke(); ctx.setLineDash([]);
    }

    // ── P50 median (main orange line)
    ctx.beginPath();
    bands.p50.forEach((v, i) => i === 0 ? ctx.moveTo(xOf(i), yOf(v)) : ctx.lineTo(xOf(i), yOf(v)));
    ctx.strokeStyle = '#f97316'; ctx.lineWidth = 2.5;
    ctx.stroke();

    // ── Shaded "loss zone" below capital
    const lossGrad = ctx.createLinearGradient(0, yCapital, 0, H - pad.b);
    lossGrad.addColorStop(0, 'rgba(220,38,38,0.06)');
    lossGrad.addColorStop(1, 'rgba(220,38,38,0)');
    ctx.fillStyle = lossGrad;
    ctx.fillRect(pad.l, yCapital, pW, H - pad.b - yCapital);

    // ── Y axis labels
    ctx.fillStyle = '#4b5563'; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
    for (let i = 0; i <= nGrid; i++) {
      const v = minV + rng * (i / nGrid);
      ctx.fillText(fmtY(v, currency), pad.l - 6, yOf(v) + 3.5);
    }

    // ── Break-even label
    ctx.fillStyle = '#1d4ed8'; ctx.font = '9px system-ui'; ctx.textAlign = 'left';
    ctx.fillText('capital', pad.l + 4, yCapital - 4);

    // ── Legend (top-right)
    const lx = W - pad.r - 120;
    const ly = pad.t + 4;
    ctx.font = '9px system-ui'; ctx.textAlign = 'left';

    // Orange rect = P50
    ctx.fillStyle = '#f97316';
    ctx.fillRect(lx, ly, 16, 2.5);
    ctx.fillStyle = '#6b7280'; ctx.fillText('Median (P50)', lx + 20, ly + 4);

    // Shaded box = P25-P75
    ctx.fillStyle = 'rgba(234,88,12,0.3)';
    ctx.fillRect(lx, ly + 12, 16, 7);
    ctx.fillStyle = '#6b7280'; ctx.fillText('P25–P75 band', lx + 20, ly + 18);

    // Blue dash = baseline
    ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(lx, ly + 27); ctx.lineTo(lx + 16, ly + 27); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#6b7280'; ctx.fillText('Historical', lx + 20, ly + 30);

  }, [runs, baselineEquity, capital, currency, height]);

  // Summary stats
  const finalEquities = runs.map(r => r.equity[r.equity.length - 1] ?? capital).filter(Number.isFinite);
  const p50Final = finalEquities.length ? quantile(finalEquities, 50) : capital;
  const p5Final  = finalEquities.length ? quantile(finalEquities, 5)  : capital;
  const p95Final = finalEquities.length ? quantile(finalEquities, 95) : capital;
  const pct = (v: number) => ((v - capital) / capital * 100).toFixed(1);
  const sgn = (v: number) => (v >= 0 ? '+' : '') + v;

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: '#080c10' }}>
      {/* Stat strip */}
      <div className="flex gap-0 border-b border-[#141c24]">
        {[
          { label: 'P50 outcome', val: `${sgn(parseFloat(pct(p50Final)))}%`, color: p50Final >= capital ? '#4ade80' : '#f87171' },
          { label: 'P5 (tail loss)', val: `${sgn(parseFloat(pct(p5Final)))}%`, color: '#f87171' },
          { label: 'P95 (upside)', val: `${sgn(parseFloat(pct(p95Final)))}%`, color: '#4ade80' },
          { label: 'Paths', val: String(runs.length), color: '#9ca3af' },
        ].map(({ label, val, color }) => (
          <div key={label} className="flex-1 px-4 py-2.5 border-r border-[#141c24] last:border-r-0">
            <p className="text-[9px] uppercase tracking-widest mb-0.5" style={{ color: '#4b5563' }}>{label}</p>
            <p className="text-sm font-bold tabular-nums" style={{ color }}>{val}</p>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div ref={containerRef}>
        <canvas ref={canvasRef} style={{ width: '100%', height, display: 'block' }} />
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-[#141c24] flex gap-4 text-[9px]" style={{ color: '#374151' }}>
        <span>Orange band = P25–P75 range · Dashed borders = P5/P95 tails · Orange line = median path · Blue = historical baseline · Red zone = below starting capital</span>
      </div>
    </div>
  );
}
