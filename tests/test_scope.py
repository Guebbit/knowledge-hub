"""Tests for the .2repoignore scope filter."""

from __future__ import annotations

import pytest

from repo import scope


class TestMatches:
    def test_empty_scope_documents_everything(self):
        assert scope.Scope().matches("anything/at/all.ts")

    def test_include_restricts_to_listed_paths(self):
        only_src = scope.Scope(include=("src/**",))
        assert only_src.matches("src/deep/a.ts")
        assert not only_src.matches("docs/a.md")

    def test_exclude_removes_from_the_set(self):
        no_tests = scope.Scope(exclude=("**/*.test.ts",))
        assert no_tests.matches("src/a.ts")
        assert not no_tests.matches("src/a.test.ts")

    def test_exclude_wins_over_include(self):
        both = scope.Scope(include=("src/**",), exclude=("src/generated/**",))
        assert both.matches("src/a.ts")
        assert not both.matches("src/generated/a.ts")

    @pytest.mark.parametrize(
        ("pattern", "path", "expected"),
        [
            ("tests/**", "tests/unit/a.ts", False),
            ("tests/**", "src/tests/a.ts", True),
            ("**/tests/**", "src/tests/a.ts", False),
            ("*.md", "README.md", False),
            ("*.md", "docs/README.md", False),
        ],
    )
    def test_gitignore_semantics(self, pattern, path, expected):
        assert scope.Scope(exclude=(pattern,)).matches(path) is expected


class TestRoundTrip:
    def test_save_then_load_preserves_both_sections(self, repo):
        original = scope.Scope(include=("src/**", "api/**"), exclude=("**/*.test.ts",))
        scope.save(repo, original)
        assert scope.load(repo) == original

    def test_missing_file_loads_as_empty(self, repo):
        assert scope.load(repo).is_empty

    def test_comments_and_blank_lines_are_ignored(self, repo):
        scope.scope_file(repo).write_text("[include]\n# a comment\n\nsrc/**\n[exclude]\n")
        assert scope.load(repo) == scope.Scope(include=("src/**",))

    def test_patterns_outside_any_section_are_ignored(self, repo):
        """A stray pattern above the headers must not silently become an include."""
        scope.scope_file(repo).write_text("stray/**\n[exclude]\ndocs/**\n")
        assert scope.load(repo) == scope.Scope(exclude=("docs/**",))


class TestResolve:
    def test_one_sided_flag_preserves_the_other_side(self, repo):
        """Regression: --exclude alone used to wipe the include list off disk."""
        scope.save(repo, scope.Scope(include=("src/**",), exclude=("old/**",)))
        resolved = scope.resolve(repo, cli_exclude="docs/**", interactive=False)
        assert resolved == scope.Scope(include=("src/**",), exclude=("docs/**",))

    def test_an_empty_flag_clears_that_side_deliberately(self, repo):
        scope.save(repo, scope.Scope(include=("src/**",), exclude=("docs/**",)))
        resolved = scope.resolve(repo, cli_include="", interactive=False)
        assert resolved == scope.Scope(include=(), exclude=("docs/**",))

    def test_flags_persist_to_disk(self, repo):
        scope.resolve(repo, cli_exclude="docs/**", interactive=False)
        assert scope.load(repo).exclude == ("docs/**",)

    def test_env_overrides_the_file_without_persisting(self, repo, monkeypatch):
        scope.save(repo, scope.Scope(exclude=("docs/**",)))
        monkeypatch.setenv("REPO_EXCLUDE", "tests/**")
        assert scope.resolve(repo, interactive=False).exclude == ("tests/**",)
        assert scope.load(repo).exclude == ("docs/**",), "env must not rewrite the file"

    def test_non_interactive_first_run_documents_everything(self, repo):
        """No file, no tty: proceed permissively and leave no file behind, so a
        later interactive run still gets the prompt."""
        assert scope.resolve(repo, interactive=False).is_empty
        assert not scope.scope_file(repo).exists()

    @pytest.mark.parametrize("raw", ["a, b", "a b", " a ,, b ", "a,b"])
    def test_pattern_lists_accept_commas_and_whitespace(self, raw):
        assert scope._split_patterns(raw) == ("a", "b")
