import { Suspense, lazy, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, isAbort } from "../api";
import { AddTransaction } from "../components/AddTransaction";
import { ProfileLine } from "../components/ProfileMenu";
import { ReturnCell, ReturnStat, useReturnHeading } from "../components/PeriodReturn";
import { Modal, Money, Percent, Stat } from "../components/common";
import { store, useData } from "../DataContext";

// The charting library is over half the app's code, so it loads only when a chart shows.
const AllocationDonut = lazy(() => import("../components/Charts").then((m) => ({ default: m.AllocationDonut })));
const GrowthChart = lazy(() => import("../components/Charts").then((m) => ({ default: m.GrowthChart })));

function ChartPlaceholder({ height, label }: { height: number; label?: string }) {
  return <div className="chart-placeholder" style={{ minHeight: height }}>{label && <p className="muted">{label}</p>}</div>;
}

/** True once the element has been on screen (then stays true). */
function useInView(element: HTMLElement | null): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (!element || seen) return;
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setSeen(true);
    }, { rootMargin: "200px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, seen]);
  return seen;
}
import { CLASS_NAMES, CLASS_ORDER, inr, signed } from "../format";
import type { HistoryPoint, PeriodResult, PeriodReturn, Summary } from "../types";

function CashDialog({ cash, onClose }: { cash: number; onClose: () => void }) {
  const { reload, addNotices } = useData();
  const [text, setText] = useState(String(cash));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      addNotices((await api.setCash(Number(text))).warnings);
      await reload();
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save.");
      setSaving(false);
    }
  }

  return (
    <Modal title="Update cash" onClose={onClose}>
      <ProfileLine label="Cash for" />
      <form onSubmit={(event) => void save(event)}>
        <label>Cash (₹)
          <input type="number" min="0" step="any" value={text}
            onChange={(e) => setText(e.target.value)} autoFocus required />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** The Realised, Unrealised, Total and XIRR (or period return) cells, shared by the class rows and TOTAL. */
function PnlCells({ row, pick }: { row: Summary; pick: (period: PeriodReturn) => PeriodResult | undefined }) {
  return (
    <>
      <td className="num"><Money value={row.realised_pnl} /></td>
      <td className="num">
        <Money value={row.unrealised_pnl} />
        {row.unrealised_pnl_pct !== null && (
          <div className="subline"><Percent value={row.unrealised_pnl_pct} /></div>
        )}
      </td>
      <td className="num"><Money value={row.pnl} /></td>
      <td className="num"><ReturnCell xirr={row.xirr} pick={pick} /></td>
    </>
  );
}

export function Dashboard() {
  const { portfolio, activeProfile, reload, addNotices } = useData();
  const [addingTrade, setAddingTrade] = useState(false);
  const [points, setPoints] = useState<HistoryPoint[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [editingCash, setEditingCash] = useState(false);
  const [historyCard, setHistoryCard] = useState<HTMLElement | null>(null);
  const historyVisible = useInView(historyCard);
  const asOf = portfolio?.as_of;
  const returnHeading = useReturnHeading();

  // Only once the chart is on screen, and after the portfolio, so today's point uses the
  // same stored prices as the cards. The store caches it per profile for that portfolio.
  useEffect(() => {
    if (!asOf || !historyVisible) return;
    let current = true;
    store.history(asOf)
      .then((result) => { if (current && result) { setPoints(result.points); setHistoryError(null); } })
      .catch((failure: Error) => { if (current && !isAbort(failure)) setHistoryError(failure.message); });
    return () => { current = false; };
  }, [asOf, historyVisible]);

  if (!portfolio) return <p className="muted">Loading portfolio…</p>;
  const total = portfolio.portfolio;

  if (portfolio.instruments.length === 0) {
    return (
      <section className="card empty-state" data-testid="empty-state">
        <h1>{activeProfile?.name ?? portfolio.profile.name} has no transactions yet</h1>
        <p className="muted">Add a trade to start tracking this profile. Instruments and prices are shared,
          so you can pick any instrument you already track or create a new one.</p>
        <button className="button primary" onClick={() => setAddingTrade(true)}>Add first transaction</button>
        {addingTrade && (
          <AddTransaction
            onClose={() => setAddingTrade(false)}
            onSaved={(warnings) => {
              addNotices(warnings);
              setAddingTrade(false);
              void reload();
            }}
          />
        )}
      </section>
    );
  }

  return (
    <>
      <section className="stats five">
        <Stat label="Total portfolio value"><span data-testid="total-value">{inr(total.value)}</span></Stat>
        <Stat label="Total profit / loss">
          <span className={signed(total.pnl)} data-testid="total-pnl">{inr(total.pnl)}</span>
        </Stat>
        <Stat label="Realised P&L">
          <span className={signed(total.realised_pnl)} data-testid="total-realised">{inr(total.realised_pnl)}</span>
        </Stat>
        <Stat label="Unrealised P&L" sub={<span data-testid="total-unrealised-pct"><Percent value={total.unrealised_pnl_pct} /></span>}>
          <span className={signed(total.unrealised_pnl)} data-testid="total-unrealised">{inr(total.unrealised_pnl)}</span>
        </Stat>
        <ReturnStat
          label="Portfolio XIRR" xirr={total.xirr} pick={(p) => p.portfolio} testId="total-xirr"
          sub={<span className="muted small-text">Based on all cash flows and current portfolio value.</span>}
        />
      </section>

      <section className="split">
        <div className="card">
          <h2>Asset class overview</h2>
          <p className="muted small-text">Allocation and performance - Click any asset class to drill down.</p>
          <div className="table-wrap">
            <table data-testid="overview">
              <thead>
                <tr>
                  <th>Asset class</th><th className="num">Value</th><th className="num">Realised P&L</th>
                  <th className="num">Unrealised P&L</th><th className="num">Total P&L</th>
                  <th className="num">{returnHeading}</th><th className="num">Action</th>
                </tr>
              </thead>
              <tbody>
                {CLASS_ORDER.filter((id) => portfolio.asset_classes[id]).map((id) => {
                  const row = portfolio.asset_classes[id];
                  return (
                    <tr key={id} data-class={id}>
                      <td><Link to={`/asset/${id}`}>{CLASS_NAMES[id]}</Link></td>
                      <td className="num">{inr(row.value)}</td>
                      <PnlCells row={row} pick={(p) => p.asset_classes[id]} />
                      <td className="num"><Link to={`/asset/${id}`}>View</Link></td>
                    </tr>
                  );
                })}
                <tr data-class="cash">
                  <td>Cash</td>
                  <td className="num">{inr(total.cash_inr)}</td>
                  <td className="num muted">N/A</td>
                  <td className="num muted">N/A</td>
                  <td className="num muted">N/A</td>
                  <td className="num muted">N/A</td>
                  <td className="num"><button className="link" onClick={() => setEditingCash(true)}>Update</button></td>
                </tr>
              </tbody>
              <tfoot>
                <tr data-class="total">
                  <td>TOTAL</td>
                  <td className="num">{inr(total.value)}</td>
                  <PnlCells row={total} pick={(p) => p.portfolio} />
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
        <div className="card">
          <h2>Allocation</h2>
          <Suspense fallback={<ChartPlaceholder height={300} />}>
            <AllocationDonut portfolio={portfolio} />
          </Suspense>
        </div>
      </section>

      <section className="card" ref={setHistoryCard} data-testid="history-card">
        {historyError && <p className="form-error">{historyError}</p>}
        {!points && !historyError && <ChartPlaceholder height={380} label="Loading history…" />}
        {points && (
          <Suspense fallback={<ChartPlaceholder height={380} label="Loading history…" />}>
            <GrowthChart points={points} />
          </Suspense>
        )}
      </section>

      {editingCash && <CashDialog cash={total.cash_inr} onClose={() => setEditingCash(false)} />}
    </>
  );
}
