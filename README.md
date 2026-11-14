# primarysource

A primary source is the text itself: answer from it, and say exactly where it is.

One package, many collections. The core is a sectioned-document model, a ref grammar, token-budgeted paging, a fixed result shape, readers, a full-text index, a CLI and an MCP server. Each collection is a subpackage behind an extra: `rfc` (the RFC series, moved in from rfclib), `nist`, `usb`, `itu`, `zim`, `cve`, and more. `PLAN.md` has the design and `ROADMAP.md` the open work.

```
pip install "primarysource[rfc,mcp]"
primarysource collections
primarysource mcp --collection rfc
```

Pre-alpha. It ships no document text: you fetch the sources yourself.

## What works today

```python
from primarysource.budget import page
from primarysource.model import Document, Section, Unit, span_hash
from primarysource.refs import RefGrammar
from primarysource.render import render

grammar = RefGrammar(r"(?:RFC|BCP|STD)\d+")
ref = grammar.parse("RFC9000§9.6¶2")          # Ref(doc='RFC9000', section='9.6', para=2)

document = Document("demo", "Demo", Unit.SENTENCE, (Section("1", "Scope", ("First.", "Second.")),))
section = document.section("1")
result = page(section.units, start=1, max_tokens=2000)
print(render(" ".join(result.units), {"cite": "Demo §1", "unit": document.unit, "span": span_hash("First.")}))
```

| Module | What it does |
|---|---|
| `primarysource.model` | `Document`, `Section`, the declared `Unit` that `¶n` counts, `span_hash` |
| `primarysource.refs` | `RefGrammar`: `<doc>§<section>[#anchor][¶n]` and `<doc>:<first>-<last>`, for a library's own document-id pattern |
| `primarysource.budget` | `tokens`, `page`: whole units up to a token budget, always making progress, with `next_start` |
| `primarysource.render` | body plus `cite:`, `unit:`, `span:`, `next:`, `relaxed:`, `warning:` footer lines in a fixed order |
| `primarysource.errors` | `LibError(message, hint)`: an error that names its remedy |
| `primarysource.home` | `resolve_home(app)`: `$<APP>_HOME` or the per-user data directory; `atomic_write` |

## What it does not do yet

It reads no file format, builds no index, has no command and serves nothing. No library depends on it.

## Tests

`python -m pytest -q` from this directory. All tests use invented text.
