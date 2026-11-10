import type {
  Backups, Fx, History, Instrument, InstrumentDetail, InstrumentListItem, PeriodReturn, Portfolio, Profile,
  SymbolCheck,
  Transaction, WriteResult,
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

/** Sent on every request; the server scopes per-person data to it (unknown -> default). */
let activeProfileId: string | null = null;

export function setActiveProfileId(id: string | null) {
  activeProfileId = id;
}

type WriteListener = (method: string, path: string, profileId: string | null) => void;
let writeListener: WriteListener | null = null;

/** Called after every successful write, so cached responses can be dropped. */
export function onWrite(listener: WriteListener) {
  writeListener = listener;
}

interface Options {
  /** Ties the request to this profile instead of whichever is active when it is sent. */
  profileId?: string;
  signal?: AbortSignal;
}

async function request<T>(path: string, method = "GET", body?: unknown, options: Options = {}): Promise<T> {
  const profileId = options.profileId ?? activeProfileId;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (profileId) headers["X-Profile-Id"] = profileId;
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(data, response.status), response.status);
  if (method !== "GET") writeListener?.(method, path, profileId);
  return data as T;
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

type InstrumentResult = WriteResult & { instrument: { id: string } };

export const api = {
  portfolio: (profileId: string, signal?: AbortSignal) =>
    request<Portfolio>("/portfolio", "GET", undefined, { profileId, signal }),
  refreshPrices: () => request<object>("/prices/refresh", "POST"),
  history: (profileId: string, signal?: AbortSignal) =>
    request<History>("/history?interval=monthly", "GET", undefined, { profileId, signal }),
  backups: (signal?: AbortSignal) => request<Backups>("/backups", "GET", undefined, { signal }),
  periodReturn: (profileId: string, start: string, end: string | null, signal?: AbortSignal) =>
    request<PeriodReturn>(
      `/xirr?start=${start}${end ? `&end=${end}` : ""}`, "GET", undefined, { profileId, signal },
    ),
  exportBackup: () => request<{ path: string }>("/export", "POST"),
  fx: (date: string) => request<Fx>(`/fx?date=${date}`),
  checkSymbol: (assetClass: string, symbol: string) =>
    request<SymbolCheck>(
      `/symbols/check?asset_class=${assetClass}&symbol=${encodeURIComponent(symbol)}`,
    ),
  profiles: () => request<{ profiles: Profile[] }>("/profiles"),
  createProfile: (body: { name: string; colour: string }) =>
    request<WriteResult & { profile: Profile }>("/profiles", "POST", body),
  deleteProfile: (id: string) =>
    request<WriteResult & { transactions_removed: number; profile_backup: string }>(`/profiles/${id}`, "DELETE"),
  instruments: () => request<{ instruments: InstrumentListItem[] }>("/instruments"),
  instrument: (id: string, signal?: AbortSignal) =>
    request<InstrumentDetail>(`/instruments/${id}`, "GET", undefined, { signal }),
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
