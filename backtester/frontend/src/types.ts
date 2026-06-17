// Strategy name is dynamic — the catalog comes from GET /api/strategies. The
// three classic strategies (GRID/DCA/PLA) still use dedicated flat form fields;
// every other strategy is driven by the schema-driven StrategyParamsForm.
export type Strategy       = string;
export const CLASSIC_STRATEGIES = ['GRID', 'DCA', 'PLA'] as const;
export type DataSource     = 'binance' | 'yfinance' | 'nse' | 'bse';

// ── Schema-driven strategy metadata (GET /api/strategies) ──────────────────
export interface ParamSchema {
  type:        'number' | 'select' | 'bool' | 'text' | 'array';
  label:       string;
  default:     unknown;
  min?:        number;
  max?:        number;
  step?:       number;
  options?:    (string | number)[];
  group?:      string;
  depends_on?: { field: string; value: unknown };
  help?:       string;
}

export interface StrategyMeta {
  name:        string;
  description: string;
  category:    'classic' | 'indicator' | 'custom';
  parameters:  Record<string, unknown>;
  schema:      Record<string, ParamSchema>;
}

// ── Indicator catalog (GET /api/indicators) ────────────────────────────────
export interface IndicatorParam { name: string; default: number; min: number; max: number; step: number }
export interface IndicatorMeta {
  key:     string;
  label:   string;
  group:   string;
  params:  IndicatorParam[];
  outputs: string[];
}
export interface IndicatorCatalog {
  groups:        string[];
  count:         number;
  output_series: number;
  indicators:    IndicatorMeta[];
}
export type Interval       = '1d' | '4h' | '1h' | '15m' | '1w';
export type MarketType     = 'equity_delivery' | 'equity_intraday' | 'futures' | 'options' | 'crypto';
export type BrokerageModel = 'flat' | 'percentage' | 'zero';

export interface Trade {
  entry_time:  string;
  entry_price: number;
  exit_time?:  string;
  exit_price?: number;
  quantity:    number;
  pnl:         number;
  pnl_pct:     number;  // decimal fraction, e.g. 0.05 = 5%
  fees:        number;
  side:        string;
}

export interface CostBreakdown {
  brokerage:        number;
  stt:              number;
  exchange_charges: number;
  sebi_charges:     number;
  gst:              number;
  stamp_duty:       number;
  total:            number;
}

// ── Regime breakdown types ────────────────────────────────────────────────
export interface RegimeStat {
  total_return_pct:  number;
  sharpe_ratio:      number;
  sortino_ratio:     number;
  volatility_pct:    number;
  max_drawdown_pct:  number;
  num_candles:       number;
  pct_of_period:     number;
  num_trades:        number;
  win_rate:          number;
  profit_factor:     number;
  avg_trade_pnl:     number;
  best_trade:        number;
  worst_trade:       number;
  gross_profit:      number;
  gross_loss:        number;
  avg_trade_duration: number;
}

export interface RegimeBreakdownData {
  method:         string;        // 'ma_trend'
  regime_counts:  { bull: number; bear: number; sideways: number };
  bull:           RegimeStat;
  bear:           RegimeStat;
  sideways:       RegimeStat;
}

// ── Validation types ──────────────────────────────────────────────────────
export interface ValidationMetrics {
  num_trades:             number;
  sharpe_ratio:           number;
  sortino_ratio:          number;
  total_return_pct:       number;
  annualised_return_pct:  number;
  max_drawdown_pct:       number;
  win_rate:               number;
  volatility_pct?:        number;
  calmar_ratio?:          number;
  final_equity?:          number;
  num_candles?:           number;
}

export interface WalkForwardWindow {
  window_num:    number;
  train_period:  string;
  test_period:   string;
  best_params:   string;
  train_sharpe:  number;
  return_pct:    number;
  sharpe:        number;
  max_dd_pct:    number;
  num_trades:    number;
  win_rate:      number;
}

export interface ValidationData {
  mode:           'holdout' | 'walk_forward';
  // holdout fields
  train_ratio?:   number;
  split_date?:    string;
  in_sample?:     ValidationMetrics;
  out_of_sample?: ValidationMetrics;
  verdict?:       'stable' | 'degraded' | 'failed' | 'insufficient_data';
  // walk-forward fields
  window?:        number;
  step?:          number;
  num_windows?:   number;
  windows?:       WalkForwardWindow[];
  // stitched validation curves
  validation_equity_curve?: number[];
  validation_timestamps?:   string[];
  validation_drawdowns?:    number[];
}

export interface MetricsResults {
  total_return_pct:       number;
  total_return_usd:       number;
  annualised_return:      number;
  annualised_return_pct:  number;
  sharpe_ratio:           number;
  sortino_ratio:          number;
  calmar_ratio:           number;
  max_drawdown_pct:       number;
  volatility_pct:         number;
  win_rate:               number;
  profit_factor:          number;
  num_trades:             number;
  best_trade:             number;
  worst_trade:            number;
  final_equity:           number;
  initial_capital:        number;
  avg_trade_pnl:          number;
  avg_trade_duration:     number;
  gross_profit:           number;
  gross_loss:             number;
  total_fees_paid:        number;
  data_quality_score:     number;
  cost_breakdown?:        CostBreakdown;
  regimes?:               RegimeBreakdownData;
}

export interface SeriesData {
  equity_curve:   number[];
  drawdowns:      number[];
  timestamps:     string[];
  trades:         Trade[];
  close_prices:   number[];
  regime_labels?: string[];   // 'bull' | 'bear' | 'sideways' per candle
}

export interface BacktestResponse {
  backtest_id:  string;
  status:       string;
  report_url:   string;
  currency:     string;   // '$' for crypto/US, '₹' for Indian
  market_type:  string;
  results:      MetricsResults;
  series:       SeriesData;
  validation?:  ValidationData;
}

// ── Stress Test types ─────────────────────────────────────────────────────

export type StressScenarioKey =
  | 'gfc_2008' | 'covid_crash' | 'flash_crash_2010' | 'luna_collapse'
  | 'liquidity_drought' | 'pump_dump' | 'whipsaw_chop' | 'slow_bleed'
  | 'vol_spike' | 'gap_risk' | 'range_bound' | 'trend_reversal'
  | 'outlier_injection'
  // Indian-specific scenarios
  | 'demonetization_2016' | 'covid_nifty_mar2020' | 'yes_bank_2020' | 'expiry_gamma_squeeze';

// 'custom' was removed: no UI sets it and api.ts always mapped it to 1.0 anyway.
export type StressSeverity = 'mild' | 'moderate' | 'severe';

export interface MonteCarloStats {
  p5:    number;
  p50:   number;
  p95:   number;
  worst: number;
  best?: number;
}

export interface StressRunMetrics {
  return_pct:        number;
  sharpe:            number;
  sortino?:          number;
  calmar?:           number;
  max_dd_pct:        number;
  win_rate:          number;
  num_trades:        number;
  final_equity?:     number;
  annualized_return?: number;
}

export interface StressMonteCarloResult {
  runs:             number;
  return_pct:       MonteCarloStats;
  max_drawdown_pct: MonteCarloStats;
  sharpe:           MonteCarloStats;
  sortino?:         MonteCarloStats;
  win_rate:         MonteCarloStats;
  cvar_5?:          number;   // Expected Shortfall at 5% (mean of worst 5% returns)
  prob_ruin?:       number;   // Fraction of runs where final equity < 50% of capital
  per_run:          StressRunMetrics[];
}

export interface RobustnessAxes {
  survival:           number;
  stability:          number;
  tail_safety:        number;
  overfit_resistance?: number;
}

export interface RobustnessScore {
  score:          number | null;
  grade:          string | null;   // A+, A, B, C, D, F
  provisional:    boolean;         // true when walk-forward wasn't run
  wfe?:           number | null;   // Walk-Forward Efficiency
  axes:           RobustnessAxes;
  interpretation: string;
  reason?:        string;          // set when score is null
}

export interface SpaghettiRun {
  run_idx:    number;
  return_pct: number;
  max_dd_pct: number;
  sharpe:     number;
  win_rate:   number;
  equity:     number[];
}

export interface StressSeries {
  timestamps:      string[];
  baseline_equity: number[];
  stressed_equity: number[];
  stressed_price:  number[];
  baseline_price:  number[];
  equity_fan?: {
    p5:  number[];
    p50: number[];
    p95: number[];
  };
  spaghetti?: {
    ts_indices: number[];
    runs:       SpaghettiRun[];
  };
}

export interface TradeMCResult {
  runs:             number;
  trade_skip_pct:   number;
  original_trades:  number;
  return_pct:       MonteCarloStats;
  max_drawdown_pct: MonteCarloStats;
  sharpe:           MonteCarloStats;
  win_rate:         MonteCarloStats;
  cvar_5?:          number;
  prob_ruin?:       number;
  per_run:          { return_pct: number; max_dd_pct: number; win_rate: number; sharpe: number; final_equity: number; num_trades: number }[];
  note?:            string;
}

export interface RegimeMCInfo {
  enabled:            boolean;
  regime_fractions:   Record<string, number>;   // bull/bear/sideways → fraction of dataset
  regime_vol_scales:  Record<string, number>;   // bull/bear/sideways → vol relative to overall
}

export interface StressResponse {
  backtest_id:  string;
  symbol:       string;
  strategy:     string;
  scenario:     {
    name:          string;
    display_name:  string;
    severity:      number;
    params:        Record<string, number>;
  };
  baseline:     Partial<MetricsResults>;
  stressed:     StressRunMetrics & { equity_curve: number[] };
  monte_carlo?:  StressMonteCarloResult;
  robustness?:   RobustnessScore;
  trade_mc?:     TradeMCResult;
  walk_forward?: ValidationData;
  regime_mc_info?: RegimeMCInfo;
  series:        StressSeries;
}

export interface StressFormState {
  // Dataset
  symbol:       string;
  customSymbol: string;
  source:       DataSource;
  startDate:    string;
  endDate:      string;
  datePreset:   string;
  interval:     Interval;
  capital:      number;
  feePct:       number;
  slippagePct:  number;
  // Strategy
  strategy:     Strategy;
  // Generic schema-driven params for non-classic strategies (mirrors FormState)
  strategyParams: Record<string, unknown>;
  // GRID params (reused from FormState)
  lowerBound:         number;
  upperBound:         number;
  numLevels:          number;
  gridSpacing:        'linear' | 'exponential';
  gridInvestPerLevel: number;
  // DCA params
  buyIntervalHours: number;
  dcaInvestPerBuy:  number;
  holdDays:         number;
  dcaExitType:      'time' | 'profit';
  profitTargetPct:  number;
  // PLA params
  fastEma:           number;
  slowEma:           number;
  plaExitType:       'crossover' | 'take_profit' | 'stop_loss';
  takeProfitPct:     number;
  stopLossPct:       number;
  plaLvl2Pct:        number;
  plaLvl3Pct:        number;
  plaLvl4Pct:        number;
  plaInvestPerLevel: number;
  // Indian market
  marketType:     MarketType;
  brokerageModel: BrokerageModel;
  brokerageFlat:  number;
  brokeragePct:   number;
  // Stress configuration
  scenarioKey:         StressScenarioKey;
  severity:            StressSeverity;
  shockDepthPct?:      number;
  shockDurationDays?:  number;
  volMultiplier?:      number;
  outlierCount:        number;
  mcRuns:              number;
  seed?:               number;
  tradeMcRuns:         number;    // 0 = disabled
  tradeSkipPct:        number;    // 0.0–0.5 (fraction to skip)
  // Walk-forward validation
  runValidation:       boolean;
  wfWindow:            number;    // train window in candles
  wfStep:              number;    // OOS step in candles
  // Regime-aware MC
  regimeAwareMC:       boolean;
  // Synthetic intraday: generate 15m/1h from daily OHLCV for unlimited history
  syntheticIntraday:   boolean;
}

export interface FormState {
  symbol:       string;
  customSymbol: string;
  source:       DataSource;
  startDate:    string;
  endDate:      string;
  datePreset:   string;
  interval:     Interval;
  capital:      number;
  feePct:       number;   // display %, e.g. 0.10
  slippagePct:  number;   // display %, e.g. 0.05
  strategy:     Strategy;
  // Generic schema-driven params for non-classic strategies (RSI/MACD/.../CUSTOM).
  // Classic GRID/DCA/PLA continue to use the dedicated flat fields below.
  strategyParams: Record<string, unknown>;
  // GRID params
  lowerBound:         number;
  upperBound:         number;
  numLevels:          number;
  gridSpacing:        'linear' | 'exponential';
  gridInvestPerLevel: number;
  // DCA params
  buyIntervalHours: number;
  dcaInvestPerBuy:  number;
  holdDays:         number;
  dcaExitType:      'time' | 'profit';
  profitTargetPct:  number;
  // PLA params
  fastEma:            number;
  slowEma:            number;
  plaExitType:        'crossover' | 'take_profit' | 'stop_loss';
  takeProfitPct:      number;
  stopLossPct:        number;
  plaLvl2Pct:         number;
  plaLvl3Pct:         number;
  plaLvl4Pct:         number;
  plaInvestPerLevel:  number;  // ₹/$ to invest at each cascading level (Level 1 base; 2x & 3x for deeper levels)
  // Indian market params
  marketType:     MarketType;
  brokerageModel: BrokerageModel;
  brokerageFlat:  number;   // ₹ per order
  brokeragePct:   number;   // % of turnover
  // Out-of-sample validation params
  validationMode: 'none' | 'holdout' | 'walk_forward';
  trainRatio:     number;   // 0.5 – 0.9 (default 0.7)
  wfWindow:       number;   // walk-forward train window in candles (default 252)
  wfStep:         number;   // walk-forward step/test size in candles (default 63)
}

// ── Forward Test types ────────────────────────────────────────────────────────

export interface ForecastFormState {
  // Dataset
  symbol:       string;
  customSymbol: string;
  source:       DataSource;
  startDate:    string;
  endDate:      string;
  datePreset:   string;
  interval:     Interval;
  capital:      number;
  feePct:       number;
  slippagePct:  number;
  // Strategy (same fields as FormState — classic + schema-driven)
  strategy:          Strategy;
  strategyParams:    Record<string, unknown>;
  lowerBound:        number;
  upperBound:        number;
  numLevels:         number;
  gridSpacing:       'linear' | 'exponential';
  gridInvestPerLevel:number;
  buyIntervalHours:  number;
  dcaInvestPerBuy:   number;
  holdDays:          number;
  dcaExitType:       'time' | 'profit';
  profitTargetPct:   number;
  fastEma:           number;
  slowEma:           number;
  plaExitType:       'crossover' | 'take_profit' | 'stop_loss';
  takeProfitPct:     number;
  stopLossPct:       number;
  plaLvl2Pct:        number;
  plaLvl3Pct:        number;
  plaLvl4Pct:        number;
  plaInvestPerLevel: number;
  marketType:        MarketType;
  brokerageModel:    BrokerageModel;
  brokerageFlat:     number;
  brokeragePct:      number;
  // Forecast-specific
  horizonDays: number;   // 30, 60, 90, 180, 365
  nPaths:      number;   // 50, 100, 200, 500
}

export interface RegimeDistribution {
  bull:     number;   // % of paths whose dominant regime was bull
  bear:     number;
  sideways: number;
}

export interface PriceSpaghettRun {
  run_idx:    number;
  return_pct: number;
  price_pct:  number[];   // % change from path start price, subsampled to ≤200 pts
}

export interface CompareMethodSummary {
  n_paths:              number;
  return_pct:           { p5: number; p50: number; p95: number };
  sharpe:               { p50: number };
  max_dd_pct:           { p50: number };
  forward_survival_pct: number;
  regime_distribution:  RegimeDistribution;
}

export interface ForecastCompareResult {
  kronos_available: boolean;
  bootstrap:        CompareMethodSummary;
  kronos:           CompareMethodSummary | null;
  n_paths:          number;
  horizon_days:     number;
}

// ForecastResponse has the same shape as StressResponse — aggregate_stress_results
// is reused verbatim; the `forecast` field carries metadata including UC-7 regime forecast.
export type ForecastResponse = StressResponse & {
  forecast?: {
    horizon_days:         number;
    n_paths:              number;
    method:               'block_bootstrap' | 'kronos';
    mode?:                'forward' | 'crisis';
    scenario_key?:        string;
    scenario_display?:    string;
    severity?:            number;
    regime_distribution?: RegimeDistribution;
    forward_survival_pct?: number;
  };
  price_spaghetti?: PriceSpaghettRun[];
};

// ── AI Paper Trading types ───────────────────────────────────────────────────

export interface PaperCandle {
  open:   number;
  high:   number;
  low:    number;
  close:  number;
  volume: number;
}

export interface PaperTrade {
  entry_time:  string;
  exit_time:   string;
  entry_price: number;
  exit_price:  number;
  quantity:    number;
  pnl:         number;
  pnl_pct:     number;
  fees:        number;
}

export interface PaperBarEvent {
  type:           'bar';
  bar_idx:        number;
  total:          number;
  timestamp:      string;
  candle:         PaperCandle;
  signal:         'BUY' | 'SELL' | 'HOLD';
  quantity:       number;
  equity:         number;
  cash:           number;
  position_qty:   number;
  position_value: number;
  trade?:         PaperTrade;
}

export interface PaperSetupEvent {
  type:     'setup';
  horizon:  number;
  symbol:   string;
  strategy: string;
  capital:  number;
  method:   'block_bootstrap' | 'kronos';
}

export interface PaperCompleteEvent {
  type:     'complete';
  metrics:  Record<string, number>;
  trades:   PaperTrade[];
  forecast: { horizon_days: number; method: string; symbol: string; strategy: string };
}

// ── Admin / Analytics types ──────────────────────────────────────────────────

export interface AdminSummary {
  total_events:    number;
  unique_sessions: number;
  unique_users:    number;
  total_feedback:  number;
  top_events:      { name: string; count: number }[];
  users:           { name: string | null; email: string; event_count: number; last_seen: string }[];
  feedback_by_category: { category: string; count: number }[];
}

export interface AdminEvent {
  id:         number;
  session_id: string;
  user_name:  string | null;
  user_email: string | null;
  event_type: string;
  event_name: string;
  page:       string | null;
  props:      Record<string, unknown> | null;
  created_at: string;
}

export interface AdminFeedback {
  id:         number;
  user_name:  string | null;
  user_email: string | null;
  category:   string;
  rating:     number | null;
  message:    string;
  page:       string | null;
  context:    Record<string, unknown> | null;
  created_at: string;
}
