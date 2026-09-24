"""Editor-bridge injection: freshness wording, routing rules, GRAPH_REPORT inlining."""

from __future__ import annotations

from repo import injection


class TestFreshnessNote:
    """C2: a HEAD comparison always fires once the artifacts are committed (that
    commit moves HEAD), so the rule must be a per-file diff against the pinned
    baseline instead.
    """

    def test_rendered_text(self):
        note = injection._freshness_note("ad8d8602")
        assert note == (
            "Artifacts describe commit `ad8d8602`. Before relying on a wiki page, check its "
            "source: `git diff --quiet ad8d8602 -- <file>` (and `git status` for uncommitted "
            "edits). Changed → prefer the source for that file and say so. Unchanged → trust "
            "the page."
        )

    def test_empty_head_gives_no_note(self):
        assert injection._freshness_note("") == ""

    def test_no_head_comparison_language_survives(self):
        note = injection._freshness_note("ad8d8602")
        assert "rev-parse HEAD" not in note


class TestClaudeVsCopilotRouting:
    """C5: Claude Code follows @-imports (REPO_CONTEXT.md already has the routing
    rules), Copilot and Cursor cannot import, so they keep the rules inline.
    """

    def test_claude_block_has_no_inline_routing(self, tmp_path):
        block = injection._claude_inline(tmp_path, head="ad8d8602")
        assert "## Where to look" not in block
        assert "@.2brain/REPO_CONTEXT.md" in block

    def test_copilot_block_keeps_inline_routing(self, tmp_path):
        block = injection._copilot_inline(tmp_path, head="ad8d8602")
        assert "## Where to look" in block


class TestRoutingRules:
    def test_first_contact_points_at_overview_and_module_index_when_present(self, tmp_path):
        wiki = tmp_path / ".2brain" / "llm-wiki"
        wiki.mkdir(parents=True)
        (wiki / "OVERVIEW.md").write_text("# Overview\n")
        modules = tmp_path / ".2brain" / "modules"
        modules.mkdir(parents=True)
        (modules / f"{tmp_path.name}_INDEX.md").write_text("# Index\n")

        rules = injection._routing_rules(tmp_path, head="")

        assert "First contact" in rules
        assert ".2brain/llm-wiki/OVERVIEW.md" in rules
        assert f".2brain/modules/{tmp_path.name}_INDEX.md" in rules

    def test_no_first_contact_rule_without_both_pages(self, tmp_path):
        rules = injection._routing_rules(tmp_path, head="")
        assert "First contact" not in rules

    def test_graph_report_never_mentioned_in_routing(self, tmp_path):
        graphify_out = tmp_path / ".2brain" / "graphify-out"
        graphify_out.mkdir(parents=True)
        (graphify_out / "GRAPH_REPORT.md").write_text("# Graph Report\n")

        rules = injection._routing_rules(tmp_path, head="")

        assert "GRAPH_REPORT" not in rules


_GRAPH_REPORT_FIXTURE = """\
# Graph Report - . (2026-09-23)

## God Nodes (most connected - your core abstractions)

1. `t` - 217 edges
2. `successResponse()` - 211 edges
3. `catchAs()` - 146 edges

## Hyperedges (group relationships)

- **Webhook Delivery Pipeline (Event to Subscriber)** — a, b, c [INFERRED 0.85]
- **Contract Validation Pipeline (OpenAPI + AsyncAPI)** — d, e, f [EXTRACTED 0.90]

## Knowledge Gaps

- **12 isolated node(s)** — run `graphify query` to explore isolated nodes.
"""


class TestGraphReportHighlights:
    """3.1: god nodes and hyperedges are worth a reader's attention even though
    GRAPH_REPORT itself is dropped from routing — inlined into REPO_CONTEXT.md.
    """

    def test_inlines_god_nodes_and_hyperedge_titles(self, tmp_path):
        graphify_out = tmp_path / ".2brain" / "graphify-out"
        graphify_out.mkdir(parents=True)
        (graphify_out / "GRAPH_REPORT.md").write_text(_GRAPH_REPORT_FIXTURE)

        highlights = injection._graph_report_highlights(tmp_path)

        assert "## Most-used code" in highlights
        assert "`t` (217 edges)" in highlights
        assert "## Cross-cutting flows" in highlights
        assert "- Webhook Delivery Pipeline (Event to Subscriber)" in highlights
        assert "- Contract Validation Pipeline (OpenAPI + AsyncAPI)" in highlights

    def test_missing_report_gives_empty_string(self, tmp_path):
        assert injection._graph_report_highlights(tmp_path) == ""

    def test_report_without_either_section_gives_empty_string(self, tmp_path):
        graphify_out = tmp_path / ".2brain" / "graphify-out"
        graphify_out.mkdir(parents=True)
        (graphify_out / "GRAPH_REPORT.md").write_text("# Graph Report\n\n## Summary\n\n- 5 nodes\n")

        assert injection._graph_report_highlights(tmp_path) == ""
