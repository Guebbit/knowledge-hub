# GRAPH_REPORT.md: gate it on graph size, and advertise it when it earns the line

**Status: planned.** This revises my earlier "drop it from the advertised list" —
you were right to push back, and the revision is below.

## Who creates it and why

graphify, but **not automatically any more**. Per your own comment at
`scripts/repo.py:245-252`: as of graphify 0.9.x, `extract` stops after writing
`graph.json` plus the analysis sidecar and no longer clusters, names communities, or
writes the report. So `2brain` makes a **second, explicit call** to produce it
(`repo.py:253-258`):

```python
cluster_cmd = ["graphify", "cluster-only", ".", "--backend", backend, "--model", model]
```

Then `_require_pipeline_artifacts()` (`repo.py:442`) makes its presence
**mandatory** — the pipeline dies without it.

It exists because it is graphify's own flagship output, built for graphify's use
case: a human doing first contact with an unfamiliar large codebase. That is what
"God Nodes", "Community Hubs" and "Surprising Connections" are for — orientation
when you know nothing at all.

## One correction to the earlier review

I called it a token sink. **It is not.** The report self-reports its own cost:

```
Token cost: 3,898 input · 253 output
```

The expensive pass is `extract`, which you need regardless because `graph.json`
feeds llm-wiki's neighbour expansion. Clustering is cheap.

So the report was never a budget problem. It is a **status** problem: a low-value
artifact was made a hard requirement and given a line in the directive that better
artifacts did not get.

## Your question: is it useless, or just useless *here*?

Useless **here**, genuinely valuable **there** — and the difference is not repo size
directly, it is whether the graph is large enough for communities to mean anything.

On this repo the report says so itself:

```
Cohesion: 0.07   Cohesion: 0.09   Cohesion: 0.06   Cohesion: 0.08
```

35 "communities" over 724 nodes at cohesion 0.06-0.09 are not clusters — that is
partition noise over a graph small enough that everything touches everything. And
the orientation is worthless to a reader who can simply read all 30 files. `die()`
has 31 edges because it is a helper called everywhere, not because it is a core
abstraction.

On a 3 000-file repository every one of those objections inverts:

- Nobody can read it all, so orientation becomes the binding constraint.
- "Which subsystem does this belong to?" becomes a real question with a real answer.
- God-nodes stop being trivia — at that scale high betweenness genuinely marks the
  abstractions that hold the system together.
- Import cycles matter, and are hard to find any other way.
- Cohesion rises, because real subsystems exist to be found.

So: **yes, gate it — and yes, advertise it when the gate passes.** Your instinct is
right and my earlier blanket "drop it" was wrong.

## Proposal

**1. Gate on node count, not file count.** `graph.json` already carries it — this
repo's has `nodes = 724` at the top level, so the check is free and needs no new
analysis. Below a threshold (~500 nodes is a reasonable starting point; tune once
you have run it on a big repo), skip the `cluster-only` call entirely.

**2. Make it optional, not required.** Remove `GRAPH_REPORT.md` from
`_require_pipeline_artifacts()`. A skipped report must not kill the pipeline, and
today a `cluster-only` failure dies with a "missing artifact" error that looks
unrelated to its cause — which your own comment at `repo.py:250-252` already
records as a footgun.

**3. Advertise conditionally.** This is the part that ties into
`repo-context-router.md`: the router should list `GRAPH_REPORT.md` **when it was
generated**, and leave it out when it was skipped. That falls out for free once
`_CONTEXT_ARTIFACTS` is derived from what exists instead of hardcoded — which is
that plan's first bullet.

**4. Consider cohesion as a second gate later.** The honest signal for "are these
communities real" is cohesion, but you only learn it after paying for clustering.
Once you have run this on a large repo, a rule like "omit the community section if
median cohesion < 0.2, keep cycles and god-nodes" may be worth it. Node count first
— it is free and it captures most of the benefit.

**Net effect:** small repos stop paying for and stop being pointed at a noise
artifact; large repos — the actual target — keep it *and* get it properly
advertised, which it is not today.

## Verification

Needs a large repository to confirm. When you next run `2brain` against a big
codebase, check whether median community cohesion rises meaningfully above the
0.06-0.09 seen here. If it does, the gate is correct and the threshold can be tuned
against real numbers. If it stays near 0.07 even at 3 000 files, then the clustering
itself is not producing signal and the report should be dropped outright — that
would be a graphify problem, not a 2brain one.
