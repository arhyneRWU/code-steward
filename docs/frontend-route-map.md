# Frontend route map

On a full-stack repository half the call graph lives on the other side
of an HTTP boundary. `trace` on a FastAPI handler could list every
Python caller — usually none, because the framework is the caller —
and still not name the one screen that actually uses it.

This maps browser call sites to the handlers they hit.

```
code-steward trace --endpoints --route sku-pins
code-steward endpoints              # mounted paths, not decorator literals
code-steward endpoints --unbound    # the call sites that matched nothing
```

The JavaScript parser is optional: `pip install 'code-steward[js]'`.
Without it the scanner reports nothing **and says so**, rather than
returning an empty result that reads like "no frontend calls this".

## What it extracts

`fetch` and `axios` call sites whose URL is written as a literal, plus
the file and line of the ones whose URL is computed. Both sides are
reduced to a route pattern before matching — `${id}` and `{item_id}`
both become `{}` — and the join is then string equality on
`(method, pattern)`.

Nothing is inferred. A `fetch(url)` is not chased back to where `url`
was assigned, and a pattern served by two handlers binds to neither.
This project has already measured a name-based resolver at 0.796
precision and rejected it; the same reasoning applies here.

Route decorators are resolved through their mount prefix, because
`@router.get("/sku-pins")` under `include_router(r, prefix="/api/admin")`
serves `/api/admin/sku-pins` and the decorator literal is not an
address any client can call. Resolution happens at query time rather
than at index time, so a prefix moved in `main.py` takes effect on the
next query instead of the next rebuild.

## Measured coverage

One run against a private full-stack repository (1,243 Python files,
273 first-party JavaScript files, 14,848 indexed units, 296 endpoints),
reported as it came out:

| | count |
|---|---|
| Browser call sites found | 158 |
| Bound to a route | **85 (53.8%)** |
| Unbound — computed URL | 64 |
| Unbound — literal URL, no matching route | 9 |
| Route handlers gaining ≥1 browser caller | 60 of 294 |

The whole pass, including loading a 64 MB index, took 5.3 seconds.

Cost on an index refresh, which is where it actually runs, measured on
the same repository:

| pass | seconds |
|---|---|
| Python AST calls and `TESTED_BY` (pre-existing) | 20.85 |
| Frontend route map (new) | 2.89 |

So the frontend pass is 12% of a refresh. Scanning prefixes originally
cost 2.6s of that on its own, because it parsed all 1,243 Python files;
only 153 of them name a router at all, and a substring prefilter before
`ast.parse` brought it to 0.57s with identical output.

The 64 computed URLs are the honest ceiling of this approach. They are
`fetch(url)` where `url` was assembled upstream, and resolving them
means dataflow inference this deliberately does not do.

The 9 literal-but-unmatched cases were inspected rather than tuned
away, and they are not one problem:

- Two name a route that **does not exist in the codebase at all**.
  That is a finding about the frontend, not a defect here.
- One builds a path segment from a ternary
  (`${scope ? "publish-changed" : "publish-all"}`), so the literal it
  carries is not a path.
- The rest are a literal client segment landing on a server path
  parameter — `/api/ui-settings/table.density` against
  `/api/ui-settings/{key}`. Matching those would mean letting any
  literal segment fill any path parameter, which would also match
  `/api/items/count` to `/api/items/{id}`. Left unmatched on purpose.

No normalisation was adjusted after seeing these numbers.

## What it does not do

JavaScript is not indexed as code units. There are no JS-to-JS `CALLS`
edges, no `TESTED_BY` against a JavaScript test suite, and `similar`
and `check` remain Python-only — `similarity.normalise` is built on
`ast.unparse` and `check` shells out to ruff, and neither has a
JavaScript equivalent in this scope. Both commands say so on a
JavaScript path rather than returning nothing.
