import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  startPipeline, getPipelineRun, submitPipelineCheckpoint,
  retryPipelineSymbol, resumePipelineRun, PipelineRunNotFoundError,
  getPipelineWalkForward, getPipelineStressDetail,
} from "../../api";
import type {
  PipelineRunState, PipelineRoundScore, PipelineStatus,
  WalkForwardDetail, StressDetailResult,
} from "../../types";

const POLL_MS = 2000;
const TOTAL_ROUNDS = 5;
const CURRENCY = "$"; // this page is crypto-USD only today
const LS_KEY = "tradeved_pipeline_run";

// ── localStorage persistence ─────────────────────────────────────────────────
function loadStoredRunId(userId: string): string | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { runId?: string; userId?: string };
    if (parsed.runId && parsed.userId === userId) return parsed.runId;
  } catch { /* corrupt entry — ignore */ }
  return null;
}
function storeRunId(runId: string, userId: string) {
  try { localStorage.setItem(LS_KEY, JSON.stringify({ runId, userId })); } catch { /* quota — ignore */ }
}
function clearStoredRunId() {
  try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
}

// ── Helpers ──────────────────────────────────────────────────────────────────
/** Backend stores checkpoint_opened_at via utcnow() (naive) — treat as UTC. */
function parseUtcMs(iso: string): number {
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  return Date.parse(hasTz ? iso : `${iso}Z`);
}

function fmtNum(v: unknown, digits = 2): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";
}
function fmtInt(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v) ? String(Math.round(v)) : "—";
}

// Rule shape mirrors StrategyIREditor's ruleToHuman (reimplemented locally on purpose).
interface IROperandLoose {
  indicator?: string;
  params?: Record<string, unknown>;
  output?: string;
  price?: string;
  value?: number | string;
}
interface IRRuleLoose {
  left?: IROperandLoose;
  operator?: string;
  right?: IROperandLoose;
}

function operandToText(op: IROperandLoose | undefined): string {
  if (!op) return "?";
  if (op.value !== undefined) return String(op.value);
  if (op.price) return op.price;
  if (op.indicator) {
    const params = op.params
      ? "(" + Object.entries(op.params).map(([k, v]) => `${k}=${v}`).join(", ") + ")"
      : "";
    const output = op.output ? `.${op.output}` : "";
    return `${op.indicator.toUpperCase()}${params}${output}`;
  }
  return JSON.stringify(op);
}

const OP_MAP: Record<string, string> = {
  cross_above: "crosses above",
  cross_below: "crosses below",
};

function ruleToHuman(rule: IRRuleLoose): string {
  const op = rule.operator ?? "?";
  return `${operandToText(rule.left)} ${OP_MAP[op] ?? op} ${operandToText(rule.right)}`;
}

const PARAM_LABELS: Record<string, string> = {
  stop_loss_pct: "Stop loss %",
  take_profit_pct: "Take profit %",
  invest_per_trade_usd: `Invest per trade (${CURRENCY})`,
  quantity: "Quantity",
  logic: "Rule logic",
};
function paramLabel(key: string): string {
  return PARAM_LABELS[key] ?? key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

// ── Progress stepper ─────────────────────────────────────────────────────────
const STEP_LABELS = ["Extracting", "Review checkpoint", "Optimizing", "Out-of-sample check", "Done"];

/** Index of the active step; 5 means everything is done; -1 means no stepper (failed/interrupted). */
function activeStepIndex(status: PipelineStatus): number {
  switch (status) {
    case "running":              return 0;
    case "awaiting_checkpoint":  return 1;
    case "looping":              return 2;
    case "holdout":              return 3;
    case "paper_trading":        return 4;
    case "complete":             return 5;
    default:                     return -1; // failed / interrupted keep their banners
  }
}

function Spinner() {
  return (
    <span className="inline-block w-3.5 h-3.5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
  );
}

function StageStepper({ run }: { run: PipelineRunState }) {
  const active = activeStepIndex(run.status);
  if (active < 0) return null;
  return (
    <div className="flex items-center flex-wrap gap-y-2">
      {STEP_LABELS.map((base, i) => {
        const isDone = i < active;
        const isActive = i === active;
        const label = i === 2 && isActive && run.loop_round
          ? `Optimizing (round ${run.loop_round} of ${TOTAL_ROUNDS})`
          : base;
        return (
          <div key={base} className="flex items-center">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                  isDone ? "bg-indigo-600 text-white"
                  : isActive ? "bg-indigo-100 text-indigo-700"
                  : "bg-gray-100 text-gray-400"
                }`}
              >
                {isDone ? "✓" : i + 1}
              </span>
              <span className={`text-xs ${isActive ? "text-indigo-700 font-semibold" : isDone ? "text-gray-700" : "text-gray-400"}`}>
                {label}
              </span>
              {isActive && <Spinner />}
            </div>
            {i < STEP_LABELS.length - 1 && <div className="w-5 h-px bg-gray-300 mx-2" />}
          </div>
        );
      })}
    </div>
  );
}

// ── Round history table ──────────────────────────────────────────────────────
function RoundsTable({ scores, showMaxDd }: { scores: PipelineRoundScore[]; showMaxDd: boolean }) {
  const bestRound = useMemo(() => {
    let best: PipelineRoundScore | null = null;
    for (const s of scores) if (!best || s.score > best.score) best = s;
    return best?.round ?? null;
  }, [scores]);

  if (!scores.length) return null;
  return (
    <div className="border border-gray-200 rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-500 border-b border-gray-200 bg-gray-50">
            <th className="text-left px-3 py-2 font-medium">Round</th>
            <th className="text-right px-3 py-2 font-medium">Score</th>
            <th className="text-right px-3 py-2 font-medium">Return %</th>
            <th className="text-right px-3 py-2 font-medium">Sharpe</th>
            {showMaxDd && <th className="text-right px-3 py-2 font-medium">Max DD %</th>}
            <th className="text-right px-3 py-2 font-medium">Trades</th>
          </tr>
        </thead>
        <tbody>
          {scores.map((s) => {
            const isBest = s.round === bestRound;
            return (
              <tr key={s.round} className={`border-b border-gray-100 last:border-0 ${isBest ? "font-bold bg-indigo-50/50" : ""}`}>
                <td className="px-3 py-1.5">
                  {s.round}{isBest && <span className="ml-1.5 text-[10px] text-indigo-600 font-semibold uppercase">best</span>}
                </td>
                <td className="text-right px-3 py-1.5">{fmtNum(s.score)}</td>
                <td className="text-right px-3 py-1.5">{fmtNum(s.metrics?.total_return_pct)}</td>
                <td className="text-right px-3 py-1.5">{fmtNum(s.metrics?.sharpe_ratio)}</td>
                {showMaxDd && <td className="text-right px-3 py-1.5">{fmtNum(s.metrics?.max_drawdown_pct)}</td>}
                <td className="text-right px-3 py-1.5">{fmtInt(s.metrics?.num_trades)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Holdout panel ────────────────────────────────────────────────────────────
const HOLDOUT_PILL: Record<string, string> = {
  stable:   "bg-green-100 text-green-700 border-green-300",
  degraded: "bg-yellow-100 text-yellow-700 border-yellow-300",
  failed:   "bg-red-100 text-red-700 border-red-300",
};

function HoldoutPanel({ holdout }: { holdout: NonNullable<PipelineRunState["holdout_result"]> }) {
  const pill = HOLDOUT_PILL[holdout.verdict] ?? "bg-gray-100 text-gray-600 border-gray-300";
  return (
    <div className="border border-gray-200 rounded-xl p-4 space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-gray-900">Out-of-sample check</h3>
        <span className={`px-2.5 py-0.5 rounded-full border text-xs font-semibold ${pill}`}>
          {holdout.verdict}
        </span>
      </div>
      <div className="text-xs text-gray-500 space-y-0.5">
        {holdout.split_date && (
          <p>Train/test split at <span className="font-medium text-gray-700">{holdout.split_date}</span></p>
        )}
        {typeof holdout.train_ratio === "number" && (
          <p>
            Trained on the first <span className="font-medium text-gray-700">{Math.round(holdout.train_ratio * 100)}%</span> of
            the data, tested on the remaining {Math.round((1 - holdout.train_ratio) * 100)}%.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Composite score math panel ───────────────────────────────────────────────
function CompositeMathPanel({ report }: { report: NonNullable<PipelineRunState["report"]> }) {
  const rows = report.composite_breakdown;
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-gray-500">No completed round to break down yet.</p>;
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        The best round's composite score is a weighted blend of five metrics. Each row shows
        how much that metric contributed to the final score of <span className="font-semibold text-gray-700">{fmtNum(report.last_score)}</span>.
      </p>
      <div className="border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b border-gray-200 bg-gray-50">
              <th className="text-left px-3 py-2 font-medium">Metric</th>
              <th className="text-right px-3 py-2 font-medium">Value</th>
              <th className="text-right px-3 py-2 font-medium">Weight</th>
              <th className="text-right px-3 py-2 font-medium">Normalized</th>
              <th className="text-right px-3 py-2 font-medium">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-b border-gray-100 last:border-0">
                <td className="px-3 py-1.5">{r.label}</td>
                <td className="text-right px-3 py-1.5">{fmtNum(r.value)}</td>
                <td className="text-right px-3 py-1.5">{Math.round(r.weight * 100)}%</td>
                <td className="text-right px-3 py-1.5">{fmtNum(r.normalized)}</td>
                <td className="text-right px-3 py-1.5 font-medium">{fmtNum(r.contribution)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Walk-forward fold breakdown panel ────────────────────────────────────────
function WalkForwardPanel({ data }: { data: WalkForwardDetail }) {
  if (!data.windows.length) {
    return <p className="text-sm text-gray-500">Not enough data for a walk-forward split on this run.</p>;
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        {data.num_windows} rolling fold{data.num_windows === 1 ? "" : "s"} — each trains on a window,
        grid-searches the best params, then tests on the next out-of-sample step.
      </p>
      <div className="border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b border-gray-200 bg-gray-50">
              <th className="text-left px-3 py-2 font-medium">Fold</th>
              <th className="text-left px-3 py-2 font-medium">Train</th>
              <th className="text-left px-3 py-2 font-medium">Test (OOS)</th>
              <th className="text-right px-3 py-2 font-medium">OOS Return %</th>
              <th className="text-right px-3 py-2 font-medium">OOS Sharpe</th>
              <th className="text-right px-3 py-2 font-medium">Trades</th>
            </tr>
          </thead>
          <tbody>
            {data.windows.map((w) => (
              <tr key={w.window_num} className="border-b border-gray-100 last:border-0">
                <td className="px-3 py-1.5">{w.window_num}</td>
                <td className="px-3 py-1.5 text-xs text-gray-600">{w.train_period}</td>
                <td className="px-3 py-1.5 text-xs text-gray-600">{w.test_period}</td>
                <td className="text-right px-3 py-1.5">{fmtNum(w.return_pct)}</td>
                <td className="text-right px-3 py-1.5">{fmtNum(w.sharpe)}</td>
                <td className="text-right px-3 py-1.5">{fmtInt(w.num_trades)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">
        Aggregated out-of-sample: {fmtNum(data.out_of_sample?.total_return_pct)}% return,
        {" "}{fmtNum(data.out_of_sample?.sharpe_ratio)} Sharpe across all folds stitched together.
      </p>
    </div>
  );
}

// ── Stress test detail panel ─────────────────────────────────────────────────
const STRESS_VERDICT_PILL: Record<string, string> = {
  SURVIVED: "bg-green-100 text-green-700 border-green-300",
  DEGRADED: "bg-yellow-100 text-yellow-700 border-yellow-300",
  SEVERE:   "bg-red-100 text-red-700 border-red-300",
};

function StressDetailPanel({ data }: { data: StressDetailResult }) {
  if (!data.scenarios.length) {
    return <p className="text-sm text-gray-500">Stress detail could not be computed for this run.</p>;
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        A quick single-pass check across {data.scenarios.length} historical stress scenarios (one
        run each, not the full 100-run Stress Tester) — shows how this strategy would have reacted.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {data.scenarios.map((s) => (
          <div key={s.scenario} className="border border-gray-200 rounded-lg p-3 flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-gray-800">{s.display_name}</p>
              <p className="text-xs text-gray-500">
                Baseline {fmtNum(s.baseline_return_pct)}% → Stressed {fmtNum(s.stressed_return_pct)}%
              </p>
            </div>
            <span className={`px-2 py-0.5 rounded-full border text-xs font-semibold whitespace-nowrap ${STRESS_VERDICT_PILL[s.verdict] ?? ""}`}>
              {s.verdict}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Paper trading panel ──────────────────────────────────────────────────────
function PaperTradingPanel({ report }: { report: NonNullable<PipelineRunState["report"]> }) {
  const result = report.paper_trading_result;
  if (!result) {
    return (
      <p className="text-sm text-gray-500">
        Paper trading is still running in the background — check back in a moment.
      </p>
    );
  }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div>
        <p className="text-xs text-gray-500">Return</p>
        <p className="text-sm font-semibold text-gray-800">{fmtNum(result.total_return_pct as number)}%</p>
      </div>
      <div>
        <p className="text-xs text-gray-500">Sharpe</p>
        <p className="text-sm font-semibold text-gray-800">{fmtNum(result.sharpe_ratio as number)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-500">Trades</p>
        <p className="text-sm font-semibold text-gray-800">{fmtInt(result.num_trades as number)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-500">Max drawdown</p>
        <p className="text-sm font-semibold text-gray-800">{fmtNum(result.max_drawdown_pct as number)}%</p>
      </div>
    </div>
  );
}

// ── Generic expandable chip panel wrapper ────────────────────────────────────
function ChipPanel({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="border border-indigo-200 bg-indigo-50/30 rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        <button className="text-xs text-gray-400 hover:text-gray-600" onClick={onClose}>Close</button>
      </div>
      {children}
    </div>
  );
}

// ── Checkpoint countdown ─────────────────────────────────────────────────────
function CheckpointCountdown({ openedAt }: { openedAt: string }) {
  const [nowTs, setNowTs] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNowTs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const elapsed = (nowTs - parseUtcMs(openedAt)) / 1000;
  const remaining = Math.ceil(60 - elapsed); // window is 60–100s random; count down the 60s minimum
  return (
    <p className="text-xs text-gray-500 italic">
      {remaining > 0
        ? `Auto-proceeding in roughly ${remaining}s if you don't respond.`
        : "Auto-proceeding any moment now."}
    </p>
  );
}

// ── Checkpoint view ──────────────────────────────────────────────────────────
function CheckpointView({
  run, tweakValue, onTweakChange, onConfirm, onTweakSubmit,
}: {
  run: PipelineRunState;
  tweakValue: string;
  onTweakChange: (v: string) => void;
  onConfirm: () => void;
  onTweakSubmit: () => void;
}) {
  const params = (run.ir?.params ?? {}) as Record<string, unknown>;
  const entryRules = (Array.isArray(params.entry_rules) ? params.entry_rules : []) as IRRuleLoose[];
  const exitRules  = (Array.isArray(params.exit_rules)  ? params.exit_rules  : []) as IRRuleLoose[];
  const scalarParams = Object.entries(params).filter(
    ([k, v]) => k !== "entry_rules" && k !== "exit_rules" &&
      (typeof v === "number" || typeof v === "string" || typeof v === "boolean"),
  );

  return (
    <div className="border border-gray-200 rounded-xl p-4 space-y-3">
      {run.disclaimer && (
        <div className="border border-amber-400 bg-amber-50 rounded-lg p-3 text-amber-800 text-sm">
          <strong>Heads up:</strong> {run.disclaimer} We've suggested a reasonable
          starting point below — review it, tweak anything that doesn't fit, or confirm as-is.
        </div>
      )}

      <p className="text-sm text-gray-700">Confirm this strategy, or type a change:</p>
      {run.checkpoint_opened_at && <CheckpointCountdown openedAt={run.checkpoint_opened_at} />}

      {run.ir && (
        <div className="space-y-3">
          <span className="inline-block px-2.5 py-1 rounded-full bg-indigo-100 text-indigo-700 text-xs font-semibold">
            {run.ir.strategy}
          </span>

          {entryRules.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Entry rules</p>
              <ul className="space-y-1">
                {entryRules.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 w-4 h-4 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[10px] font-bold flex-shrink-0">{i + 1}</span>
                    <code className="text-gray-800 bg-gray-50 border border-gray-100 rounded px-2 py-0.5">{ruleToHuman(r)}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {exitRules.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Exit rules</p>
              <ul className="space-y-1">
                {exitRules.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 w-4 h-4 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[10px] font-bold flex-shrink-0">{i + 1}</span>
                    <code className="text-gray-800 bg-gray-50 border border-gray-100 rounded px-2 py-0.5">{ruleToHuman(r)}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {scalarParams.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Parameters</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 max-w-md">
                {scalarParams.map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm border-b border-gray-100 py-0.5">
                    <span className="text-gray-500">{paramLabel(k)}</span>
                    <span className="text-gray-800 font-medium">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <details className="text-xs">
            <summary className="cursor-pointer text-gray-400 hover:text-gray-600 select-none">Show raw strategy JSON</summary>
            <pre className="mt-2 bg-gray-100 p-2 rounded-lg overflow-x-auto">{JSON.stringify(run.ir, null, 2)}</pre>
          </details>
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <button className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700" onClick={onConfirm}>
          Confirm
        </button>
        <input
          className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-400"
          placeholder="e.g. use a faster EMA crossover"
          value={tweakValue}
          onChange={(e) => onTweakChange(e.target.value)}
        />
        <button
          className="px-3 py-2 rounded-lg border border-gray-300 text-sm disabled:opacity-40 disabled:cursor-default"
          disabled={!tweakValue.trim()}
          onClick={onTweakSubmit}
        >
          Apply tweak
        </button>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
const IMPLEMENTED_CHIPS = new Set([
  "retry_symbol", "composite_math", "paper_trading", "walk_forward", "stress_detail",
]);
// Chips whose data lives in an already-fetched field on the run/report — no on-demand request needed.
const INSTANT_CHIPS = new Set(["composite_math", "paper_trading"]);
// Chips that need a separate on-demand request the first time they're opened.
const FETCHABLE_CHIPS = new Set(["walk_forward", "stress_detail"]);

const STATUS_BADGE: Record<string, string> = {
  complete:    "bg-green-100 text-green-700",
  failed:      "bg-red-100 text-red-700",
  interrupted: "bg-amber-100 text-amber-700",
};

export default function PipelinePage({ userId }: { userId: string }) {
  const [inputMode, setInputMode] = useState<"transcript" | "url">("transcript");
  const [transcript, setTranscript] = useState("");
  const [url, setUrl] = useState("");
  const [tweak, setTweak] = useState("");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [runId, setRunId] = useState<string | null>(() => loadStoredRunId(userId));
  const [run, setRun] = useState<PipelineRunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkpointTweak, setCheckpointTweak] = useState("");
  const [retrySymbol, setRetrySymbol] = useState("");
  const [openChip, setOpenChip] = useState<string | null>(null);
  const [walkForward, setWalkForward] = useState<WalkForwardDetail | null>(null);
  const [stressDetail, setStressDetail] = useState<StressDetailResult | null>(null);
  const [chipLoading, setChipLoading] = useState<string | null>(null);
  const [chipError, setChipError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!runId) return;
    const stopPolling = () => {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
    const poll = async () => {
      try {
        const state = await getPipelineRun(runId);
        setRun(state);
        // Terminal states — stop polling, keep the result on screen.
        if (state.status === "complete" || state.status === "failed") stopPolling();
      } catch (e) {
        if (e instanceof PipelineRunNotFoundError) {
          // Stale stored run id (backend cleaned it up) — clear and reset.
          clearStoredRunId();
          stopPolling();
          setRunId(null);
          setRun(null);
          setError("Your previous run no longer exists — start a new one below.");
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    poll();
    pollRef.current = window.setInterval(poll, POLL_MS);
    return stopPolling;
  }, [runId]);

  const adoptRun = (id: string) => {
    storeRunId(id, userId);
    setRun(null);
    setRunId(id);
  };

  const handleStart = async () => {
    setError(null);
    try {
      const { run_id } = await startPipeline({
        user_id: userId,
        transcript: inputMode === "transcript" ? transcript : undefined,
        url: inputMode === "url" ? url : undefined,
        tweak: tweak || undefined,
        symbol,
      });
      adoptRun(run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleReset = () => {
    clearStoredRunId();
    setRunId(null);
    setRun(null);
    setError(null);
    setRetrySymbol("");
    setOpenChip(null);
    setWalkForward(null);
    setStressDetail(null);
    setChipError(null);
    setTranscript("");
    setUrl("");
  };

  const handleConfirm = async () => {
    if (!runId) return;
    try { await submitPipelineCheckpoint(runId, "confirm"); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const handleTweakSubmit = async () => {
    if (!runId || !checkpointTweak.trim()) return;
    try {
      await submitPipelineCheckpoint(runId, "tweak", checkpointTweak);
      setCheckpointTweak("");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const handleRetrySymbol = async () => {
    if (!runId || !retrySymbol.trim()) return;
    setError(null);
    try {
      const { run_id } = await retryPipelineSymbol(runId, retrySymbol.trim());
      setRetrySymbol("");
      adoptRun(run_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const handleResume = async () => {
    if (!runId) return;
    try { await resumePipelineRun(runId); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const handleChipClick = async (chipId: string) => {
    if (openChip === chipId) { setOpenChip(null); return; }
    setOpenChip(chipId);
    setChipError(null);
    if (!runId || !FETCHABLE_CHIPS.has(chipId)) return;
    if (chipId === "walk_forward" && walkForward) return;
    if (chipId === "stress_detail" && stressDetail) return;
    setChipLoading(chipId);
    try {
      if (chipId === "walk_forward") setWalkForward(await getPipelineWalkForward(runId));
      if (chipId === "stress_detail") setStressDetail(await getPipelineStressDetail(runId));
    } catch (e) {
      setChipError(e instanceof Error ? e.message : String(e));
    } finally {
      setChipLoading(null);
    }
  };

  const isTerminal = run?.status === "complete" || run?.status === "failed";

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Reel → Backtest Pipeline</h1>

      {!runId && (
        <div className="space-y-3">
          <div className="flex gap-1 bg-gray-100 rounded-full p-1 w-fit">
            {(["transcript", "url"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setInputMode(m)}
                className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all ${
                  inputMode === m ? "bg-white text-indigo-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
                }`}
              >
                {m === "transcript" ? "📝 Paste Transcript" : "🔗 Paste URL"}
              </button>
            ))}
          </div>

          {inputMode === "url" ? (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Reel / Video URL</label>
              <input
                className="w-full border border-gray-200 rounded-lg p-2 text-sm focus:outline-none focus:border-indigo-400"
                placeholder="https://www.youtube.com/watch?v=... or https://www.instagram.com/reel/..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <p className="text-xs text-gray-400 mt-1">
                Downloads the video, transcribes it, and extracts the strategy automatically.
              </p>
            </div>
          ) : (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Strategy transcript</label>
              <textarea
                className="w-full border border-gray-200 rounded-lg p-2 text-sm focus:outline-none focus:border-indigo-400"
                rows={6}
                placeholder="Paste a transcript describing a trading strategy..."
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-500 mb-1">Tweak (optional)</label>
            <input
              className="w-full border border-gray-200 rounded-lg p-2 text-sm italic focus:outline-none focus:border-indigo-400"
              placeholder='Optional: "also try this differently" — a free-text tweak'
              value={tweak}
              onChange={(e) => setTweak(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Symbol — e.g. BTC/USDT</label>
            <input
              className="w-full border border-gray-200 rounded-lg p-2 text-sm focus:outline-none focus:border-indigo-400"
              placeholder="BTC/USDT"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            />
          </div>
          <button
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-default"
            disabled={inputMode === "transcript" ? !transcript.trim() : !url.trim()}
            onClick={handleStart}
          >
            Run pipeline
          </button>
        </div>
      )}

      {error && <div className="text-red-600 text-sm">{error}</div>}

      {run && (
        <div className="space-y-4">
          {/* Header: symbol + status + reset */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-semibold text-gray-900">{run.symbol}</span>
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[run.status] ?? "bg-gray-100 text-gray-600"}`}>
                {run.status.replace(/_/g, " ")}
              </span>
            </div>
            {isTerminal && (
              <button className="px-3 py-1.5 rounded-lg border border-gray-300 text-sm hover:bg-gray-50" onClick={handleReset}>
                Start a new run
              </button>
            )}
          </div>

          <StageStepper run={run} />

          {run.status === "failed" && (
            <div className="border border-red-400 rounded-lg p-3 text-red-700 text-sm">
              This run failed: {run.error_message || "Unknown error"}
            </div>
          )}

          {run.status === "interrupted" && (
            <div className="border border-amber-400 rounded-lg p-3 text-sm">
              This run was interrupted (likely a backend restart).
              <button className="ml-2 underline" onClick={handleResume}>Resume</button>
            </div>
          )}

          {run.status === "awaiting_checkpoint" && (
            <CheckpointView
              run={run}
              tweakValue={checkpointTweak}
              onTweakChange={setCheckpointTweak}
              onConfirm={handleConfirm}
              onTweakSubmit={handleTweakSubmit}
            />
          )}

          {/* Live rounds while optimizing */}
          {run.status === "looping" && run.composite_scores.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Completed rounds</p>
              <RoundsTable scores={run.composite_scores} showMaxDd={false} />
            </div>
          )}

          {/* Results */}
          {run.report && (
            <div className="space-y-4">
              <p className="text-base font-medium text-gray-900">{run.report.verdict}</p>

              {run.composite_scores.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Optimization rounds</p>
                  <RoundsTable scores={run.composite_scores} showMaxDd />
                </div>
              )}

              {run.holdout_result && <HoldoutPanel holdout={run.holdout_result} />}

              <div className="flex flex-wrap items-center gap-2">
                {run.report.chips.map((chip) => {
                  if (!IMPLEMENTED_CHIPS.has(chip.id)) {
                    return (
                      <span
                        key={chip.id}
                        className="px-3 py-1 rounded-full border border-gray-200 text-sm text-gray-400 cursor-default select-none"
                        title="Coming soon"
                      >
                        <span className="inline-block w-2 h-2 rounded-full mr-2 bg-gray-300" />
                        {chip.label}
                        <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-400">soon</span>
                      </span>
                    );
                  }
                  if (chip.id === "retry_symbol") {
                    return (
                      <div key={chip.id} className="flex items-center gap-2 border border-gray-200 rounded-full pl-3 pr-1.5 py-1">
                        <span className="inline-block w-2 h-2 rounded-full bg-indigo-500" />
                        <span className="text-sm text-gray-700">{chip.label}</span>
                        <input
                          className="w-28 border border-gray-200 rounded-lg px-2 py-0.5 text-sm focus:outline-none focus:border-indigo-400"
                          placeholder="ETH/USDT"
                          value={retrySymbol}
                          onChange={(e) => setRetrySymbol(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") handleRetrySymbol(); }}
                        />
                        <button
                          className="px-2.5 py-0.5 rounded-full bg-indigo-600 text-white text-sm disabled:opacity-40 disabled:cursor-default"
                          disabled={!retrySymbol.trim()}
                          onClick={handleRetrySymbol}
                        >
                          Go
                        </button>
                      </div>
                    );
                  }
                  const isOpen = openChip === chip.id;
                  return (
                    <button
                      key={chip.id}
                      className={`flex items-center gap-2 border rounded-full pl-3 pr-3 py-1 text-sm ${
                        isOpen ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "border-gray-200 text-gray-700 hover:bg-gray-50"
                      }`}
                      onClick={() => handleChipClick(chip.id)}
                    >
                      <span className={`inline-block w-2 h-2 rounded-full ${INSTANT_CHIPS.has(chip.id) ? "bg-indigo-500" : "bg-emerald-500"}`} />
                      {chip.label}
                      {chipLoading === chip.id && <Spinner />}
                    </button>
                  );
                })}
              </div>

              {chipError && <p className="text-sm text-red-600">{chipError}</p>}

              {openChip === "composite_math" && (
                <ChipPanel title="Composite score math" onClose={() => setOpenChip(null)}>
                  <CompositeMathPanel report={run.report} />
                </ChipPanel>
              )}
              {openChip === "paper_trading" && (
                <ChipPanel title="Paper trading" onClose={() => setOpenChip(null)}>
                  <PaperTradingPanel report={run.report} />
                </ChipPanel>
              )}
              {openChip === "walk_forward" && walkForward && (
                <ChipPanel title="Walk-forward fold breakdown" onClose={() => setOpenChip(null)}>
                  <WalkForwardPanel data={walkForward} />
                </ChipPanel>
              )}
              {openChip === "stress_detail" && stressDetail && (
                <ChipPanel title="Stress test detail" onClose={() => setOpenChip(null)}>
                  <StressDetailPanel data={stressDetail} />
                </ChipPanel>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
