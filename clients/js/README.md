# modelwatch (JavaScript)

Dependency-free client for the [ModelWatch](../..) AI model index — capabilities,
context windows and pricing, every figure with a source.

## Install

```bash
npm install modelwatch
```

## Use

```js
import { ModelWatch } from "modelwatch";

const mw = new ModelWatch();                 // default base URL
// const mw = new ModelWatch({ baseUrl: "https://your-domain" });

const opus = await mw.model("claude-opus-5");
console.log(opus.display_name, opus.pricing.input, opus.context.max_input_tokens);

const cheap = await mw.cheapest({ by: "input", limit: 5, provider: "anthropic" });
for (const m of cheap) console.log(m.display_name, m.pricing.input);

const { changes } = await mw.changes();      // what moved since the last snapshot
```

Requires Node 18+ (built-in `fetch`), or pass `{ fetchImpl }` on older runtimes.

## API

| Method | Returns |
|---|---|
| `dataset()` | `{ meta, models }` |
| `models()` | all model records |
| `model(id)` | one record, or `null` |
| `cheapest({ by, limit, provider })` | cheapest models by `input`/`output` |
| `changes()` | `{ meta, changes }` since the previous snapshot |

## License

MIT
