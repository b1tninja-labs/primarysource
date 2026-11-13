"""IETF Internet-Drafts as a primarysource collection: `primarysource mcp --collection draft`.

The portfolio tracks documents that exist only as drafts (RTR version 2 and the ASPA PDU, ASPA verification,
LibrePGP, the TURN REST API), which the RFC library cannot cite. This collection imports named drafts from the
IETF's own servers into `$PRIMARYSOURCE_HOME/draft/` and serves them like the `rfc` collection does, with one
difference that matters: a draft has revisions and a life cycle, so every result says which revision it read and
whether that draft is still alive.

`docs/draft.md` is the user-facing description. Nothing here needs a dependency beyond the standard library;
serving needs the `[mcp]` extra. `primarysource draft ...` runs `cli.py`.
"""
