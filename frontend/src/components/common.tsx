import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { inr, percent, signed, xirrText } from "../format";
import type { InstrumentRow } from "../types";

export function Modal({ title, onClose, children }: {
  title: string; onClose: () => void; children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({ title, message, onConfirm, onCancel, error, busy }: {
  title: string; message: string; onConfirm: () => void; onCancel: () => void;
  error?: string | null; busy?: boolean;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p className="muted">{message}</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="modal-actions">
        <button className="button ghost" onClick={onCancel}>Cancel</button>
        <button className="button danger" onClick={onConfirm} disabled={busy}>
          {busy ? "Deleting…" : "Delete"}
        </button>
      </div>
    </Modal>
  );
}

export function Money({ value }: { value: number }) {
  return <span className={signed(value)}>{inr(value)}</span>;
}

export function Percent({ value }: { value: number | null | undefined }) {
  return <span className={signed(value)}>{percent(value)}</span>;
}

/** Long values shrink and wrap (see .xirr-long), so a huge XIRR is never cut off. */
export function Xirr({ value }: { value: number | null }) {
  const text = xirrText(value);
  return <span className={`${signed(value)} ${text.length > 12 ? "xirr-long" : ""}`}>{text}</span>;
}

export function PriceBadge({ row }: { row: Pick<InstrumentRow, "price_source"> }) {
  const kind = { yahoo: "live", yahoo_last_known: "stale", manual: "manual" }[row.price_source];
  return <span className={`badge ${kind}`}>{kind}</span>;
}

export function Stat({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="stat-value">{children}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  value: (row: T) => string | number | null;
  render?: (row: T) => ReactNode;
  numeric?: boolean;
}

/** Table with clickable headers. Rows with no value sort last in either direction. */
export function SortableTable<T>({ columns, rows, rowKey, defaultSort }: {
  columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; defaultSort: string;
}) {
  const [sort, setSort] = useState({ key: defaultSort, descending: true });

  const sorted = useMemo(() => {
    const column = columns.find((item) => item.key === sort.key) ?? columns[0];
    return [...rows].sort((a, b) => {
      const left = column.value(a);
      const right = column.value(b);
      if (left === null) return right === null ? 0 : 1;
      if (right === null) return -1;
      const order = typeof left === "number" && typeof right === "number"
        ? left - right
        : String(left).localeCompare(String(right));
      return sort.descending ? -order : order;
    });
  }, [columns, rows, sort]);

  const toggle = (column: Column<T>) =>
    setSort((current) => current.key === column.key
      ? { key: column.key, descending: !current.descending }
      : { key: column.key, descending: Boolean(column.numeric) });

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={column.numeric ? "num" : ""}
                aria-sort={sort.key === column.key ? (sort.descending ? "descending" : "ascending") : "none"}
              >
                <button className="th-button" onClick={() => toggle(column)}>
                  {column.label}
                  {sort.key === column.key && <span aria-hidden="true">{sort.descending ? " ▾" : " ▴"}</span>}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} className={column.numeric ? "num" : ""}>
                  {column.render ? column.render(row) : column.value(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
