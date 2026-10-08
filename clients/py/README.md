# modelwatch (Python)

Dependency-free (stdlib-only) client for the [ModelWatch](../..) AI model index —
capabilities, context windows and pricing, every figure with a source.

## Install

```bash
pip install modelwatch
```

## Use

```python
from modelwatch import ModelWatch

mw = ModelWatch()                                  # default base URL
# mw = ModelWatch(base_url="https://your-domain")

opus = mw.model("claude-opus-5")
print(opus["display_name"], opus["pricing"]["input"], opus["context"]["max_input_tokens"])

for m in mw.cheapest(by="input", limit=5, provider="anthropic"):
    print(m["display_name"], m["pricing"]["input"])

print(mw.changes()["changes"])                     # what moved since the last snapshot
```

## API

| Method | Returns |
|---|---|
| `dataset()` | `{"meta": ..., "models": [...]}` |
| `models()` | all model records |
| `model(id)` | one record, or `None` |
| `cheapest(by="input", limit=10, provider=None)` | cheapest models by `input`/`output` |
| `changes()` | change feed since the previous snapshot |

## License

MIT
