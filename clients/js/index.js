/**
 * ModelWatch client - AI model capabilities, context windows and pricing.
 *
 * Dependency-free. Reads the public read-only JSON API.
 *
 *   import { ModelWatch } from "modelwatch";
 *   const mw = new ModelWatch();                       // or { baseUrl: "..." }
 *   const opus = await mw.model("claude-opus-5");
 *   console.log(opus.pricing.input);                   // 5  (USD per million tokens)
 *   const cheap = await mw.cheapest({ by: "input", limit: 5 });
 */

export const DEFAULT_BASE_URL = "https://modelwatch.example";

export class ModelWatch {
  #baseUrl;
  #fetch;

  constructor({ baseUrl = DEFAULT_BASE_URL, fetchImpl = globalThis.fetch } = {}) {
    if (typeof fetchImpl !== "function") {
      throw new Error("ModelWatch: no fetch available - pass { fetchImpl } on Node < 18");
    }
    this.#baseUrl = baseUrl.replace(/\/+$/, "");
    this.#fetch = fetchImpl;
  }

  async #get(path) {
    const res = await this.#fetch(`${this.#baseUrl}${path}`, {
      headers: { accept: "application/json" },
    });
    if (!res.ok) throw new Error(`ModelWatch: ${path} -> HTTP ${res.status}`);
    return res.json();
  }

  /** The whole dataset envelope: { meta, models }. */
  async dataset() {
    return this.#get("/api/v1/models.json");
  }

  /** All model records. */
  async models() {
    return (await this.dataset()).models;
  }

  /** One model record by id, or null. */
  async model(id) {
    const models = await this.models();
    return models.find((m) => m.id === id) ?? null;
  }

  /** Change feed between the two most recent snapshots: { meta, changes }. */
  async changes() {
    return this.#get("/api/v1/changes.json");
  }

  /**
   * Cheapest models by `by` ("input" | "output"), ascending.
   * Models without a published price are skipped.
   */
  async cheapest({ by = "input", limit = 10, provider } = {}) {
    let models = await this.models();
    if (provider) models = models.filter((m) => m.provider === provider);
    return models
      .filter((m) => typeof m.pricing?.[by] === "number")
      .sort((a, b) => a.pricing[by] - b.pricing[by])
      .slice(0, limit);
  }
}

export default ModelWatch;
