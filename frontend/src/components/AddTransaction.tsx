import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CLASS_NAMES, CLASS_ORDER } from "../format";
import type { InstrumentListItem } from "../types";
import { InstrumentForm } from "./InstrumentForm";
import { ProfileLine } from "./ProfileMenu";
import { TransactionForm } from "./TransactionForm";
import { Modal } from "./common";

type Step = { kind: "pick" } | { kind: "new" } | { kind: "trade"; instrument: InstrumentListItem };

/** Pick any instrument (they are shared by all profiles), or create one, then add a trade. */
export function AddTransaction({ assetClass, onClose, onSaved }: {
  assetClass?: string;
  onClose: () => void;
  onSaved: (warnings: string[]) => void;
}) {
  const [instruments, setInstruments] = useState<InstrumentListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cls, setCls] = useState(assetClass ?? CLASS_ORDER[0]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("");
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const [notes, setNotes] = useState<string[]>([]);

  const load = () => api.instruments()
    .then((result) => {
      setInstruments(result.instruments);
      return result.instruments;
    })
    .catch((failure: Error) => {
      setError(failure.message);
      return [] as InstrumentListItem[];
    });

  useEffect(() => {
    void load();
  }, []);

  const query = search.trim().toLowerCase();
  const options = useMemo(
    () => (instruments ?? []).filter((i) => i.asset_class === cls
      && (!query || `${i.name} ${i.symbol ?? ""}`.toLowerCase().includes(query))),
    [instruments, cls, query],
  );
  const chosen = options.find((i) => i.id === selected);

  if (step.kind === "new") {
    return (
      <InstrumentForm
        assetClass={cls}
        onClose={() => setStep({ kind: "pick" })}
        onSaved={(warnings, newId) => {
          setNotes(warnings);
          void load().then((list) => {
            const created = list.find((i) => i.id === newId);
            setStep(created ? { kind: "trade", instrument: created } : { kind: "pick" });
          });
        }}
      />
    );
  }
  if (step.kind === "trade") {
    return (
      <TransactionForm
        instrument={step.instrument}
        onClose={onClose}
        onSaved={(warnings) => onSaved([...notes, ...warnings])}
      />
    );
  }

  return (
    <Modal title="Add transaction" onClose={onClose}>
      <ProfileLine />
      {!assetClass && (
        <label>Asset class
          <select value={cls} onChange={(e) => { setCls(e.target.value); setSelected(""); }}>
            {CLASS_ORDER.map((id) => <option key={id} value={id}>{CLASS_NAMES[id]}</option>)}
          </select>
        </label>
      )}
      <label>Instrument
        <input type="search" placeholder="Search name or symbol" value={search}
          onChange={(e) => setSearch(e.target.value)} autoFocus />
      </label>
      {error && <p className="form-error" role="alert">{error}</p>}
      {!instruments && !error && <p className="muted">Loading instruments…</p>}
      {instruments && (
        options.length ? (
          <select className="picker" size={Math.min(8, Math.max(options.length, 2))} value={selected}
            aria-label="Instruments" onChange={(e) => setSelected(e.target.value)}
            onDoubleClick={() => chosen && setStep({ kind: "trade", instrument: chosen })}>
            {options.map((i) => (
              <option key={i.id} value={i.id}>{i.name}{i.symbol && i.symbol !== i.name ? ` (${i.symbol})` : ""}</option>
            ))}
          </select>
        ) : <p className="muted">{query ? `No instrument matches "${search.trim()}".` : "No instruments in this class yet."}</p>
      )}
      <div className="modal-actions spread">
        <button type="button" className="button ghost" onClick={() => setStep({ kind: "new" })}>New instrument…</button>
        <span className="actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="button primary" disabled={!chosen}
            onClick={() => chosen && setStep({ kind: "trade", instrument: chosen })}>
            Next
          </button>
        </span>
      </div>
    </Modal>
  );
}
