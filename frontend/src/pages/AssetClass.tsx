import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { InstrumentForm } from "../components/InstrumentForm";
import { TransactionForm } from "../components/TransactionForm";
import { Money, Percent, PriceBadge, SortableTable, Stat, Xirr } from "../components/common";
import type { Column } from "../components/common";
import { useData } from "../DataContext";
import { CLASS_NAMES, inr, qty, signed, usd } from "../format";
import type { InstrumentRow } from "../types";

export function PriceCell({ row }: { row: InstrumentRow }) {
  return (
    <>
      {inr(row.valuation_price_inr)}
      {row.last_price_currency === "USD" && row.last_price !== null && row.fx_used !== null && (
        <div className="subline">{usd(row.last_price)} @ {row.fx_used.toFixed(2)}</div>
      )}
    </>
  );
}

const COLUMNS: Column<InstrumentRow>[] = [
  { key: "name", label: "Name", value: (r) => r.name, render: (r) => <Link to={`/instrument/${r.id}`}>{r.name}</Link> },
  { key: "symbol", label: "Symbol", value: (r) => r.symbol, render: (r) => r.symbol ?? "—" },
  { key: "qty", label: "Qty", numeric: true, value: (r) => r.qty, render: (r) => qty(r.qty) },
  { key: "avg", label: "Avg cost", numeric: true, value: (r) => r.avg_cost, render: (r) => (r.avg_cost === null ? "—" : inr(r.avg_cost)) },
  { key: "price", label: "Price", numeric: true, value: (r) => r.valuation_price_inr, render: (r) => <PriceCell row={r} /> },
  { key: "value", label: "Value", numeric: true, value: (r) => r.value, render: (r) => inr(r.value) },
  { key: "unrealised", label: "Unrealised", numeric: true, value: (r) => r.unrealised_pnl, render: (r) => <Money value={r.unrealised_pnl} /> },
  { key: "unrealised_pct", label: "Unrealised %", numeric: true, value: (r) => r.unrealised_pnl_pct, render: (r) => <Percent value={r.unrealised_pnl_pct} /> },
  { key: "realised", label: "Realised", numeric: true, value: (r) => r.realised_pnl, render: (r) => <Money value={r.realised_pnl} /> },
  { key: "pnl", label: "Total P&L", numeric: true, value: (r) => r.pnl, render: (r) => <Money value={r.pnl} /> },
  { key: "xirr", label: "XIRR", numeric: true, value: (r) => r.xirr, render: (r) => <Xirr value={r.xirr} /> },
  { key: "status", label: "Status", value: (r) => r.price_source, render: (r) => <PriceBadge row={r} /> },
];

/** Keyed by class, so the search and toggle start fresh in each category. */
export function AssetClass() {
  const { id = "" } = useParams();
  return <AssetClassPage key={id} id={id} />;
}

function AssetClassPage({ id }: { id: string }) {
  const { portfolio, reload, addNotices } = useData();
  const navigate = useNavigate();
  const [showClosed, setShowClosed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [trading, setTrading] = useState<InstrumentRow | null>(null);

  const all = useMemo(
    () => portfolio?.instruments.filter((row) => row.asset_class === id) ?? [],
    [portfolio, id],
  );
  // A search covers closed positions too, so one can be found to buy back into.
  const query = search.trim().toLowerCase();
  const rows = useMemo(() => {
    if (query) {
      return all.filter((row) => `${row.name} ${row.symbol ?? ""}`.toLowerCase().includes(query));
    }
    return showClosed ? all : all.filter((row) => row.qty !== 0);
  }, [all, showClosed, query]);
  const columns = useMemo<Column<InstrumentRow>[]>(() => [...COLUMNS, {
    key: "action",
    label: "Action",
    value: () => null,
    render: (row) => (
      <button className="link" aria-label={`Add transaction for ${row.name}`} onClick={() => setTrading(row)}>+ Add</button>
    ),
  }], []);

  if (!portfolio) return <p className="muted">Loading…</p>;
  const summary = portfolio.asset_classes[id];
  if (!CLASS_NAMES[id]) return <p className="muted">Unknown asset class.</p>;
  const closedCount = all.length - all.filter((row) => row.qty !== 0).length;

  return (
    <>
      <div className="page-head">
        <h1>{CLASS_NAMES[id]}</h1>
        <button className="button primary" onClick={() => setAdding(true)}>Add instrument</button>
      </div>

      {summary && (
        <section className="stats six">
          <Stat label="Value"><span data-testid="class-value">{inr(summary.value)}</span></Stat>
          <Stat label="Unrealised P&L" sub={<Percent value={summary.unrealised_pnl_pct} />}>
            <span className={signed(summary.unrealised_pnl)} data-testid="class-unrealised">{inr(summary.unrealised_pnl)}</span>
          </Stat>
          <Stat label="Realised P&L">
            <span className={signed(summary.realised_pnl)} data-testid="class-realised">{inr(summary.realised_pnl)}</span>
          </Stat>
          <Stat label="Total P&L">
            <span className={signed(summary.pnl)} data-testid="class-pnl">{inr(summary.pnl)}</span>
          </Stat>
          <Stat label="XIRR"><Xirr value={summary.xirr} /></Stat>
          <Stat label="Open positions">{all.length - closedCount}</Stat>
        </section>
      )}

      <section className="card">
        <div className="chart-head">
          <h2>Instruments</h2>
          <div className="chart-tools">
            <input
              className="search" type="search" aria-label="Search instruments" placeholder="Search name or symbol"
              value={search} onChange={(e) => setSearch(e.target.value)} autoFocus
            />
            <label className="toggle">
              <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
              Show closed positions ({closedCount})
            </label>
          </div>
        </div>
        {rows.length ? (
          <SortableTable columns={columns} rows={rows} rowKey={(row) => row.id} defaultSort="value" />
        ) : <p className="muted">{query ? `No instrument matches "${search.trim()}".` : "No open positions."}</p>}
      </section>

      {trading && (
        <TransactionForm
          instrument={trading}
          onClose={() => setTrading(null)}
          onSaved={(warnings) => {
            addNotices(warnings);
            setTrading(null);
            void reload();
          }}
        />
      )}
      {adding && (
        <InstrumentForm
          assetClass={id}
          onClose={() => setAdding(false)}
          onSaved={(warnings, newId) => {
            addNotices(warnings);
            setAdding(false);
            void reload();
            if (newId) navigate(`/instrument/${newId}`);
          }}
        />
      )}
    </>
  );
}
