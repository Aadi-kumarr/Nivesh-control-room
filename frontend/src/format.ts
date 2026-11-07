const inrFormat = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const usdFormat = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const qtyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 6 });

export const inr = (value: number) => inrFormat.format(value);
export const usd = (value: number) => usdFormat.format(value);
export const qty = (value: number) => qtyFormat.format(value);

/** Short form for chart axes: ₹4.3L, ₹1.2Cr. */
export function inrShort(value: number): string {
  const size = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (size >= 1e7) return `${sign}₹${(size / 1e7).toFixed(1)}Cr`;
  if (size >= 1e5) return `${sign}₹${(size / 1e5).toFixed(1)}L`;
  if (size >= 1e3) return `${sign}₹${(size / 1e3).toFixed(0)}K`;
  return `${sign}₹${size.toFixed(0)}`;
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}%`;
}

/** The real XIRR, however large. "-" means it can't be calculated. */
export function xirrText(value: number | null): string {
  return value === null ? "-" : percent(value);
}

export function signed(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "gain" : "loss";
}

export function age(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} hr ago`;
  return `${Math.round(minutes / 60 / 24)} days ago`;
}

export function monthLabel(iso: string): string {
  const [year, month] = iso.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export function dateLabel(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
  });
}

export function todayIso(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export const CLASS_NAMES: Record<string, string> = {
  "indian-equities": "Indian Equities",
  "us-equities": "US Equities",
  crypto: "Crypto",
  fno: "F&O",
};

export const CLASS_ORDER = ["indian-equities", "us-equities", "crypto", "fno"];

/** Mirrors prices.normalize_symbol on the server, for the live helper in forms. */
export function normalizeSymbol(assetClass: string, typed: string): string {
  const symbol = typed.trim().toUpperCase();
  if (!symbol) return "";
  if (assetClass === "indian-equities" && !symbol.includes(".")) return `${symbol}.NS`;
  if (assetClass === "crypto" && !symbol.includes("-")) return `${symbol}-INR`;
  return symbol;
}
