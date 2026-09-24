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
        from repo import llm_wiki

        assert modules.page_name_for("src/auth", "r") != f"r_{llm_wiki.page_path_for('src/auth.ts')}"

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


class TestFoldColocatedTests:
    """M2: a module's own tests belong in its note, not a competing sibling
    module — src/modules/account/tests/** must count toward src/modules/account.
    """

    def test_nested_tests_dir_folds_into_its_parent(self):
        assert modules._directory_of("src/modules/account/tests/unit/two-factor.test.ts") == "src/modules/account"

    def test_nested_test_singular_and_dunder_also_fold(self):
        assert modules._directory_of("src/modules/orders/test/order.test.ts") == "src/modules/orders"
        assert modules._directory_of("src/modules/orders/__tests__/order.test.ts") == "src/modules/orders"

    def test_top_level_tests_tree_is_unaffected(self):
        """No parent to fold into — this is M1's job, not M2's."""
        assert modules._directory_of("tests/unit/infrastructure/adapters/x.test.ts") == "tests/unit/infrastructure/adapters"

    def test_a_deeper_nested_tests_dir_still_folds(self):
        assert modules._directory_of("src/modules/account/controllers/tests/x.test.ts") == "src/modules/account/controllers"

    def test_colocated_tests_land_in_the_parent_module(self):
        # A large sibling forces a real top-down split, so account's own subtree
        # (small on its own) isn't just absorbed whole into an even bigger parent.
        files = _files(
            {"src/modules/account": 5, "src/modules/account/tests": 8, "docs": modules._MAX_FILES_PER_MODULE + 1}
        )
        grouped = modules.select_modules(files)

        account_files = [f for f in files if f.startswith("src/modules/account")]
        owning = {module for module, members in grouped.items() if any(f in members for f in account_files)}

        assert len(owning) == 1, "code and its co-located tests must land in the same module"
        assert not modules._is_test_tree(next(iter(owning)))


class TestTestTreesMergeFirst:
    """M1: the merge loop's key is (is_test_tree, size, name) — test trees merge
    away however large, before any domain module loses its slot to one.
    """

    def test_is_test_tree_detects_top_level_test_roots(self):
        assert modules._is_test_tree("tests") is True
        assert modules._is_test_tree("tests/unit") is True
        assert modules._is_test_tree("test/unit") is True
        assert modules._is_test_tree("__tests__/unit") is True
        assert modules._is_test_tree("src/modules/account") is False
        assert modules._is_test_tree("") is False

    def test_boilerplate_shaped_repo_keeps_domain_modules_and_merges_test_trees_first(self):
        """27 domain modules (216 files) + a tests/ tree big enough to split into
        4 sub-modules of its own (unit/infrastructure nesting, integration,
        cross-cutting, support) — 31 modules total, one over cap. The one
        needed merge must come from the test side; every domain module keeps
        its own note.
        """
        spec: dict[str, int] = {}
        for i in range(27):
            spec[f"src/modules/d{i}"] = 8
        spec["tests/unit"] = 15
        spec["tests/unit/infrastructure/adapters"] = 12
        spec["tests/unit/infrastructure/http"] = 10
        spec["tests/integration"] = 14
        spec["tests/cross-cutting"] = 8
        spec["tests/support"] = 6
        files = _files(spec)

        grouped = modules.select_modules(files)

        assert len(grouped) <= modules._MAX_MODULES
        for i in range(27):
            assert f"src/modules/d{i}" in grouped, f"domain module d{i} lost its slot"
        assert sum(1 for m in grouped if modules._is_test_tree(m)) < 4, "at least one test module must have merged"


class TestRootEdgesDroppedFromDiagrams:
    """M3: ROOT links to nearly everything (package.json, tsconfig.json, ...) —
    true, but clutter. It keeps its note and file list; only diagram edges drop.
    """

    def test_root_never_appears_in_an_overview_edge(self):
        grouped = {modules._ROOT_MODULE: ["package.json"], "src": ["src/a.ts"], "docs": ["docs/b.md"]}
        linked = {
            modules._ROOT_MODULE: {"src", "docs"},
            "src": {modules._ROOT_MODULE},
            "docs": {modules._ROOT_MODULE},
        }

        diagram = modules._mermaid_overview(grouped, linked)

        root_id = modules._mermaid_id(modules._ROOT_MODULE)
        assert f"{modules._mermaid_id('src')} --- {root_id}" not in diagram
        assert f"{root_id} --- {modules._mermaid_id('src')}" not in diagram
        assert " --- " not in diagram  # every edge here touches ROOT, so none survive

    def test_root_still_gets_a_node_in_the_overview(self):
        grouped = {modules._ROOT_MODULE: ["package.json"], "src": ["src/a.ts"]}
        linked = {modules._ROOT_MODULE: {"src"}, "src": {modules._ROOT_MODULE}}

        diagram = modules._mermaid_overview(grouped, linked)

        assert modules._mermaid_id(modules._ROOT_MODULE) in diagram

    def test_root_is_excluded_from_another_modules_local_diagram(self):
        linked = {"src": {modules._ROOT_MODULE, "docs"}, modules._ROOT_MODULE: {"src"}, "docs": {"src"}}
        grouped = {"src": ["src/a.ts"], modules._ROOT_MODULE: ["package.json"], "docs": ["docs/b.md"]}

        diagram = modules._mermaid_local("src", linked, grouped)

        assert modules._mermaid_id(modules._ROOT_MODULE) not in diagram
        assert modules._mermaid_id("docs") in diagram

    def test_roots_own_local_diagram_still_shows_its_links(self):
        linked = {modules._ROOT_MODULE: {"src"}, "src": {modules._ROOT_MODULE}}
        grouped = {modules._ROOT_MODULE: ["package.json"], "src": ["src/a.ts"]}

        diagram = modules._mermaid_local(modules._ROOT_MODULE, linked, grouped)

        assert modules._mermaid_id("src") in diagram
