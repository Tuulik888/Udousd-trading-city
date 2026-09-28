export type AgentName = "Trend" | "Reverter" | "Breaker";

export type AgentActivity = "idle" | "thinking" | "backtesting" | "trading" | "frozen";

export interface StatusResponse {
  kill_switch_active: boolean;
  agents: Record<string, AgentActivity>;
}

export interface LeaderboardRow {
  agent: string;
  sharpe: number | null;
  equity: number | null;
  total_pips: number;
}

export interface Decision {
  id: number;
  strategy_config: Record<string, unknown>;
  reasoning: string;
  created_at: string;
}

export interface Trade {
  id: number;
  oanda_trade_id: string;
  instrument: string;
  direction: number;
  units: number;
  entry_price: number;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  pips: number | null;
  status: "open" | "closed";
  reasoning: string;
}

export interface EquityPoint {
  equity: number;
  at: string;
}

export interface BacktestSummary {
  id: number;
  sharpe_train: number;
  sharpe_test: number;
  max_dd_train: number;
  max_dd_test: number;
  win_rate_train: number;
  win_rate_test: number;
  trade_count_train: number;
  trade_count_test: number;
  pips_train: number;
  pips_test: number;
  passed_promotion_bar: boolean;
  created_at: string;
}

export interface AgentDetail {
  agent: string;
  style: string;
  status: AgentActivity;
  decisions: Decision[];
  open_trades: Trade[];
  trades: Trade[];
  equity_curve: EquityPoint[];
  latest_backtest: BacktestSummary | null;
}
