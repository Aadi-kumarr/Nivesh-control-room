/**
 * Per-profile response cache and request bookkeeping. No React here, so it can be tested
 * with `node --test`.
 *
 * - Portfolio and history are cached per profile, for up to 15 minutes (the server's
 *   price refresh rule), so switching back to a profile already viewed costs no requests.
 * - A write clears what it can change: transactions and cash clear that profile's cache;
 *   instruments and prices are shared, so they clear every profile's cache.
 * - Switching profile aborts the previous profile's requests, and a response is only ever
 *   stored under the profile it was requested for and only shown while that profile is active.
 */

export const CACHE_MS = 15 * 60 * 1000;

export interface Fetchers<P, H, B, R = unknown> {
  portfolio: (profileId: string, signal: AbortSignal) => Promise<P>;
  history: (profileId: string, signal: AbortSignal) => Promise<H>;
  backups: (signal: AbortSignal) => Promise<B>;
  /** Returns for a time frame; end null means today. */
  period?: (profileId: string, start: string, end: string | null, signal: AbortSignal) => Promise<R>;
}

interface Entry<T> {
  data: T;
  at: number;
  /** For history: the portfolio as_of it was fetched with, so its last point matches. */
  key?: string;
}

interface ProfileCache<P, H, R> {
  portfolio?: Entry<P>;
  history?: Entry<H>;
  /** Keyed by "start|end". */
  periods?: Map<string, Entry<R>>;
}

export type WriteScope = { kind: "profile"; profileId: string } | { kind: "all" } | { kind: "none" };

/** What a successful write invalidates, from its method and path (without /api). */
export function writeScope(method: string, path: string, profileId: string | null): WriteScope {
  if (method === "GET") return { kind: "none" };
  if (path.startsWith("/transactions") || path.startsWith("/cash")) {
    return profileId ? { kind: "profile", profileId } : { kind: "all" };
  }
  if (path.startsWith("/profiles/") && method === "DELETE") {
    return { kind: "profile", profileId: decodeURIComponent(path.split("/")[2]) };
  }
  if (path.startsWith("/instruments") || path.startsWith("/prices")) return { kind: "all" };
  return { kind: "none" }; // export, profile create/rename: no portfolio data changes
}

export function createStore<P, H, B, R = unknown>(fetchers: Fetchers<P, H, B, R>, now: () => number = Date.now) {
  const caches = new Map<string, ProfileCache<P, H, R>>();
  // Bumped by every invalidation, so a response requested before a write is not cached.
  let generation = 0;
  let backups: Entry<B> | undefined;
  let active: string | null = null;
  let controller = new AbortController();
  const listeners = new Set<() => void>();

  const cacheFor = (profileId: string) => {
    let cache = caches.get(profileId);
    if (!cache) {
      cache = {};
      caches.set(profileId, cache);
    }
    return cache;
  };
  const fresh = <T>(entry: Entry<T> | undefined) => entry !== undefined && now() - entry.at < CACHE_MS;
  const notify = () => listeners.forEach((listener) => listener());

  return {
    get active() {
      return active;
    },

    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    /** Make a profile active. Requests still running for the previous one are aborted. */
    switchTo(profileId: string) {
      if (profileId === active) return;
      controller.abort();
      controller = new AbortController();
      active = profileId;
      notify();
    },

    /** Cached data for the active profile only, so nothing shows under the wrong name. */
    cachedPortfolio(): P | null {
      if (!active) return null;
      return caches.get(active)?.portfolio?.data ?? null;
    },

    /** The active profile's portfolio: from the cache when fresh, otherwise fetched.
     * Resolves to null when the profile changed before the response arrived. */
    async portfolio(force = false): Promise<P | null> {
      const profileId = active;
      if (!profileId) return null;
      const cache = cacheFor(profileId);
      if (!force && fresh(cache.portfolio)) return cache.portfolio!.data;
      const started = generation;
      const data = await fetchers.portfolio(profileId, controller.signal);
      if (started === generation) cacheFor(profileId).portfolio = { data, at: now() };
      if (active !== profileId) return null;
      notify();
      return data;
    },

    /** History for the active profile, matching the portfolio it is shown with (asOf). */
    async history(asOf: string): Promise<H | null> {
      const profileId = active;
      if (!profileId) return null;
      const cached = cacheFor(profileId).history;
      if (cached && cached.key === asOf && fresh(cached)) return cached.data;
      const started = generation;
      const data = await fetchers.history(profileId, controller.signal);
      if (started === generation) cacheFor(profileId).history = { data, at: now(), key: asOf };
      return active === profileId ? data : null;
    },

    /** Returns for (start, end] for the active profile, fetched only when asked for and
     * cached per profile and period. end null means today, which uses today's prices,
     * so like the portfolio it is kept for at most 15 minutes. */
    async period(start: string, end: string | null): Promise<R | null> {
      const profileId = active;
      if (!profileId || !fetchers.period) return null;
      const key = `${start}|${end ?? ""}`;
      const cache = cacheFor(profileId);
      const cached = cache.periods?.get(key);
      if (cached && fresh(cached)) return cached.data;
      const started = generation;
      const data = await fetchers.period(profileId, start, end, controller.signal);
      if (started === generation) {
        const periods = cacheFor(profileId).periods ?? new Map<string, Entry<R>>();
        periods.set(key, { data, at: now() });
        cacheFor(profileId).periods = periods;
      }
      return active === profileId ? data : null;
    },

    /** Cached period result for the active profile, if any (shown at once on a switch). */
    cachedPeriod(start: string, end: string | null): R | null {
      if (!active) return null;
      const cached = caches.get(active)?.periods?.get(`${start}|${end ?? ""}`);
      return cached && fresh(cached) ? cached.data : null;
    },

    /** Backups are not per profile: fetched once, and again after a write. */
    async backups(): Promise<B> {
      if (backups) return backups.data;
      const data = await fetchers.backups(new AbortController().signal);
      backups = { data, at: now() };
      return data;
    },

    /** Call after every successful write. */
    written(scope: WriteScope) {
      if (scope.kind === "none") return;
      backups = undefined; // every write takes a snapshot
      generation += 1;
      if (scope.kind === "all") caches.clear();
      else caches.delete(scope.profileId);
    },

    backupsChanged() {
      backups = undefined;
    },

    /** For tests and the profile menu. */
    hasCached(profileId: string) {
      const cache = caches.get(profileId);
      return Boolean(cache?.portfolio || cache?.history || cache?.periods?.size);
    },
  };
}

export type Store<P, H, B, R = unknown> = ReturnType<typeof createStore<P, H, B, R>>;
