"""Generated-path bookkeeping: what a 2brain run itself writes must not look
like a source change (S2), except the scope file, which genuinely should.
"""

from __future__ import annotations

from shared import config


class TestGeneratedFiles:
    def test_gitignore_is_generated(self):
        assert ".gitignore" in config.GENERATED_FILES

    def test_scope_file_is_not_generated(self):
        """A .2brainignore edit is a real reason to re-run the wiki."""
        assert config.SCOPE_FILE not in config.GENERATED_FILES

    def test_existing_managed_files_are_still_generated(self):
        for name in ("CLAUDE.md", ".github/copilot-instructions.md", ".graphifyignore", ".gitattributes"):
            assert name in config.GENERATED_FILES
