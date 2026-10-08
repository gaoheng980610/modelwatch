/**
 * Client tests - no network; the transport is injected.
 * Run:  node --test clients/js
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { ModelWatch } from "../index.js";

const MODELS = {
  meta: { count: 3 },
  models: [
    { id: "cheap", provider: "acme", display_name: "Cheap", pricing: { input: 1, output: 2 } },
    { id: "pricey", provider: "acme", display_name: "Pricey", pricing: { input: 5, output: 50 } },
    { id: "unpriced", provider: "acme", display_name: "Unpriced", pricing: { input: null, output: null } },
  ],
};
const CHANGES = { meta: {}, changes: [{ model: "pricey", type: "price_input", from: 4, to: 5 }] };

const fetchImpl = async (url) => ({
  ok: true,
  status: 200,
  json: async () => (url.endsWith("/api/v1/changes.json") ? CHANGES : MODELS),
});

const failing = async () => ({ ok: false, status: 503, json: async () => ({}) });

test("normalizes the base URL", () => {
  assert.equal(new ModelWatch({ baseUrl: "https://x.test/", fetchImpl }).dataset instanceof Function, true);
});

test("models() returns every record", async () => {
  const mw = new ModelWatch({ baseUrl: "https://x.test", fetchImpl });
  assert.equal((await mw.models()).length, 3);
});

test("model() finds by id and returns null on miss", async () => {
  const mw = new ModelWatch({ baseUrl: "https://x.test", fetchImpl });
  assert.equal((await mw.model("cheap")).display_name, "Cheap");
  assert.equal(await mw.model("nope"), null);
});

test("cheapest() sorts ascending and skips unpriced models", async () => {
  const mw = new ModelWatch({ baseUrl: "https://x.test", fetchImpl });
  const ids = (await mw.cheapest({ by: "input" })).map((m) => m.id);
  assert.deepEqual(ids, ["cheap", "pricey"]);
});

test("cheapest() respects limit and provider", async () => {
  const mw = new ModelWatch({ baseUrl: "https://x.test", fetchImpl });
  assert.deepEqual((await mw.cheapest({ limit: 1 })).map((m) => m.id), ["cheap"]);
  assert.deepEqual(await mw.cheapest({ provider: "nobody" }), []);
});

test("changes() returns the feed", async () => {
  const mw = new ModelWatch({ baseUrl: "https://x.test", fetchImpl });
  assert.equal((await mw.changes()).changes[0].type, "price_input");
});

test("non-ok responses raise with the status", async () => {
  const mw = new ModelWatch({ baseUrl: "https://x.test", fetchImpl: failing });
  await assert.rejects(() => mw.models(), /HTTP 503/);
});
