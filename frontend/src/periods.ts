/** Time frames for period returns. No React here, so it can be tested with `node --test`. */

export const PRESETS = ["1M", "3M", "6M", "1Y", "YTD", "All", "Custom"] as const;
export type Preset = (typeof PRESETS)[number];

export interface PeriodChoice {
  preset: Preset;
  /** Custom range only (YYYY-MM-DD). An end of today, or none, means "up to now". */
  start?: string;
  end?: string;
}

export const ALL_PERIOD: PeriodChoice = { preset: "All" };

const pad = (value: number) => String(value).padStart(2, "0");
const iso = (year: number, month: number, day: number) => `${year}-${pad(month)}-${pad(day)}`;

/** The same day `months` earlier, or the month's last day when it has fewer days. */
export function monthsBefore(today: string, months: number): string {
  const [year, month, day] = today.split("-").map(Number);
  const index = year * 12 + (month - 1) - months;
  const y = Math.floor(index / 12);
  const m = (index % 12) + 1;
  const lastDay = new Date(y, m, 0).getDate();
  return iso(y, m, Math.min(day, lastDay));
}

/** Start and end dates for a choice; end null means today. null for "All" or an unfinished custom range. */
export function periodDates(choice: PeriodChoice, today: string = localToday()): { start: string; end: string | null } | null {
  switch (choice.preset) {
    case "All":
      return null;
    case "1M":
      return { start: monthsBefore(today, 1), end: null };
    case "3M":
      return { start: monthsBefore(today, 3), end: null };
    case "6M":
      return { start: monthsBefore(today, 6), end: null };
    case "1Y":
      return { start: monthsBefore(today, 12), end: null };
    case "YTD":
      return { start: `${Number(today.slice(0, 4)) - 1}-12-31`, end: null };
    case "Custom": {
      if (customError(choice.start, choice.end, today) !== null) return null;
      return { start: choice.start!, end: !choice.end || choice.end >= today ? null : choice.end };
    }
  }
}

/** Why a custom range can't be used, or null when it can. */
export function customError(start: string | undefined, end: string | undefined, today: string = localToday()): string | null {
  if (!start) return "Pick a start date.";
  const last = end || today;
  if (last > today) return "The end date can't be after today.";
  if (start >= last) return "The start date must be before the end date.";
  return null;
}

export function localToday(): string {
  const now = new Date();
  return iso(now.getFullYear(), now.getMonth() + 1, now.getDate());
}
