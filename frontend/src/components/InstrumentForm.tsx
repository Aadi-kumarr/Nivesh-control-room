import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { inr, normalizeSymbol, usd } from "../format";
import type { Instrument, SymbolCheck } from "../types";
import { Modal } from "./common";

type Check = { state: "idle" | "checking" } | { state: "ok"; result: SymbolCheck } | { state: "error"; message: string };

/** Adds an instrument, or edits one when `instrument` is given. */
export function InstrumentForm({ assetClass, instrument, onClose, onSaved }: {
  assetClass: string;
  instrument?: Instrument;
  onClose: () => void;
  onSaved: (warnings: string[], id?: string) => void;
}) {
  const [name, setName] = useState(instrument?.name ?? "");
  const [symbol, setSymbol] = useState(instrument?.symbol ?? "");
  const [source, setSource] = useState<"yahoo" | "manual">(instrument?.price_source ?? "yahoo");
  const [manual, setManual] = useState(instrument ? String(instrument.manual_price_inr) : "");
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const typed = symbol.trim() || (instrument ? "" : name.trim());
  const normalized = normalizeSymbol(assetClass, typed);
  const yahooUnchanged = instrument?.price_source === "yahoo" && source === "yahoo"
    && normalized === instrument.symbol;
  const needsCheck = source === "yahoo" && Boolean(normalized) && !yahooUnchanged;

  useEffect(() => {
    if (!needsCheck) {
      setCheck({ state: "idle" });
      return;
    }
    setCheck({ state: "checking" });
    let current = true;
    const timer = setTimeout(() => {
      api.checkSymbol(assetClass, normalized)
        .then((result) => current && setCheck({ state: "ok", result }))
        .catch((failure: Error) => current && setCheck({ state: "error", message: failure.message }));
    }, 500);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [assetClass, normalized, needsCheck]);

  const blocked = source === "yahoo" && (!normalized || (needsCheck && check.state !== "ok"));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const price = manual === "" ? undefined : Number(manual);
      if (instrument) {
        const changes: Partial<Instrument> = {};
        const nextSymbol = normalized || null;
        if (nextSymbol !== instrument.symbol) changes.symbol = nextSymbol;
        if (source !== instrument.price_source) changes.price_source = source;
        if (price !== undefined && price !== instrument.manual_price_inr) changes.manual_price_inr = price;
        if (Object.keys(changes).length === 0) {
          onClose();
          return;
        }
        onSaved((await api.updateInstrument(instrument.id, changes)).warnings);
      } else {
        const result = await api.createInstrument({
          asset_class: assetClass,
          name: name.trim(),
          symbol: symbol.trim() || undefined,
          price_source: source,
          manual_price_inr: price,
        });
        onSaved(result.warnings, result.instrument.id);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save.");
      setSaving(false);
    }
  }

  return (
    <Modal title={instrument ? `Edit ${instrument.name}` : "Add instrument"} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)}>
        {!instrument && (
          <label>Name
            <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </label>
        )}
        <label>Symbol
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
            placeholder={instrument ? "" : "Leave blank to use the name"} />
        </label>
        {normalized && (
          <p className="hint" data-testid="symbol-helper">Saved as <b>{normalized}</b></p>
        )}
        <label>Price source
          <select value={source} onChange={(e) => setSource(e.target.value as "yahoo" | "manual")}>
            <option value="yahoo">Yahoo (live)</option>
            <option value="manual">Manual</option>
          </select>
        </label>
        {check.state === "checking" && <p className="hint">Checking Yahoo…</p>}
        {check.state === "ok" && (
          <p className="hint ok" data-testid="symbol-price">
            Yahoo price: {check.result.currency === "USD" ? usd(check.result.price) : inr(check.result.price)}
          </p>
        )}
        {check.state === "error" && <p className="form-error" role="alert">{check.message}</p>}
        <label>Manual price (₹)
          <input type="number" min="0" step="any" value={manual} onChange={(e) => setManual(e.target.value)}
            placeholder={source === "yahoo" ? "Optional fallback" : ""} />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving || blocked}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
