import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, setActiveProfileId } from "./api";
import type { Backups, Portfolio, Profile } from "./types";

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
  // Responses for a profile that is no longer active are dropped.
  const activeRef = useRef<string | null>(null);

  const reload = useCallback(async () => {
    const requested = activeRef.current;
    if (!requested) return;
    try {
      const [nextPortfolio, nextBackups] = await Promise.all([api.portfolio(), api.backups()]);
      if (activeRef.current !== requested) return;
      setPortfolio(nextPortfolio);
      setBackups(nextBackups);
      setLoadError(null);
    } catch (error) {
      if (activeRef.current !== requested) return;
      setLoadError(error instanceof Error ? error.message : "Could not load the portfolio.");
    }
  }, []);

  const reloadProfiles = useCallback(async () => {
    const { profiles: list } = await api.profiles();
    setProfiles(list);
    return list;
  }, []);

  const switchProfile = useCallback((id: string) => {
    if (id === activeRef.current) return;
    activeRef.current = id;
    setActiveProfileId(id);
    storeProfileId(id);
    setActiveId(id);
    setPortfolio(null); // never show the previous person's numbers while loading
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
    if (activeId) void reload();
  }, [activeId, reload]);

  const addNotices = useCallback((messages: string[]) => {
    if (messages.length) setNotices((current) => [...current, ...messages]);
  }, []);

  const refreshPrices = useCallback(async () => {
    setRefreshing(true);
    try {
      await api.refreshPrices();
      await reload(); // failures that matter come back as portfolio warnings
    } catch (error) {
      addNotices([error instanceof Error ? error.message : "Price refresh failed."]);
    } finally {
      setRefreshing(false);
    }
  }, [addNotices, reload]);

  const exportBackup = useCallback(async () => {
    setExporting(true);
    try {
      const { path } = await api.exportBackup();
      addNotices([`Backup saved to ${path}`]);
      await reload();
    } catch (error) {
      addNotices([error instanceof Error ? error.message : "Backup was not saved."]);
    } finally {
      setExporting(false);
    }
  }, [addNotices, reload]);

  const activeProfile = profiles.find((p) => p.id === activeId) ?? null;

  const value = useMemo(
    () => ({
      portfolio, backups, profiles, activeProfile, loadError, notices, refreshing, exporting,
      reload, reloadProfiles, switchProfile, refreshPrices, exportBackup, addNotices,
      dismissNotices: () => setNotices([]),
    }),
    [portfolio, backups, profiles, activeProfile, loadError, notices, refreshing, exporting,
      reload, reloadProfiles, switchProfile, refreshPrices, exportBackup, addNotices],
  );
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}
