// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { CLASS_COLORS, OTHERS_COLOR, classSlices, holdingSlices, shade } from "../src/allocation.ts";
import type { Portfolio } from "../src/types.ts";

function portfolio(values: Record<string, number>, cash = 0, assetClass = "indian-equities"): Portfolio {
  const instruments = Object.entries(values).map(([id, value]) => ({ id, name: id.toUpperCase(), asset_class: assetClass, value }));
  const total = instruments.reduce((sum, row) => sum + row.value, 0);
  return {
    portfolio: { value: total + cash, cash_inr: cash },
    asset_classes: { [assetClass]: { value: total }, crypto: { value: 0 } },
    instruments,
  } as unknown as Portfolio;
}

test("a class with few holdings gets one slice each, largest first, and the legend matches", () => {
  const { slices, legend, total } = holdingSlices(portfolio({ a: 100, b: 300, c: 0, d: 600 }), "indian-equities");
  assert.equal(total, 1000);
  assert.deepEqual(slices.map((s) => s.id), ["d", "b", "a"]); // zero-value holding left out
  assert.deepEqual(legend.map((s) => s.id), ["d", "b", "a"]);
  assert.equal(slices[0].color, shade(CLASS_COLORS["indian-equities"], -0.3));
});

test("past the seven largest, holdings under 3% of the class become Others; the legend lists all", () => {
  // 8 large holdings (one past the top 7 but still 10%+) and 3 tiny ones.
  const values: Record<string, number> = {};
  for (let i = 1; i <= 8; i += 1) values[`big${i}`] = 1000 + i;
  Object.assign(values, { tiny1: 50, tiny2: 40, tiny3: 30 });
  const { slices, legend, total } = holdingSlices(portfolio(values), "indian-equities");

  assert.equal(slices.length, 9); // 8 big + Others
  const others = slices.at(-1)!;
  assert.equal(others.id, "others");
  assert.equal(others.value, 120);
  assert.deepEqual(others.members, ["TINY1", "TINY2", "TINY3"]);
  assert.equal(others.color, OTHERS_COLOR);
  assert.equal(legend.length, 11);
  assert.equal(legend.find((s) => s.id === "tiny3")!.color, OTHERS_COLOR);
  assert.equal(slices.reduce((sum, s) => sum + s.value, 0), total); // nothing lost or counted twice
});

test("an Others of one holding is shown as that holding", () => {
  const values: Record<string, number> = { tiny: 10 };
  for (let i = 1; i <= 7; i += 1) values[`big${i}`] = 1000;
  const { slices } = holdingSlices(portfolio(values), "indian-equities");
  assert.equal(slices.length, 8);
  assert.ok(!slices.some((s) => s.id === "others"));
});

test("the top level leaves out zero-value classes and shows cash", () => {
  const slices = classSlices(portfolio({ a: 100 }, 50));
  assert.deepEqual(slices.map((s) => s.id), ["indian-equities", "cash"]);
});
