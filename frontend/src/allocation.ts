/** Allocation donut slices. No React here, so it can be tested with `node --test`. */
import { CLASS_NAMES, CLASS_ORDER } from "./format.ts";
import type { Portfolio } from "./types";

// Validated against the dark surface; each entity keeps its colour on every chart.
export const CLASS_COLORS: Record<string, string> = {
  "indian-equities": "#3987e5",
  "us-equities": "#d95926",
  crypto: "#199e70",
  fno: "#c98500",
  cash: "#d55181",
};
export const OTHERS_COLOR = "#6b7682";
/** The largest holdings always get their own slice... */
export const KEEP_LARGEST = 7;
/** ...and past those, holdings under this share of the class are grouped as "Others". */
export const OTHERS_BELOW = 0.03;

export interface Slice {
  id: string;
  name: string;
  value: number;
  color: string;
  /** For "Others": the holdings it groups. */
  members?: string[];
}

/** Mix a #rrggbb colour toward white (t > 0) or black (t < 0). */
export function shade(hex: string, t: number): string {
  const target = t > 0 ? 255 : 0;
  const amount = Math.abs(t);
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `#${channels.map((c) => Math.round(c + (target - c) * amount).toString(16).padStart(2, "0")).join("")}`;
}

/** Shades of one colour, darkest first, spread so neighbouring slices stay apart. */
export function shades(hex: string, count: number): string[] {
  if (count <= 1) return [hex];
  return Array.from({ length: count }, (_, i) => shade(hex, -0.3 + (0.75 * i) / (count - 1)));
}

/** Top level: one slice per asset class with value, then cash. */
export function classSlices(portfolio: Portfolio): Slice[] {
  return [
    ...CLASS_ORDER.map((id) => ({
      id, name: CLASS_NAMES[id], value: portfolio.asset_classes[id]?.value ?? 0, color: CLASS_COLORS[id],
    })),
    { id: "cash", name: "Cash", value: portfolio.portfolio.cash_inr, color: CLASS_COLORS.cash },
  ].filter((slice) => slice.value > 0);
}

/** Inside a class: one slice per holding by current value, small ones past the largest few
 * grouped as "Others". The legend still lists every holding. */
export function holdingSlices(portfolio: Portfolio, classId: string) {
  const holdings = portfolio.instruments
    .filter((row) => row.asset_class === classId && row.value > 0)
    .sort((a, b) => b.value - a.value);
  const total = holdings.reduce((sum, row) => sum + row.value, 0);
  let kept = holdings.filter((row, i) => i < KEEP_LARGEST || row.value / total >= OTHERS_BELOW);
  let grouped = holdings.filter((row) => !kept.includes(row));
  if (grouped.length === 1) { // an "Others" of one is just that holding
    kept = holdings;
    grouped = [];
  }
  const colors = shades(CLASS_COLORS[classId], kept.length);
  const slices: Slice[] = kept.map((row, i) => ({ id: row.id, name: row.name, value: row.value, color: colors[i] }));
  if (grouped.length) {
    slices.push({
      id: "others", name: `Others (${grouped.length})`, color: OTHERS_COLOR,
      value: grouped.reduce((sum, row) => sum + row.value, 0), members: grouped.map((row) => row.name),
    });
  }
  const colorOf = new Map(slices.map((slice) => [slice.id, slice.color]));
  const legend: Slice[] = holdings.map((row) => ({
    id: row.id, name: row.name, value: row.value, color: colorOf.get(row.id) ?? OTHERS_COLOR,
  }));
  return { slices, legend, total };
}

/** Classes that open into their holdings: not cash, and only with value (zero ones aren't drawn). */
export const DRILLABLE = new Set(CLASS_ORDER);
