"""Tests for the module tier's grouping and graph lifting."""

from __future__ import annotations

import pytest

from repo import modules


def _files(spec: dict[str, int]) -> list[str]:
    """Build a file list from {directory: count}; "" means the repository root."""
    out = []
    for directory, count in spec.items():
        prefix = f"{directory}/" if directory else ""
        out.extend(f"{prefix}f{i}.ts" for i in range(count))
    return out


class TestSelectModules:
    def test_empty_input_produces_no_modules(self):
        assert modules.select_modules([]) == {}

    def test_every_file_lands_in_exactly_one_module(self):
        files = _files({"src/a": 5, "src/b": 5, "docs": 3, "": 2})
        grouped = modules.select_modules(files)
        assigned = [rel for members in grouped.values() for rel in members]
        assert sorted(assigned) == sorted(files)
        assert len(assigned) == len(set(assigned))

    def test_small_repo_collapses_to_a_single_root_module(self):
        """If the whole tree fits under the threshold there is nothing to split."""
        files = _files({"src/a": 2, "src/b": 2})
        assert set(modules.select_modules(files)) == {""}

    def test_subtree_under_the_threshold_is_not_split_further(self):
        """Descending past a big root must stop as soon as a subtree fits."""
        files = _files({"src/a": 5, "src/b": 5, "docs": modules._MAX_FILES_PER_MODULE + 1})
        grouped = modules.select_modules(files)
        assert "src" in grouped, "src/ fits in one module and must not split into a/ and b/"
        assert "src/a" not in grouped

    def test_large_tree_splits_into_children(self):
        files = _files({f"src/m{i}": 10 for i in range(6)})
        grouped = modules.select_modules(files)
        assert "src" not in grouped
        assert set(grouped) == {f"src/m{i}" for i in range(6)}

    def test_files_directly_in_a_split_directory_keep_a_home(self):
        """The split parent still owns its own loose files."""
        files = _files({f"src/m{i}": 10 for i in range(6)}) + ["src/loose.ts"]
        grouped = modules.select_modules(files)
        assert grouped["src"] == ["src/loose.ts"]

    def test_result_is_capped_and_loses_nothing(self):
        """Pathological input: 50 sibling directories must merge down, not overflow."""
        files = _files({f"src/m{i}": 3 for i in range(50)} | {"": 4})
        grouped = modules.select_modules(files)
        assert len(grouped) <= modules._MAX_MODULES
        assigned = [rel for members in grouped.values() for rel in members]
        assert sorted(assigned) == sorted(files)

    def test_flat_oversized_directory_is_not_split(self):
        """A directory with no subdirectories stays one module however big it is."""
        files = _files({"docs": modules._MAX_FILES_PER_MODULE * 2})
        assert set(modules.select_modules(files)) == {"docs"}

    def test_members_are_sorted(self):
        grouped = modules.select_modules(["src/z.ts", "src/a.ts"])
        assert grouped[""] == ["src/a.ts", "src/z.ts"]


class TestModuleAdjacency:
    def test_lifts_file_edges_to_module_level(self):
        grouped = {"src/a": ["src/a/x.ts"], "src/b": ["src/b/y.ts"]}
        linked = modules.module_adjacency(grouped, {"src/a/x.ts": {"src/b/y.ts"}})
        assert linked == {"src/a": {"src/b"}, "src/b": {"src/a"}}

    def test_intra_module_edges_are_dropped(self):
        """Two files in the same module are not a connection between modules."""
        grouped = {"src": ["src/x.ts", "src/y.ts"]}
        assert modules.module_adjacency(grouped, {"src/x.ts": {"src/y.ts"}}) == {"src": set()}

    def test_edges_to_undocumented_files_are_ignored(self):
        """Scope can exclude a file from the tier; its edges must not resurrect it."""
        grouped = {"src": ["src/x.ts"]}
        assert modules.module_adjacency(grouped, {"src/x.ts": {"tests/x.test.ts"}}) == {"src": set()}

    def test_result_is_symmetric(self):
        grouped = {"a": ["a/1.ts"], "b": ["b/2.ts"]}
        linked = modules.module_adjacency(grouped, {"a/1.ts": {"b/2.ts"}})
        assert all(other in linked[node] for node, others in linked.items() for other in others)


class TestFilePurpose:
    def test_extracts_the_purpose_paragraph(self):
        page = "# src/a.ts\n## Purpose\nDoes the thing.\n\n## Key elements\n- x\n"
        assert modules.file_purpose(page) == "Does the thing."

    def test_falls_back_when_the_section_is_missing(self):
        assert modules.file_purpose("# src/a.ts\nSome prose.\n") == "Some prose."

    def test_empty_page_yields_empty_string(self):
        assert modules.file_purpose("") == ""

    def test_skips_headings_and_bullet_markers(self):
        assert modules.file_purpose("## Purpose\n\n- Leading bullet.\n") == "Leading bullet."


class TestNaming:
    def test_module_notes_are_namespaced_by_repo(self):
        """Two repos with the same module must not collide in a shared vault."""
        assert modules.page_name_for("src/ui", "alpha") != modules.page_name_for("src/ui", "beta")

    def test_never_collides_with_a_per_file_wiki_page(self):
        from repo import wiki

        assert modules.page_name_for("src/auth", "r") != f"r_{wiki.page_name_for('src/auth.ts')}"

    def test_root_module_has_a_stable_name(self):
        assert modules.page_name_for("", "r") == "r_ROOT.md"

    @pytest.mark.parametrize("module", ["", "src", "src/deep/nest", "a-b/c.d"])
    def test_mermaid_ids_are_safe_identifiers(self, module):
        node_id = modules._mermaid_id(module)
        assert node_id.replace("_", "").isalnum()


class TestMermaid:
    def test_overview_renders_a_node_per_module(self):
        grouped = {"a": ["a/1.ts"], "b": ["b/2.ts"]}
        linked = {"a": {"b"}, "b": {"a"}}
        diagram = modules._mermaid_overview(grouped, linked)
        assert diagram.startswith("```mermaid")
        assert diagram.count("---") == 1, "one undirected edge, not one per direction"

    def test_overview_caps_edges_and_says_so(self):
        grouped = {f"m{i}": [f"m{i}/f.ts"] for i in range(30)}
        linked = {m: {other for other in grouped if other != m} for m in grouped}
        diagram = modules._mermaid_overview(grouped, linked)
        assert diagram.count(" --- ") == modules._MAX_DIAGRAM_EDGES
        assert "hidden to keep the diagram readable" in diagram

    def test_local_diagram_is_empty_for_an_isolated_module(self):
        assert modules._mermaid_local("a", {"a": set()}, {"a": []}) == ""
