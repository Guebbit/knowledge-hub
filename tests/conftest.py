"""Shared test fixtures.

The suite deliberately covers only pure logic — how files are grouped into
modules, how the scope filter decides what is documented, how graphify's JSON is
parsed. Those are the parts that decide *what* the expensive LLM layers get
asked to do, so they are where a bug is both most likely and most costly, and
they need neither a network nor a running model to exercise.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def repo(tmp_path):
    """An empty repository directory for scope/cache round-trips."""
    return str(tmp_path)
