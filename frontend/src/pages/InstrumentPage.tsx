import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { InstrumentForm } from "../components/InstrumentForm";
import { TransactionForm } from "../components/TransactionForm";
import { ConfirmDialog, Percent, PriceBadge, Stat, Xirr } from "../components/common";
import { useData } from "../DataContext";
import { CLASS_NAMES, dateLabel, inr, qty, signed, usd } from "../format";
import type { InstrumentDetail, Transaction } from "../types";
import { PriceCell } from "./AssetClass";

type Dialog =
  | { kind: "edit-instrument" }
  | { kind: "delete-instrument" }
  | { kind: "add-transaction" }
  | { kind: "edit-transaction"; transaction: Transaction }
  | { kind: "delete-transaction"; transaction: Transaction };

export function InstrumentPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { reload, addNotices } = useData();
  const [detail, setDetail] = useState<InstrumentDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await api.instrument(id));
      setLoadError(null);
    } catch (failure) {
      setLoadError(failure instanceof Error ? failure.message : "Could not load the instrument.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const saved = (warnings: string[]) => {
    addNotices(warnings);
    setDialog(null);
    void load();
    void reload();
  };

  async function confirmDelete(action: () => Promise<{ warnings: string[] }>, after: () => void) {
    setDeleting(true);
    setDeleteError(null);
    try {
      addNotices((await action()).warnings);
      setDialog(null);
      after();
    } catch (failure) {
      setDeleteError(failure instanceof Error ? failure.message : "Could not delete.");
    } finally {
      setDeleting(false);
    }
  }

  const close = () => {
    setDialog(null);
    setDeleteError(null);
  };

  if (loadError) return <p className="form-error">{loadError}</p>;
  if (!detail) return <p className="muted">Loading…</p>;
  const { instrument, transactions, summary } = detail;

  return (
    <>
      <p className="crumbs">
        <Link to={`/asset/${instrument.asset_class}`}>{CLASS_NAMES[instrument.asset_class]}</Link> / {instrument.name}
      </p>
      <div className="page-head">
        <h1>
          {instrument.name}
          {instrument.symbol && <span className="symbol">{instrument.symbol}</span>}
          <PriceBadge row={summary} />
        </h1>
        <div className="actions">
          <button className="button ghost" onClick={() => setDialog({ kind: "edit-instrument" })}>Edit instrument</button>
          <button
            className="button danger-ghost"
            disabled={transactions.length > 0}
            title={transactions.length ? "Delete its transactions first" : undefined}
            onClick={() => setDialog({ kind: "delete-instrument" })}
          >
            Delete instrument
          </button>
        </div>
      </div>

      <section className="stats">
        <Stat label="Quantity">{qty(summary.qty)}</Stat>
        <Stat label="Avg cost">{summary.avg_cost === null ? "—" : inr(summary.avg_cost)}</Stat>
        <Stat label="Price"><PriceCell row={summary} /></Stat>
        <Stat label="Value">{inr(summary.value)}</Stat>
        <Stat label="Unrealised P&L" sub={<Percent value={summary.unrealised_pnl_pct} />}>
          <span className={signed(summary.unrealised_pnl)} data-testid="instrument-unrealised">{inr(summary.unrealised_pnl)}</span>
        </Stat>
        <Stat label="Realised P&L">
          <span className={signed(summary.realised_pnl)} data-testid="instrument-realised">{inr(summary.realised_pnl)}</span>
        </Stat>
        <Stat label="Total P&L">
          <span className={signed(summary.pnl)} data-testid="instrument-pnl">{inr(summary.pnl)}</span>
        </Stat>
        <Stat label="XIRR"><span data-testid="instrument-xirr"><Xirr value={summary.xirr} /></span></Stat>
      </section>

      <section className="card">
        <div className="chart-head">
          <h2>Transactions</h2>
          <button className="button primary" onClick={() => setDialog({ kind: "add-transaction" })}>Add transaction</button>
        </div>
        {transactions.length === 0 ? <p className="muted">No transactions yet.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th><th>Type</th><th className="num">Qty</th><th className="num">Price</th>
                  <th className="num">Amount</th><th>Note</th><th>Kind</th><th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {transactions.map((txn) => (
                  <tr key={txn.id}>
                    <td>{dateLabel(txn.date)}</td>
                    <td><span className={`badge ${txn.type.toLowerCase()}`}>{txn.type}</span></td>
                    <td className="num">{qty(txn.quantity)}</td>
                    <td className="num">
                      {inr(txn.price_inr)}
                      {txn.currency === "USD" && txn.price_usd !== null && txn.fx_rate_used !== null && (
                        <div className="subline">{usd(txn.price_usd)} @ {txn.fx_rate_used.toFixed(2)}</div>
                      )}
                    </td>
                    <td className="num">{inr(txn.quantity * txn.price_inr)}</td>
                    <td className="note">{txn.note}</td>
                    <td><span className={`badge ${txn.kind === "trade" ? "trade" : "action"}`}>{txn.kind.replace("_", " ")}</span></td>
                    <td className="row-actions">
                      <button className="link" onClick={() => setDialog({ kind: "edit-transaction", transaction: txn })}>Edit</button>
                      <button className="link danger-text" onClick={() => setDialog({ kind: "delete-transaction", transaction: txn })}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {dialog?.kind === "edit-instrument" && (
        <InstrumentForm assetClass={instrument.asset_class} instrument={instrument} onClose={close} onSaved={saved} />
      )}
      {dialog?.kind === "add-transaction" && (
        <TransactionForm instrument={instrument} onClose={close} onSaved={saved} />
      )}
      {dialog?.kind === "edit-transaction" && (
        <TransactionForm instrument={instrument} transaction={dialog.transaction} onClose={close} onSaved={saved} />
      )}
      {dialog?.kind === "delete-transaction" && (
        <ConfirmDialog
          title="Delete transaction?"
          message={`${dialog.transaction.type} ${qty(dialog.transaction.quantity)} on ${dateLabel(dialog.transaction.date)}. A backup is saved first, but this can't be undone here.`}
          error={deleteError} busy={deleting} onCancel={close}
          onConfirm={() => void confirmDelete(() => api.deleteTransaction(dialog.transaction.id), () => {
            void load();
            void reload();
          })}
        />
      )}
      {dialog?.kind === "delete-instrument" && (
        <ConfirmDialog
          title={`Delete ${instrument.name}?`}
          message="This removes the instrument. It has no transactions."
          error={deleteError} busy={deleting} onCancel={close}
          onConfirm={() => void confirmDelete(() => api.deleteInstrument(instrument.id), () => {
            void reload();
            navigate(`/asset/${instrument.asset_class}`);
          })}
        />
      )}
    </>
  );
}
