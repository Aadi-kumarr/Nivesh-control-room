import { useMemo, useState } from "react";
import {
  CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { CLASS_NAMES, CLASS_ORDER, dateLabel, inr, inrShort, monthLabel, percent } from "../format";
import type { HistoryPoint, HistoryValues, Portfolio } from "../types";

// Validated against the dark surface; each entity keeps its colour on every chart.
const CLASS_COLORS: Record<string, string> = {
  "indian-equities": "#3987e5",
  "us-equities": "#d95926",
  crypto: "#199e70",
  fno: "#c98500",
  cash: "#d55181",
};
const VALUE_COLOR = "#3987e5";
const INVESTED_COLOR = "#d95926";
const AXIS = { fill: "#93a0ae", fontSize: 12 };

export function AllocationDonut({ portfolio }: { portfolio: Portfolio }) {
  const total = portfolio.portfolio.value;
  const slices = [
    ...CLASS_ORDER.map((id) => ({
      id, name: CLASS_NAMES[id], value: portfolio.asset_classes[id]?.value ?? 0,
    })),
    { id: "cash", name: "Cash", value: portfolio.portfolio.cash_inr },
  ].filter((slice) => slice.value > 0);

  return (
    <div className="donut">
      <div className="donut-chart">
        <ResponsiveContainer width="100%" height={230}>
          <PieChart>
            <Pie
              data={slices} dataKey="value" nameKey="name" innerRadius="66%" outerRadius="96%"
              stroke="#141a21" strokeWidth={2} startAngle={90} endAngle={-270} isAnimationActive={false}
            >
              {slices.map((slice) => <Cell key={slice.id} fill={CLASS_COLORS[slice.id]} />)}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                const item = payload?.[0];
                if (!active || !item) return null;
                const value = Number(item.value);
                return (
                  <div className="tooltip">
                    <strong>{item.name}</strong>
                    <div>{inr(value)} · {percent(value / total)}</div>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="legend">
        {slices.map((slice) => (
          <li key={slice.id}>
            <span className="swatch" style={{ background: CLASS_COLORS[slice.id] }} />
            <span>{slice.name}</span>
            <span className="legend-value">{percent(slice.value / total)}</span>
          </li>
        ))}
      </ul>
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
