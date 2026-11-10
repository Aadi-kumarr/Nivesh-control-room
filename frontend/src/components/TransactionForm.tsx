import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { inr, todayIso } from "../format";
import type { Fx, Instrument, Transaction } from "../types";
import { Modal } from "./common";
import { ProfileLine } from "./ProfileMenu";

type FxState = { state: "idle" | "loading" | "failed" } | { state: "ok"; fx: Fx };

/** Adds a transaction, or edits one when `transaction` is given. */
export function TransactionForm({ instrument, transaction, onClose, onSaved }: {
  instrument: Pick<Instrument, "id" | "name" | "asset_class">;
  transaction?: Transaction;
  onClose: () => void;
  onSaved: (warnings: string[]) => void;
}) {
  // Old US trades stay in INR, so an edit follows the transaction, not the asset class.
  const isUsd = transaction ? transaction.currency === "USD" : instrument.asset_class === "us-equities";
  const savedOverride = transaction?.fx_override ? String(transaction.fx_rate_used) : "";
  const savedPrice = transaction ? (isUsd ? transaction.price_usd : transaction.price_inr) : null;

  const [date, setDate] = useState(transaction?.date ?? todayIso());
  const [type, setType] = useState<"BUY" | "SELL">(transaction?.type ?? "BUY");
  const [quantity, setQuantity] = useState(transaction ? String(transaction.quantity) : "");
  const [price, setPrice] = useState(savedPrice === null ? "" : String(savedPrice));
  const [note, setNote] = useState(transaction?.note ?? "");
  const [override, setOverride] = useState(savedOverride);
  const [fx, setFx] = useState<FxState>({ state: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // The server only changes a saved trade's rate when its date changes.
  const needsFx = isUsd && Boolean(date) && (!transaction || date !== transaction.date);

  useEffect(() => {
    if (!needsFx) {
      setFx({ state: "idle" });
      return;
    }
    setFx({ state: "loading" });
    let current = true;
    api.fx(date)
      .then((result) => current && setFx({ state: "ok", fx: result }))
      .catch(() => current && setFx({ state: "failed" }));
    return () => {
      current = false;
    };
  }, [date, needsFx]);

  const overrideRate = override === "" ? null : Number(override);
  const rate = overrideRate
    ?? (fx.state === "ok" ? fx.fx.usdinr_used : null)
    ?? (needsFx ? null : transaction?.fx_rate_used ?? null);
  const amount = Number(quantity) * Number(price) * (isUsd ? rate ?? 0 : 1);
  const needsOverride = needsFx && fx.state === "failed" && overrideRate === null;
  const fxPending = needsFx && fx.state === "loading" && overrideRate === null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const priceField = isUsd ? "price_usd" : "price_inr";
    try {
      if (transaction) {
        const changes: Record<string, unknown> = {};
        if (date !== transaction.date) changes.date = date;
        if (type !== transaction.type) changes.type = type;
        if (Number(quantity) !== transaction.quantity) changes.quantity = Number(quantity);
        if (Number(price) !== savedPrice) changes[priceField] = Number(price);
        if (note !== transaction.note) changes.note = note;
        if (isUsd && override !== savedOverride) changes.fx_rate_used = overrideRate;
        if (Object.keys(changes).length === 0) {
          onClose();
          return;
        }
        onSaved((await api.updateTransaction(transaction.id, changes)).warnings);
      } else {
        const result = await api.createTransaction({
          instrument_id: instrument.id,
          date, type, note,
          quantity: Number(quantity),
          [priceField]: Number(price),
          ...(isUsd && overrideRate !== null ? { fx_rate_used: overrideRate } : {}),
        });
        onSaved(result.warnings);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save.");
      setSaving(false);
    }
  }

  return (
    <Modal title={`${transaction ? "Edit" : "Add"} transaction: ${instrument.name}`} onClose={onClose}>
      <ProfileLine label={transaction ? "Editing in" : "Adding to"} />
      <form onSubmit={(event) => void submit(event)}>
        <div className="form-row">
          <label>Date
            <input type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} required />
          </label>
          <label>Type
            <select value={type} onChange={(e) => setType(e.target.value as "BUY" | "SELL")}>
              <option>BUY</option>
              <option>SELL</option>
            </select>
          </label>
        </div>
        <div className="form-row">
          <label>Quantity
            <input type="number" min="0" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
          </label>
          <label>Price ({isUsd ? "$" : "₹"})
            <input type="number" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)} required />
          </label>
        </div>

        {isUsd && (
          <>
            {fx.state === "loading" && <p className="hint">Fetching USDINR…</p>}
            {fx.state === "ok" && (
              <p className="hint" data-testid="fx-line">
                Market {fx.fx.usdinr_market.toFixed(2)} → used {fx.fx.usdinr_used.toFixed(2)} (your
                ₹{(fx.fx.usdinr_market - fx.fx.usdinr_used).toFixed(2).replace(/\.00$/, "")} rule)
                {fx.fx.rate_date !== fx.fx.date && ` · rate from ${fx.fx.rate_date}`}
              </p>
            )}
            {fx.state === "failed" && (
              <p className="form-error" role="alert">
                Could not fetch USDINR for this date. Enter an override rate to save.
              </p>
            )}
            {!needsFx && transaction && transaction.fx_rate_used !== null && overrideRate === null && (
              <p className="hint" data-testid="fx-line">Saved rate {transaction.fx_rate_used.toFixed(2)} stays unless the date changes</p>
            )}
            {transaction?.fx_override && date !== transaction.date && override === savedOverride && (
              <p className="hint">Your manual rate stays for the new date. Clear it to use Yahoo's rate.</p>
            )}
            <label>Override rate (optional)
              <input type="number" min="0" step="any" value={override} onChange={(e) => setOverride(e.target.value)}
                placeholder="Your broker's rate" required={needsOverride} />
            </label>
          </>
        )}

        {amount > 0 && <p className="hint amount" data-testid="amount">Amount: <b>{inr(amount)}</b></p>}

        <label>Note
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </label>

        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving || needsOverride || fxPending}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
