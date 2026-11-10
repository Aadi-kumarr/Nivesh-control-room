// Run with: npm test   (node --test; Node 22.18+ runs TypeScript directly)
import assert from "node:assert/strict";
import { test } from "node:test";
import { CACHE_MS, createStore, writeScope } from "../src/store.ts";

type Data = { profile: string; n: number };

/** Fetchers that record each call and resolve only when the test says so. */
function harness() {
  const calls: string[] = [];
  const pending: { key: string; resolve: (value: Data) => void; signal: AbortSignal }[] = [];
  let clock = 0;
  const counter = new Map<string, number>();

  const fetcher = (kind: string) => (profileId: string, signal: AbortSignal) => {
    const key = `${kind}:${profileId}`;
    calls.push(key);
    const n = (counter.get(key) ?? 0) + 1;
    counter.set(key, n);
    return new Promise<Data>((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      pending.push({ key, signal, resolve: (value) => resolve(value ?? { profile: profileId, n }) });
    });
  };

  const store = createStore<Data, Data, Data>(
    {
      portfolio: fetcher("portfolio"),
      history: fetcher("history"),
      backups: () => {
        calls.push("backups");
        return Promise.resolve({ profile: "-", n: 0 });
      },
    },
    () => clock,
  );

  /** Resolve the oldest pending request for this key with its own profile's data. */
  const answer = (key: string) => {
    const index = pending.findIndex((p) => p.key === key);
    assert.ok(index >= 0, `no pending ${key}`);
    const [request] = pending.splice(index, 1);
    const profile = key.split(":")[1];
    request.resolve({ profile, n: counter.get(key)! });
    return request;
  };

  return { store, calls, pending, answer, tick: (ms: number) => { clock += ms; } };
}

async function load(h: ReturnType<typeof harness>, profile: string) {
  h.store.switchTo(profile);
  const result = h.store.portfolio();
  await Promise.resolve();
  if (h.pending.some((p) => p.key === `portfolio:${profile}`)) h.answer(`portfolio:${profile}`);
  return result;
}

test("switching back to a profile already viewed uses the cache", async () => {
  const h = harness();
  await load(h, "A");
  await load(h, "B");
  const again = await load(h, "A");
  assert.deepEqual(again, { profile: "A", n: 1 });
  assert.deepEqual(h.calls, ["portfolio:A", "portfolio:B"]);
});

test("a write clears only that profile's cache", async () => {
  const h = harness();
  await load(h, "A");
  await load(h, "B");
  h.store.written(writeScope("POST", "/transactions", "A"));

  assert.equal(h.store.hasCached("A"), false);
  assert.equal(h.store.hasCached("B"), true);
  const refetched = await load(h, "A");
  assert.deepEqual(refetched, { profile: "A", n: 2 });
  await load(h, "B");
  assert.deepEqual(h.calls, ["portfolio:A", "portfolio:B", "portfolio:A"]);
});

test("shared writes (instruments, prices) clear every profile's cache", async () => {
  const h = harness();
  await load(h, "A");
  await load(h, "B");
  h.store.written(writeScope("PATCH", "/instruments/x", "B"));
  assert.equal(h.store.hasCached("A"), false);
  assert.equal(h.store.hasCached("B"), false);
  h.store.written(writeScope("POST", "/prices/refresh", "B"));
});

test("cash and profile delete are per profile; reads and exports clear nothing", () => {
  assert.deepEqual(writeScope("PUT", "/cash", "A"), { kind: "profile", profileId: "A" });
  assert.deepEqual(writeScope("DELETE", "/profiles/B", "A"), { kind: "profile", profileId: "B" });
  assert.deepEqual(writeScope("GET", "/transactions", "A"), { kind: "none" });
  assert.deepEqual(writeScope("POST", "/export", "A"), { kind: "none" });
});

test("a response requested before a write is not cached", async () => {
  const h = harness();
  h.store.switchTo("A");
  const early = h.store.portfolio();
  await Promise.resolve();
  h.store.written(writeScope("POST", "/transactions", "A"));
  h.answer("portfolio:A");
  await early;
  assert.equal(h.store.hasCached("A"), false);
});

test("cached data expires after 15 minutes, so prices still refresh", async () => {
  const h = harness();
  await load(h, "A");
  h.tick(CACHE_MS - 1);
  await load(h, "A");
  assert.equal(h.calls.length, 1);
  h.tick(1);
  await load(h, "A");
  assert.deepEqual(h.calls, ["portfolio:A", "portfolio:A"]);
});

test("a fast switch aborts the old request and never shows its data", async () => {
  const h = harness();
  h.store.switchTo("A");
  const slowA = h.store.portfolio();
  await Promise.resolve();
  const requestA = h.pending.find((p) => p.key === "portfolio:A")!;

  h.store.switchTo("B");
  assert.equal(requestA.signal.aborted, true);
  await assert.rejects(slowA, { name: "AbortError" });
  assert.equal(h.store.cachedPortfolio(), null); // nothing of A's shows while B loads

  const b = h.store.portfolio();
  await Promise.resolve();
  h.answer("portfolio:B");
  assert.deepEqual(await b, { profile: "B", n: 1 });
  assert.deepEqual(h.store.cachedPortfolio(), { profile: "B", n: 1 });
});

test("a late response for the old profile is stored under its own name and not returned", async () => {
  // Even if a request escaped the abort, its data stays with the profile it was asked for.
  let finishA: (value: Data) => void = () => undefined;
  const store = createStore<Data, Data, Data>({
    // Ignores the abort signal, like a server response already on its way.
    portfolio: (profileId) => new Promise<Data>((resolve) => {
      if (profileId === "A") finishA = resolve;
    }),
    history: () => new Promise<Data>(() => undefined),
    backups: () => Promise.resolve({ profile: "-", n: 0 }),
  });
  store.switchTo("A");
  const slowA = store.portfolio();
  store.switchTo("B");
  finishA({ profile: "A", n: 1 });
  assert.equal(await slowA, null); // not handed to the page now showing B
  assert.equal(store.cachedPortfolio(), null); // B is active and has nothing yet
  store.switchTo("A");
  assert.deepEqual(store.cachedPortfolio(), { profile: "A", n: 1 });
});

test("history is cached per profile and per portfolio as_of", async () => {
  const h = harness();
  h.store.switchTo("A");
  const first = h.store.history("t1");
  await Promise.resolve();
  h.answer("history:A");
  await first;
  await h.store.history("t1");
  assert.deepEqual(h.calls, ["history:A"]);
  const second = h.store.history("t2");
  await Promise.resolve();
  h.answer("history:A");
  await second;
  assert.deepEqual(h.calls, ["history:A", "history:A"]);
});

test("backups are fetched once and again only after a write", async () => {
  const h = harness();
  await h.store.backups();
  await h.store.backups();
  h.store.switchTo("B");
  await h.store.backups();
  assert.deepEqual(h.calls, ["backups"]);
  h.store.written(writeScope("PUT", "/cash", "B"));
  await h.store.backups();
  assert.deepEqual(h.calls, ["backups", "backups"]);
});
