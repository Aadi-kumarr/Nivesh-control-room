import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useData } from "../DataContext";
import { CLASS_NAMES, CLASS_ORDER, age } from "../format";
import type { Backups } from "../types";
import { ProfileMenu } from "./ProfileMenu";

function lastBackup(backups: Backups | null): string {
  const times = [backups?.auto[0], backups?.daily[0], backups?.exports[0]]
    .map((file) => file?.modified).filter(Boolean) as string[];
  if (!times.length) return "none yet";
  const latest = new Date(times.sort().at(-1) as string);
  return latest.toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export function Layout() {
  const {
    portfolio, backups, activeProfile, loadError, notices, refreshing, exporting, refreshPrices, exportBackup,
    dismissNotices,
  } = useData();
  const fx = portfolio?.fx;
  const warnings = portfolio?.warnings ?? [];
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          Nivesh <span>Control Room</span>
        </NavLink>
        <nav className="nav" aria-label="Sections">
          <NavLink to="/" end>Dashboard</NavLink>
          {CLASS_ORDER.map((id) => (
            <NavLink key={id} to={`/asset/${id}`}>{CLASS_NAMES[id]}</NavLink>
          ))}
        </nav>
        <div className="status">
          <div className="readout">
            <span className="label">Prices</span>
            <span data-testid="price-age">{age(portfolio?.price_age_minutes)}</span>
          </div>
          <div className="readout">
            <span className="label">USDINR market / used</span>
            <span>{fx ? `${fx.usdinr_market.toFixed(2)} / ${fx.usdinr_used.toFixed(2)}` : "—"}</span>
          </div>
          <div className="readout">
            <span className="label">Last backup</span>
            <span data-testid="last-backup">{lastBackup(backups)}</span>
          </div>
          <button className="button ghost" onClick={() => void exportBackup()} disabled={exporting}>
            {exporting ? "Saving…" : "Export backup"}
          </button>
          <button className="button primary" onClick={() => void refreshPrices()} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh prices"}
          </button>
          <ProfileMenu />
        </div>
      </header>

      {(warnings.length > 0 || notices.length > 0 || loadError) && (
        <div className="banner" role="alert">
          <ul>
            {loadError && <li>{loadError}</li>}
            {warnings.map((warning) => <li key={warning}>{warning}</li>)}
            {notices.map((notice, index) => <li key={`${index}-${notice}`}>{notice}</li>)}
          </ul>
          {notices.length > 0 && (
            <button className="button ghost small" onClick={dismissNotices}>Dismiss</button>
          )}
        </div>
      )}

      {/* Keyed by profile: switching remounts the page, so it reloads everything and
          closes any open form for the previous person. */}
      <main className="page"><Outlet key={activeProfile?.id ?? "none"} /></main>
    </div>
  );
}
