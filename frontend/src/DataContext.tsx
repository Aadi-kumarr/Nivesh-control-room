import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, isAbort, onWrite, setActiveProfileId } from "./api";
import { createStore, writeScope } from "./store";
import { ALL_PERIOD, periodDates } from "./periods";
import type { PeriodChoice } from "./periods";
import type { Backups, History, PeriodReturn, Portfolio, Profile } from "./types";

const PROFILE_KEY = "nivesh.activeProfileId";

function storedProfileId(): string | null {
  try {
    return localStorage.getItem(PROFILE_KEY);
  } catch {
    return null;
  }
}

function storeProfileId(id: string) {
  try {
    localStorage.setItem(PROFILE_KEY, id);
  } catch {
    // Private windows can block storage; the app still works, it just won't remember.
  }
}

/** One store for the app: per-profile cache, aborts on switch, cleared by writes. */
export const store = createStore<Portfolio, History, Backups, PeriodReturn>({
  portfolio: (profileId, signal) => api.portfolio(profileId, signal),
  history: (profileId, signal) => api.history(profileId, signal),
  period: (profileId, start, end, signal) => api.periodReturn(profileId, start, end, signal),
  backups: (signal) => api.backups(signal),
});
onWrite((method, path, profileId) => store.written(writeScope(method, path, profileId)));

interface Data {
  portfolio: Portfolio | null;
  backups: Backups | null;
  profiles: Profile[];
  activeProfile: Profile | null;
  loadError: string | null;
  notices: string[];
  refreshing: boolean;
  exporting: boolean;
  reload: () => Promise<void>;
  reloadProfiles: () => Promise<Profile[]>;
  switchProfile: (id: string) => void;
  refreshPrices: () => Promise<void>;
  exportBackup: () => Promise<void>;
  addNotices: (messages: string[]) => void;
  dismissNotices: () => void;
  /** One time frame shared by the dashboard, asset-class and instrument pages. */
  period: PeriodChoice;
  setPeriod: (choice: PeriodChoice) => void;
  /** Returns for the chosen time frame; null for "All" (the existing XIRR is shown). */
  periodResult: PeriodReturn | null;
  periodLoading: boolean;
  periodError: string | null;
}

const DataContext = createContext<Data | null>(null);

export function useData(): Data {
  const data = useContext(DataContext);
  if (!data) throw new Error("useData must be used inside DataProvider");
  return data;
}

export function DataProvider({ children }: { children: ReactNode }) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [backups, setBackups] = useState<Backups | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [period, setPeriod] = useState<PeriodChoice>(ALL_PERIOD);
  const [periodResult, setPeriodResult] = useState<PeriodReturn | null>(null);
  const [periodLoading, setPeriodLoading] = useState(false);
  const [periodError, setPeriodError] = useState<string | null>(null);

  const loadBackups = useCallback(async () => {
    try {
      setBackups(await store.backups());
    } catch {
      // Only the header's "Last backup" readout uses this; the portfolio still loads.
    }
  }, []);

  /** The active profile's data: cached when fresh (or after no write), fetched otherwise. */
  const load = useCallback(async (force: boolean) => {
    try {
      const next = await store.portfolio(force);
      if (next) {
        setPortfolio(next);
        setLoadError(null);
      }
    } catch (error) {
      if (isAbort(error)) return; // the profile changed; its own load is running
      setLoadError(error instanceof Error ? error.message : "Could not load the portfolio.");
    }
    void loadBackups();
  }, [loadBackups]);

  /** After a write: the write already cleared what it changed, so this refetches only that. */
  const reload = useCallback(() => load(false), [load]);

  const reloadProfiles = useCallback(async () => {
    const { profiles: list } = await api.profiles();
    setProfiles(list);
    return list;
  }, []);

  const switchProfile = useCallback((id: string) => {
    if (id === store.active) return;
    store.switchTo(id); // aborts the previous profile's requests
    setActiveProfileId(id);
    storeProfileId(id);
    setActiveId(id);
    // Shown at once from the cache, or blank while loading: never the previous person's numbers.
    setPortfolio(store.cachedPortfolio());
    setLoadError(null);
  }, []);

  // First load: the remembered profile if it still exists, otherwise the default one.
  useEffect(() => {
    reloadProfiles()
      .then((list) => {
        const remembered = storedProfileId();
        const start = list.find((p) => p.id === remembered) ?? list.find((p) => p.is_default) ?? list[0];
        if (start) switchProfile(start.id);
        else setLoadError("No profiles found. Run scripts\\migrate_profiles.py.");
      })
      .catch((error: Error) => setLoadError(error.message));
  }, [reloadProfiles, switchProfile]);

  useEffect(() => {
    if (activeId) void load(false);
  }, [activeId, load]);

  // Computed only when a time frame other than "All" is chosen. Runs again when the portfolio
  // changes (a write or a price refresh), which is when the store has dropped the old result.
  useEffect(() => {
    const dates = periodDates(period);
    setPeriodError(null);
    if (!dates || !activeId || !portfolio) {
      setPeriodResult(null);
      setPeriodLoading(false);
      return;
    }
    let current = true;
    const cached = store.cachedPeriod(dates.start, dates.end);
    setPeriodResult(cached);
    setPeriodLoading(!cached);
    store.period(dates.start, dates.end)
      .then((result) => { if (current && result) setPeriodResult(result); })
      .catch((error: Error) => {
        if (current && !isAbort(error)) {
          setPeriodResult(null);
          setPeriodError(error.message);
        }
      })
      .finally(() => { if (current) setPeriodLoading(false); });
    return () => { current = false; };
  }, [period, activeId, portfolio]);

  const addNotices = useCallback((messages: string[]) => {
    if (messages.length) setNotices((current) => [...current, ...messages]);
  }, []);

  const refreshPrices = useCallback(async () => {
    setRefreshing(true);
    try {
      await api.refreshPrices(); // a write: clears every profile's cache (prices are shared)
      await load(true); // failures that matter come back as portfolio warnings
    } catch (error) {
      addNotices([error instanceof Error ? error.message : "Price refresh failed."]);
    } finally {
      setRefreshing(false);
    }
  }, [addNotices, load]);

  const exportBackup = useCallback(async () => {
    setExporting(true);
    try {
      const { path } = await api.exportBackup();
      addNotices([`Backup saved to ${path}`]);
      store.backupsChanged();
      await loadBackups();
    } catch (error) {
      addNotices([error instanceof Error ? error.message : "Backup was not saved."]);
    } finally {
      setExporting(false);
    }
  }, [addNotices, loadBackups]);

  const activeProfile = profiles.find((p) => p.id === activeId) ?? null;

  const value = useMemo(
    () => ({
      portfolio, backups, profiles, activeProfile, loadError, notices, refreshing, exporting,
      reload, reloadProfiles, switchProfile, refreshPrices, exportBackup, addNotices,
      dismissNotices: () => setNotices([]),
      period, setPeriod, periodResult, periodLoading, periodError,
    }),
    [portfolio, backups, profiles, activeProfile, loadError, notices, refreshing, exporting,
      reload, reloadProfiles, switchProfile, refreshPrices, exportBackup, addNotices,
      period, periodResult, periodLoading, periodError],
  );
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}
