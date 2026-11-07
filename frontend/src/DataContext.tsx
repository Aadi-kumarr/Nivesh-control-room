import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { Backups, Portfolio } from "./types";

interface Data {
  portfolio: Portfolio | null;
  backups: Backups | null;
  loadError: string | null;
  notices: string[];
  refreshing: boolean;
  exporting: boolean;
  reload: () => Promise<void>;
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [exporting, setExporting] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [nextPortfolio, nextBackups] = await Promise.all([api.portfolio(), api.backups()]);
      setPortfolio(nextPortfolio);
      setBackups(nextBackups);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load the portfolio.");
    }
  }, []);

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

  useEffect(() => {
    void reload();
  }, [reload]);

  const value = useMemo(
    () => ({
      portfolio, backups, loadError, notices, refreshing, exporting, reload, refreshPrices, exportBackup, addNotices,
      dismissNotices: () => setNotices([]),
    }),
    [portfolio, backups, loadError, notices, refreshing, exporting, reload, refreshPrices, exportBackup, addNotices],
  );
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}
