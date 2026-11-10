// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { customError, monthsBefore, periodDates } from "../src/periods.ts";

const TODAY = "2026-11-11";

test("presets count back from today; YTD starts on Dec 31 of the previous year", () => {
  assert.deepEqual(periodDates({ preset: "1M" }, TODAY), { start: "2026-10-11", end: null });
  assert.deepEqual(periodDates({ preset: "3M" }, TODAY), { start: "2026-08-11", end: null });
  assert.deepEqual(periodDates({ preset: "6M" }, TODAY), { start: "2026-05-11", end: null });
  assert.deepEqual(periodDates({ preset: "1Y" }, TODAY), { start: "2025-11-11", end: null });
  assert.deepEqual(periodDates({ preset: "YTD" }, TODAY), { start: "2025-12-31", end: null });
  assert.equal(periodDates({ preset: "All" }, TODAY), null);
});

test("a month back from the 31st lands on the shorter month's last day", () => {
  assert.equal(monthsBefore("2026-03-31", 1), "2026-02-28");
  assert.equal(monthsBefore("2024-03-31", 1), "2024-02-29");
  assert.equal(monthsBefore("2026-01-15", 3), "2025-10-15");
});

test("custom ranges must start before they end and not end after today", () => {
  assert.deepEqual(periodDates({ preset: "Custom", start: "2025-01-01", end: "2025-06-30" }, TODAY),
    { start: "2025-01-01", end: "2025-06-30" });
  assert.deepEqual(periodDates({ preset: "Custom", start: "2025-01-01", end: TODAY }, TODAY),
    { start: "2025-01-01", end: null });
  assert.equal(periodDates({ preset: "Custom", start: "2025-06-30", end: "2025-01-01" }, TODAY), null);
  assert.equal(customError("2025-01-01", "2026-12-01", TODAY), "The end date can't be after today.");
  assert.equal(customError(undefined, undefined, TODAY), "Pick a start date.");
  assert.equal(customError(TODAY, undefined, TODAY), "The start date must be before the end date.");
});
