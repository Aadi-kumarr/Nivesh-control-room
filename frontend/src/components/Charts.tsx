import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { DRILLABLE, classSlices, holdingSlices } from "../allocation";
import type { Slice } from "../allocation";
import { CLASS_NAMES, CLASS_ORDER, dateLabel, inr, inrShort, monthLabel, percent } from "../format";
import type { HistoryPoint, HistoryValues, Portfolio } from "../types";

const VALUE_COLOR = "#3987e5";
const INVESTED_COLOR = "#d95926";
const AXIS = { fill: "#93a0ae", fontSize: 12 };

/** Asset classes; click one (or its legend name) to see its holdings. Back, "All" or Esc return. */
export function AllocationDonut({ portfolio }: { portfolio: Portfolio }) {
  const [drill, setDrill] = useState<string | null>(null);
  const root = classSlices(portfolio);
  // A class drilled into can disappear (sold out, or another profile): show the top level then.
  const classId = drill && root.some((slice) => slice.id === drill) ? drill : null;
  const drilled = classId ? holdingSlices(portfolio, classId) : null;
  const slices = drilled ? drilled.slices : root;
  const base = drilled ? drilled.total : portfolio.portfolio.value;
  const canDrill = (id: string) => !drilled && DRILLABLE.has(id);
  const back = () => setDrill(null);

  useEffect(() => {
    if (!classId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrill(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [classId]);

  return (
    <div className="donut-wrap">
      <div className="donut-nav">
        {classId ? (
          <>
            <button type="button" className="button ghost small" onClick={back}>‹ Back</button>
            <nav className="breadcrumb" aria-label="Allocation level">
              <button type="button" className="link" onClick={back}>All</button>
              <span aria-hidden="true"> › </span>
              <span aria-current="page">{CLASS_NAMES[classId]}</span>
            </nav>
          </>
        ) : <p className="muted small-text">Click an asset class to see its holdings.</p>}
      </div>
      {/* Keyed by level, so each level fades in (.donut-level; off under reduced motion). */}
      <div className="donut donut-level" key={classId ?? "all"} data-testid="allocation-donut" data-level={classId ?? "all"}>
        <div className="donut-chart">
          <ResponsiveContainer width="100%" height={230}>
            <PieChart>
              <Pie
                data={slices} dataKey="value" nameKey="name" innerRadius="66%" outerRadius="96%"
                stroke="#141a21" strokeWidth={2} startAngle={90} endAngle={-270} isAnimationActive={false}
                onClick={(_, index) => {
                  const slice = slices[index];
                  if (slice && canDrill(slice.id)) setDrill(slice.id);
                }}
              >
                {slices.map((slice) => (
                  <Cell
                    key={slice.id} fill={slice.color} data-slice={slice.id}
                    style={{ cursor: canDrill(slice.id) ? "pointer" : "default", outline: "none" }}
                  />
                ))}
              </Pie>
              <Tooltip
                content={({ active, payload }) => {
                  const slice = payload?.[0]?.payload as Slice | undefined;
                  if (!active || !slice) return null;
                  return (
                    <div className="tooltip">
                      <strong>{slice.name}</strong>
                      <div>{inr(slice.value)} · {percent(slice.value / base)}{classId ? ` of ${CLASS_NAMES[classId]}` : ""}</div>
                      {slice.members && (
                        <div className="muted">{slice.members.slice(0, 6).join(", ")}{slice.members.length > 6 ? "…" : ""}</div>
                      )}
                      {canDrill(slice.id) && <div className="muted">Click to see holdings</div>}
                    </div>
                  );
                }}
              />
            </PieChart>
          </ResponsiveContainer>
          {drilled && classId && (
            <button type="button" className="donut-center" onClick={back} title="Back to all asset classes">
              <span>{CLASS_NAMES[classId]}</span>
              <strong>{inrShort(drilled.total)}</strong>
            </button>
          )}
        </div>
        <ul className={`legend ${drilled ? "holdings" : ""}`}>
          {(drilled ? drilled.legend : root).map((slice) => (
            <li key={slice.id}>
              <span className="swatch" style={{ background: slice.color }} />
              {canDrill(slice.id)
                ? <button type="button" className="link legend-name" onClick={() => setDrill(slice.id)}>{slice.name}</button>
                : <span className="legend-name">{slice.name}</span>}
              {drilled && <span className="legend-amount">{inr(slice.value)}</span>}
              <span className="legend-value">{percent(slice.value / base)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

interface ChartRow extends HistoryValues {
  date: string;
}

function EstimatedDot(props: { cx?: number; cy?: number; payload?: ChartRow }) {
  const { cx, cy, payload } = props;
  if (!payload?.estimated || cx === undefined || cy === undefined) return <g />;
  return <circle cx={cx} cy={cy} r={4} fill="#141a21" stroke={VALUE_COLOR} strokeWidth={2} />;
}

function EndLabel({ rows, text }: { rows: ChartRow[]; text: string }) {
  function Label(props: { x?: number | string; y?: number | string; index?: number }) {
    if (props.index !== rows.length - 1) return <g />;
    return <text x={Number(props.x) + 8} y={Number(props.y) + 4} fill="#c7d0d9" fontSize={12}>{text}</text>;
  }
  return Label;
}

export function GrowthChart({ points }: { points: HistoryPoint[] }) {
  const [view, setView] = useState("all");
  const views = ["all", ...CLASS_ORDER.filter((id) => points.at(-1)?.asset_classes[id])];

  const rows: ChartRow[] = useMemo(
    () => points.map((point) => {
      const values = view === "all" ? point : point.asset_classes[view];
      return {
        date: point.date,
        value: values?.value ?? 0,
        net_invested: values?.net_invested ?? 0,
        estimated_value: values?.estimated_value ?? 0,
        estimated: values?.estimated ?? false,
      };
    }),
    [points, view],
  );

  return (
    <>
      <div className="chart-head">
        <div>
          <h2>Portfolio growth</h2>
          <p className="muted small-text">Total value over time</p>
        </div>
        <div className="segmented" role="group" aria-label="Asset class">
          {views.map((id) => (
            <button key={id} className={view === id ? "active" : ""} aria-pressed={view === id} onClick={() => setView(id)}>
              {id === "all" ? "All" : CLASS_NAMES[id]}
            </button>
          ))}
        </div>
      </div>

      <ul className="legend inline">
        <li><span className="swatch line" style={{ background: VALUE_COLOR }} />Value</li>
        <li><span className="swatch line dashed" style={{ color: INVESTED_COLOR }} />Net invested</li>
        <li><span className="swatch ring" />Estimated (partly priced from trades)</li>
      </ul>

      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={rows} margin={{ top: 12, right: 96, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="#27303a" vertical={false} />
          <XAxis dataKey="date" tickFormatter={monthLabel} tick={AXIS} stroke="#27303a" minTickGap={40} tickLine={false} />
          <YAxis tickFormatter={inrShort} tick={AXIS} stroke="none" width={64} tickLine={false} />
          <Tooltip
            cursor={{ stroke: "#55626f" }}
            content={({ active, payload }) => {
              const row = payload?.[0]?.payload as ChartRow | undefined;
              if (!active || !row) return null;
              return (
                <div className="tooltip">
                  <strong>{dateLabel(row.date)}</strong>
                  <div>Value <b>{inr(row.value)}</b></div>
                  <div>Net invested <b>{inr(row.net_invested)}</b></div>
                  {row.estimated && <div className="muted">Estimated part: {inr(row.estimated_value)}</div>}
                </div>
              );
            }}
          />
          <Line
            type="linear" dataKey="net_invested" stroke={INVESTED_COLOR} strokeWidth={2} strokeDasharray="6 4"
            dot={false} isAnimationActive={false} label={EndLabel({ rows, text: "Net invested" })}
          />
          <Line
            type="linear" dataKey="value" stroke={VALUE_COLOR} strokeWidth={2} dot={EstimatedDot}
            activeDot={{ r: 5 }} isAnimationActive={false} label={EndLabel({ rows, text: "Value" })}
          />
        </LineChart>
      </ResponsiveContainer>

      <details className="data-table">
        <summary>Show data table</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Date</th><th className="num">Value</th><th className="num">Net invested</th><th>Estimated</th></tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((row) => (
                <tr key={row.date}>
                  <td>{dateLabel(row.date)}</td>
                  <td className="num">{inr(row.value)}</td>
                  <td className="num">{inr(row.net_invested)}</td>
                  <td>{row.estimated ? inr(row.estimated_value) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
