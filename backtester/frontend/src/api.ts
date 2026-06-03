import { BacktestResponse, FormState, StressFormState, StressResponse } from './types';

/** Returns true for NSE / BSE sources */
export const isIndianSource = (source: string) => source === 'nse' || source === 'bse';

/** Build strategy-specific params dict from form state */
function buildStrategyParams(form: FormState): Record<string, unknown> {
  if (form.strategy === 'GRID') {
    return {
      lower_bound:          form.lowerBound,
      upper_bound:          form.upperBound,
      num_levels:           form.numLevels,
      spacing:              form.gridSpacing,
      invest_per_level_usd: form.gridInvestPerLevel,
    };
  }
  if (form.strategy === 'DCA') {
    return {
      buy_interval_hours: form.buyIntervalHours,
      invest_per_buy_usd: form.dcaInvestPerBuy,
      hold_days:          form.holdDays,
      exit_type:          form.dcaExitType,
      ...(form.dcaExitType === 'profit' ? { profit_target_pct: form.profitTargetPct } : {}),
    };
  }
  // PLA — user-controlled invest per level; deeper levels scale 1×, 1×, 2×, 3×
  const perLvl = form.plaInvestPerLevel;
  return {
    fast_ema:             form.fastEma,
    slow_ema:             form.slowEma,
    exit_type:            form.plaExitType,
    entry_levels:         [0, form.plaLvl2Pct, form.plaLvl3Pct, form.plaLvl4Pct],
    invest_per_level_usd: [perLvl, perLvl, perLvl * 2, perLvl * 3],
    ...(form.plaExitType === 'take_profit' ? { take_profit_pct: form.takeProfitPct } : {}),
    ...(form.plaExitType === 'stop_loss'   ? { stop_loss_pct:   form.stopLossPct   } : {}),
  };
}

/** POST /api/backtest/run */
export async function runBacktest(form: FormState): Promise<BacktestResponse> {
  const symbol = form.symbol === '__custom__' ? form.customSymbol : form.symbol;
  const indian = isIndianSource(form.source);

  const payload = {
    symbol,
    strategy:   form.strategy,
    start_date: form.startDate,
    end_date:   form.endDate,
    capital:    form.capital,
    fee_pct:    indian ? 0 : form.feePct / 100,       // Indian costs override fee_pct
    slippage:   form.slippagePct / 100,
    source:     form.source,
    interval:   form.interval,
    params:     buildStrategyParams(form),
    // Indian market fields
    use_indian_costs: indian,
    market_type:      indian ? form.marketType : 'equity_delivery',
    brokerage_model:  indian ? form.brokerageModel : 'flat',
    brokerage_flat:   indian ? form.brokerageFlat : 20,
    brokerage_pct:    indian ? form.brokeragePct / 100 : 0.005,
    // Out-of-sample validation fields
    validation_mode:  form.validationMode,
    train_ratio:      form.trainRatio,
    wf_window:        form.wfWindow,
    wf_step:          form.wfStep,
  };

  const res = await fetch('/api/backtest/run', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  return res.json();
}

/** GET /api/strategies/grid/bounds — auto-detect GRID bounds */
export async function fetchGridBounds(
  symbol: string,
  source: string,
  interval: string,
  startDate: string,
  endDate: string,
) {
  const q = new URLSearchParams({ symbol, source, interval, start_date: startDate, end_date: endDate });
  const res = await fetch(`/api/strategies/grid/bounds?${q}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as any).detail ?? `Server ${res.status}`);
  }
  return res.json();
}

/** POST /api/stress/run */
export async function runStressTest(form: StressFormState): Promise<StressResponse> {
  const symbol = form.symbol === '__custom__' ? form.customSymbol : form.symbol;
  const indian = form.source === 'nse' || form.source === 'bse';

  const severityValue = form.severity === 'mild' ? 0.5 : form.severity === 'severe' ? 1.5 : 1.0;

  const payload: Record<string, unknown> = {
    symbol,
    source:           form.source,
    interval:         form.interval,
    start_date:       form.startDate,
    end_date:         form.endDate,
    capital:          form.capital,
    fee_pct:          indian ? 0 : form.feePct / 100,
    slippage:         form.slippagePct / 100,
    strategy:         form.strategy,
    params:           buildStrategyParams(form as unknown as FormState),
    use_indian_costs: indian,
    market_type:      indian ? form.marketType : 'equity_delivery',
    brokerage_model:  indian ? form.brokerageModel : 'flat',
    brokerage_flat:   indian ? form.brokerageFlat : 20,
    brokerage_pct:    indian ? form.brokeragePct / 100 : 0.005,
    scenario_key:     form.scenarioKey,
    severity:         form.severity === 'custom' ? severityValue : severityValue,
    outlier_count:    form.outlierCount,
    monte_carlo_runs: form.mcRuns,
    trade_mc_runs:    form.tradeMcRuns ?? 0,
    trade_skip_pct:   form.tradeSkipPct ?? 0.10,
    run_validation:   form.runValidation ?? false,
    wf_window:        form.wfWindow ?? 252,
    wf_step:          form.wfStep ?? 63,
    regime_aware_mc:      form.regimeAwareMC ?? false,
    synthetic_intraday:   form.syntheticIntraday ?? false,
  };
  if (form.shockDepthPct     != null) payload.shock_depth_pct     = form.shockDepthPct;
  if (form.shockDurationDays != null) payload.shock_duration_days = form.shockDurationDays;
  if (form.volMultiplier     != null) payload.vol_multiplier      = form.volMultiplier;
  if (form.seed              != null) payload.seed                = form.seed;

  const res = await fetch('/api/stress/run', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

// ── Live-run data shape coming off the SSE stream ────────────────────────────
export interface StreamRun {
  run_idx:          number;
  return_pct:       number;
  sharpe:           number;
  sortino:          number;
  max_dd_pct:       number;
  win_rate:         number;
  num_trades:       number;
  final_equity:     number;
  annualized_return:number;
  equity:           number[];   // ≤200-point subsampled equity curve
}

/**
 * POST /api/stress/stream — SSE streaming stress test.
 * Calls back as each run completes; final callback with complete StressResponse.
 * Returns a cleanup function (call it to abort the stream).
 */
export function streamStressTest(
  form: StressFormState,
  callbacks: {
    onBaseline?: (metrics: Record<string, number>, total?: number) => void;
    onRun?:      (runNum: number, total: number, run: StreamRun) => void;
    onComplete?: (result: StressResponse) => void;
    onError?:    (msg: string) => void;
  },
): () => void {
  const symbol       = form.symbol === '__custom__' ? form.customSymbol : form.symbol;
  const indian       = form.source === 'nse' || form.source === 'bse';
  const severityValue = form.severity === 'mild' ? 0.5 : form.severity === 'severe' ? 1.5 : 1.0;

  const payload: Record<string, unknown> = {
    symbol,
    source:           form.source,
    interval:         form.interval,
    start_date:       form.startDate,
    end_date:         form.endDate,
    capital:          form.capital,
    fee_pct:          indian ? 0 : form.feePct / 100,
    slippage:         form.slippagePct / 100,
    strategy:         form.strategy,
    params:           buildStrategyParams(form as unknown as FormState),
    use_indian_costs: indian,
    market_type:      indian ? form.marketType : 'equity_delivery',
    brokerage_model:  indian ? form.brokerageModel : 'flat',
    brokerage_flat:   indian ? form.brokerageFlat : 20,
    brokerage_pct:    indian ? form.brokeragePct / 100 : 0.005,
    scenario_key:     form.scenarioKey,
    severity:         severityValue,
    outlier_count:    form.outlierCount,
    monte_carlo_runs: form.mcRuns,
    trade_mc_runs:    form.tradeMcRuns ?? 0,
    trade_skip_pct:   form.tradeSkipPct ?? 0.10,
    run_validation:   form.runValidation ?? false,
    wf_window:        form.wfWindow ?? 252,
    wf_step:          form.wfStep ?? 63,
    regime_aware_mc:      form.regimeAwareMC ?? false,
    synthetic_intraday:   form.syntheticIntraday ?? false,
  };
  if (form.shockDepthPct     != null) payload.shock_depth_pct     = form.shockDepthPct;
  if (form.shockDurationDays != null) payload.shock_duration_days = form.shockDurationDays;
  if (form.volMultiplier     != null) payload.vol_multiplier      = form.volMultiplier;
  if (form.seed              != null) payload.seed                = form.seed;

  const ctrl = new AbortController();

  (async () => {
    try {
      const res = await fetch('/api/stress/stream', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
        signal:  ctrl.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        callbacks.onError?.((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
        return;
      }

      const reader  = res.body!.getReader();
      const decoder = new TextDecoder();
      let   buffer  = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const ev = JSON.parse(line.slice(6)) as {
              type: string;
              metrics?: Record<string, number>;
              run_num?: number;
              total?: number;
              equity?: number[];
              result?: StressResponse;
              message?: string;
            };
            if (ev.type === 'baseline') callbacks.onBaseline?.(ev.metrics ?? {}, ev.total);
            else if (ev.type === 'run')
              callbacks.onRun?.(ev.run_num!, ev.total!, { ...ev.metrics, equity: ev.equity ?? [] } as StreamRun);
            else if (ev.type === 'complete') callbacks.onComplete?.(ev.result!);
            else if (ev.type === 'error')   callbacks.onError?.(ev.message ?? 'Unknown error');
          } catch { /* malformed line */ }
        }
      }
    } catch (e: unknown) {
      if (!ctrl.signal.aborted)
        callbacks.onError?.(e instanceof Error ? e.message : String(e));
    }
  })();

  return () => ctrl.abort();
}

/** GET /api/stress/scenarios */
export async function fetchStressScenarios(): Promise<Record<string, {
  display_name: string;
  shock_depth_pct: number;
  shock_duration_days: number;
  vol_multiplier: number;
  slip_multiplier: number;
  direction: string;
  has_outliers: boolean;
}>> {
  const res = await fetch('/api/stress/scenarios');
  if (!res.ok) throw new Error(`Server ${res.status}`);
  return res.json();
}

/** GET /api/india/cost_preview — preview Indian transaction costs */
export async function fetchIndianCostPreview(
  marketType:     string,
  brokerageModel: string,
  brokerageFlat:  number,
  turnover        = 100_000,
) {
  const q = new URLSearchParams({
    market_type:     marketType,
    brokerage_model: brokerageModel,
    brokerage_flat:  String(brokerageFlat),
    turnover:        String(turnover),
  });
  const res = await fetch(`/api/india/cost_preview?${q}`);
  if (!res.ok) throw new Error(`Server ${res.status}`);
  return res.json();
}
