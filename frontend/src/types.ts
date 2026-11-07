export interface Summary {
  value: number;
  buy_amount: number;
  sell_amount: number;
  cost_basis: number;
  pnl: number;
  realised_pnl: number;
  unrealised_pnl: number;
  unrealised_pnl_pct: number | null;
  xirr: number | null;
  holding_days: number | null;
}

export interface InstrumentRow extends Summary {
  id: string;
  name: string;
  symbol: string | null;
  asset_class: string;
  needs_review: boolean;
  valuation_price_inr: number;
  price_source: "yahoo" | "yahoo_last_known" | "manual";
  price_status: string;
  price_age_minutes: number | null;
  last_price: number | null;
  last_price_currency: string | null;
  fx_used: number | null;
  qty: number;
  avg_cost: number | null;
}

export interface Fx {
  date: string;
  usdinr_market: number;
  usdinr_used: number;
  age_minutes?: number | null;
  source?: string;
  rate_date?: string;
}

export interface Portfolio {
  as_of: string;
  last_price_fetch: string | null;
  price_age_minutes: number | null;
  fx: Fx | null;
  warnings: string[];
  portfolio: Summary & { holdings_value: number; cash_inr: number };
  asset_classes: Record<string, Summary>;
  instruments: InstrumentRow[];
}

export interface Instrument {
  id: string;
  asset_class: string;
  name: string;
  symbol: string | null;
  price_source: "yahoo" | "manual";
  quote_currency: "INR" | "USD";
  manual_price_inr: number;
}

export interface Transaction {
  id: string;
  instrument_id: string;
  date: string;
  type: "BUY" | "SELL";
  quantity: number;
  price_inr: number;
  currency: "INR" | "USD";
  price_usd: number | null;
  fx_rate_market?: number | null;
  fx_rate_used: number | null;
  fx_override?: boolean;
  kind: string;
  note: string;
}

export interface InstrumentDetail {
  instrument: Instrument;
  transactions: Transaction[];
  summary: InstrumentRow;
}

export interface WriteResult {
  backup: string | null;
  warnings: string[];
}

export interface BackupFile {
  name: string;
  size_bytes: number;
  modified: string;
}

export interface Backups {
  auto: BackupFile[];
  daily: BackupFile[];
  exports: BackupFile[];
  manual: BackupFile[];
}

export interface HistoryValues {
  value: number;
  net_invested: number;
  estimated_value: number;
  estimated: boolean;
}

export interface HistoryPoint extends HistoryValues {
  date: string;
  asset_classes: Record<string, HistoryValues>;
}

export interface History {
  points: HistoryPoint[];
}

export interface SymbolCheck {
  symbol: string;
  price: number;
  currency: "INR" | "USD";
}
