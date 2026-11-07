import type {
  Backups, Fx, History, Instrument, InstrumentDetail, Portfolio, SymbolCheck, Transaction, WriteResult,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = item.loc?.[item.loc.length - 1];
        const message = (item.msg ?? "is invalid").replace(/^Value error, /, "");
        return field && field !== "body" ? `${field}: ${message}` : message;
      })
      .join("; ");
  }
  return `Request failed (${status}).`;
}

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(data, response.status), response.status);
  return data as T;
}

type InstrumentResult = WriteResult & { instrument: { id: string } };

export const api = {
  portfolio: () => request<Portfolio>("/portfolio"),
  refreshPrices: () => request<object>("/prices/refresh", "POST"),
  history: () => request<History>("/history?interval=monthly"),
  backups: () => request<Backups>("/backups"),
  exportBackup: () => request<{ path: string }>("/export", "POST"),
  fx: (date: string) => request<Fx>(`/fx?date=${date}`),
  checkSymbol: (assetClass: string, symbol: string) =>
    request<SymbolCheck>(
      `/symbols/check?asset_class=${assetClass}&symbol=${encodeURIComponent(symbol)}`,
    ),
  instrument: (id: string) => request<InstrumentDetail>(`/instruments/${id}`),
  createInstrument: (body: object) => request<InstrumentResult>("/instruments", "POST", body),
  updateInstrument: (id: string, body: Partial<Instrument>) =>
    request<WriteResult>(`/instruments/${id}`, "PATCH", body),
  deleteInstrument: (id: string) => request<WriteResult>(`/instruments/${id}`, "DELETE"),
  createTransaction: (body: object) => request<WriteResult>("/transactions", "POST", body),
  updateTransaction: (id: string, body: Partial<Transaction>) =>
    request<WriteResult>(`/transactions/${id}`, "PATCH", body),
  deleteTransaction: (id: string) => request<WriteResult>(`/transactions/${id}`, "DELETE"),
  setCash: (cash: number) => request<WriteResult>("/cash", "PUT", { cash_inr: cash }),
};
