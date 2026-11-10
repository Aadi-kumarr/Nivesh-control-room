import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useData } from "../DataContext";
import { dateLabel, percent, signed } from "../format";
import { PRESETS, customError, localToday } from "../periods";
import type { Preset } from "../periods";
import type { PeriodResult, PeriodReturn } from "../types";
import { Money, Xirr } from "./common";

const ABSOLUTE_TIP = "Absolute return: what the money at work gained over this period, not scaled to a year.";
const ANNUALISED_TIP = "Annualised (XIRR): the yearly rate that gives the same result, counting each buy and sell from its date.";

/** Small "i" that explains the two figures, on hover or keyboard focus. */
export function ReturnInfo() {
  return (
    <span className="info" tabIndex={0} role="note" aria-label={`${ABSOLUTE_TIP} ${ANNUALISED_TIP}`}>
      i
      <span className="info-tip" aria-hidden="true">
        <span>{ABSOLUTE_TIP}</span>
        <span>{ANNUALISED_TIP}</span>
      </span>
    </span>
  );
}

/** Time-frame picker; the choice is shared by every page. */
export function PeriodPicker() {
  const { period, setPeriod } = useData();
  const [start, setStart] = useState(period.start ?? "");
  const [end, setEnd] = useState(period.end ?? "");
  const [editing, setEditing] = useState(false);
  const today = localToday();
  const error = customError(start || undefined, end || undefined, today);

  function choose(preset: Preset) {
    if (preset === "Custom") setEditing(true);
    else {
      setEditing(false);
      setPeriod({ preset });
    }
  }

  function apply(event: FormEvent) {
    event.preventDefault();
    if (error) return;
    setPeriod({ preset: "Custom", start, end: end || undefined });
    setEditing(false);
  }

  return (
    <div className="period-picker">
      <div className="period-buttons" role="group" aria-label="Time frame">
        {PRESETS.map((preset) => (
          <button
            key={preset} type="button"
            className={`period-button ${(editing ? preset === "Custom" : period.preset === preset) ? "active" : ""}`}
            aria-pressed={editing ? preset === "Custom" : period.preset === preset}
            onClick={() => choose(preset)}
          >
            {preset}
          </button>
        ))}
      </div>
      {period.preset === "Custom" && !editing && period.start && (
        <div className="period-range muted small-text">
          {dateLabel(period.start)} to {period.end ? dateLabel(period.end) : "today"}
        </div>
      )}
      {editing && (
        <form className="period-custom" onSubmit={apply}>
          <label>From <input type="date" value={start} max={today} onChange={(e) => setStart(e.target.value)} required /></label>
          <label>To <input type="date" value={end} max={today} onChange={(e) => setEnd(e.target.value)} placeholder="today" /></label>
          <button type="submit" className="button primary small" disabled={Boolean(error)}>Apply</button>
          <button type="button" className="button ghost small" onClick={() => setEditing(false)}>Cancel</button>
          {start && error && <p className="form-error small-text">{error}</p>}
        </form>
      )}
    </div>
  );
}

function namesText(names: string[]): string {
  return names.length <= 3 ? names.join(", ") : `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
}

/** Notes under a period figure: started later than the period, values estimated. */
function Notes({ result }: { result: PeriodResult }) {
  return (
    <>
      {result.started_from && <div className="period-note">from {dateLabel(result.started_from)}</div>}
      {result.estimated.length > 0 && (
        <div className="period-note estimated" title={`Estimated (last trade price): ${result.estimated.join(", ")}`}>
          estimated: {namesText(result.estimated)}
        </div>
      )}
    </>
  );
}

/** Under a year the absolute return leads (annualising a few weeks exaggerates); from a year, XIRR. */
function figures(result: PeriodResult, days: number) {
  const absolute = <span className={signed(result.return_pct)}>{percent(result.return_pct)}</span>;
  const annualised = <Xirr value={result.xirr} />;
  return days < 365
    ? { main: absolute, mainTag: "absolute", second: annualised, secondTag: "annualised (XIRR)" }
    : { main: annualised, mainTag: "annualised (XIRR)", second: absolute, secondTag: "absolute" };
}

/** Big figure for a stat card. */
function PeriodFigure({ result, days, testId }: { result: PeriodResult; days: number; testId?: string }) {
  const f = figures(result, days);
  return (
    <div className="period-figure">
      <div data-testid={testId}>{f.main} <span className="period-tag">{f.mainTag}</span></div>
      <div className="period-sub">
        <span>{f.second} <span className="period-tag">{f.secondTag}</span></span>
        <span>Gain <Money value={result.gain_inr} /></span>
      </div>
      <Notes result={result} />
    </div>
  );
}

/** Compact figure for a table cell. */
export function PeriodCell({ result, days }: { result: PeriodResult | undefined; days: number }) {
  if (!result) return <span className="muted" title="No holdings or trades in this time frame">—</span>;
  const f = figures(result, days);
  return (
    <>
      {f.main}
      <div className="subline"><Money value={result.gain_inr} /></div>
      {(result.started_from || result.estimated.length > 0) && (
        <div className="subline period-flag" title={[
          result.started_from ? `From ${dateLabel(result.started_from)}` : "",
          result.estimated.length ? `Estimated: ${result.estimated.join(", ")}` : "",
        ].filter(Boolean).join(". ")}
        >
          {result.started_from ? `from ${dateLabel(result.started_from)}` : "estimated"}
        </div>
      )}
    </>
  );
}

/**
 * The XIRR card with a time frame. "All" shows the existing all-time XIRR as it always was;
 * another time frame shows that period's returns, picked from the shared result.
 */
export function ReturnStat({ label, xirr, pick, sub, testId }: {
  label: string;
  xirr: number | null;
  pick: (period: PeriodReturn) => PeriodResult | undefined;
  sub?: ReactNode;
  testId?: string;
}) {
  const { period, periodResult, periodLoading, periodError } = useData();
  let body: ReactNode;
  if (period.preset === "All") {
    body = (
      <>
        <div className="stat-value"><span data-testid={testId}><Xirr value={xirr} /></span></div>
        {sub && <div className="stat-sub">{sub}</div>}
      </>
    );
  } else if (periodError) {
    body = <p className="form-error small-text">{periodError}</p>;
  } else if (!periodResult) {
    body = <div className="stat-value muted">{periodLoading ? "…" : "—"}</div>;
  } else {
    const result = pick(periodResult);
    body = result
      ? <PeriodFigure result={result} days={periodResult.days} testId={testId} />
      : <div className="stat-value muted" title="No holdings or trades in this time frame">—</div>;
  }
  return (
    <div className="card stat return-stat">
      <div className="label">{label} <ReturnInfo /></div>
      <PeriodPicker />
      {body}
      {period.preset !== "All" && periodResult && (
        <div className="period-range muted small-text">
          {dateLabel(periodResult.start)} to {dateLabel(periodResult.end)}{periodLoading ? " · updating…" : ""}
        </div>
      )}
    </div>
  );
}

/** Table cell for a period figure, or the existing XIRR under "All". */
export function ReturnCell({ xirr, pick }: { xirr: number | null; pick: (period: PeriodReturn) => PeriodResult | undefined }) {
  const { period, periodResult, periodLoading } = useData();
  if (period.preset === "All") return <Xirr value={xirr} />;
  if (!periodResult) return <span className="muted">{periodLoading ? "…" : "—"}</span>;
  return <PeriodCell result={pick(periodResult)} days={periodResult.days} />;
}

/** Column heading that follows the time frame. */
export function useReturnHeading(): string {
  const { period } = useData();
  return period.preset === "All" ? "XIRR" : `Return (${period.preset})`;
}
