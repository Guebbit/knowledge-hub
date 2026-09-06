"""Apply 2repo's build-time patches to the vendored CodeBoarding package.

Run by Dockerfile.scripts with CodeBoarding's own interpreter right after the
package is installed:

    /opt/codeboarding/bin/python /opt/codeboarding-patches/apply.py

Every patch is an exact-text replacement that must match *exactly once*. If a
future CodeBoarding release moves or rewrites an anchor, the build fails loudly
here instead of silently shipping the stock behaviour — the same guarantee the
old `sed ... && grep -q` chain gave, in one readable place. Re-running on an
already patched tree is a no-op.

Patches (anchors verified against CodeBoarding 0.13.8 and 0.13.10):

1. agents/agent.py — agent-invocation timeout from env.
   CodeBoarding hardcodes 300s for the first attempt and 600s on retry with no
   override. A slow local model can legitimately need longer, and since every
   retry restarts the same multi-turn reasoning chain from scratch, a too-short
   timeout just burns minutes on doomed retries. Read
   CODEBOARDING_AGENT_TIMEOUT_FIRST / _RETRY instead (repo/arch.py sets them from
   REPO_ARCH_AGENT_TIMEOUT), defaulting to the stock values.

2. agents/agent.py — context-window budget middleware.
   Wire ContextBudgetMiddleware (context_budget.py, installed alongside as
   `codeboarding_context_budget`) into create_agent() so tool results can never
   push the conversation past the model's real context window. See that module
   for the full rationale. No-op unless CODEBOARDING_CONTEXT_WINDOW is set.

3. agents/tools/read_file.py — read chunk size from env.
   readFile returns 300 lines per call; on a 32k window a handful of reads fill
   the whole conversation. Make the chunk CODEBOARDING_READ_FILE_LINES (default
   300, so stock behaviour is unchanged); repo/arch.py derives it from the
   window so a small local model reads in smaller pieces and can afford more of
   them before the budget guard has to step in.
"""

from __future__ import annotations

import importlib
import py_compile
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIDDLEWARE_SOURCE = HERE / "context_budget.py"
MIDDLEWARE_MODULE = "codeboarding_context_budget"


def _site_packages() -> Path:
    """Locate CodeBoarding's site-packages via the interpreter running this script."""
    agents = importlib.import_module("agents")
    return Path(agents.__file__).resolve().parent.parent


def _patch(path: Path, marker: str, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"already patched: {path}")
        return
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            sys.exit(
                f"PATCH FAILED: anchor found {count} time(s) instead of once in {path}.\n"
                f"CodeBoarding changed; update patches/codeboarding/apply.py.\n--- anchor ---\n{old}"
            )
        text = text.replace(old, new)
    if marker not in text:
        sys.exit(f"PATCH FAILED: marker {marker!r} missing after patching {path}")
    path.write_text(text, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    print(f"patched: {path}")


def patch_agent(site: Path) -> None:
    path = site / "agents" / "agent.py"
    text = path.read_text(encoding="utf-8")
    replacements: list[tuple[str, str]] = []
    if "\nimport os\n" not in text:
        replacements.append(("import json\n", "import json\nimport os\n"))
    replacements += [
        # (1) timeout from env
        (
            "            timeout_seconds = 300 if attempt == 0 else 600\n",
            "            timeout_seconds = (\n"
            "                int(os.environ.get(\"CODEBOARDING_AGENT_TIMEOUT_FIRST\", \"300\"))\n"
            "                if attempt == 0\n"
            "                else int(os.environ.get(\"CODEBOARDING_AGENT_TIMEOUT_RETRY\", \"600\"))\n"
            "            )\n",
        ),
        # (2) context budget middleware
        (
            "from agents.tools.toolkit import CodeBoardingToolkit\n",
            "from agents.tools.toolkit import CodeBoardingToolkit\n"
            f"from {MIDDLEWARE_MODULE} import ContextBudgetMiddleware\n",
        ),
        (
            "        self.agent: CompiledStateGraph = create_agent(\n"
            "            model=agent_llm,\n"
            "            tools=self.toolkit.get_agent_tools(),\n"
            "        )\n",
            "        self.agent: CompiledStateGraph = create_agent(\n"
            "            model=agent_llm,\n"
            "            tools=self.toolkit.get_agent_tools(),\n"
            "            middleware=[ContextBudgetMiddleware()],\n"
            "        )\n",
        ),
    ]
    _patch(path, marker="CODEBOARDING_AGENT_TIMEOUT_FIRST", replacements=replacements)


def patch_read_file(site: Path) -> None:
    path = site / "agents" / "tools" / "read_file.py"
    _patch(
        path,
        marker="CODEBOARDING_READ_FILE_LINES",
        replacements=[
            (
                "import logging\nfrom pathlib import Path\n",
                "import logging\nimport os\nfrom pathlib import Path\n",
            ),
            (
                "logger = logging.getLogger(__name__)\n",
                "logger = logging.getLogger(__name__)\n"
                "\n"
                "# 2repo patch: lines returned per readFile call. Stock CodeBoarding is 300;\n"
                "# repo/arch.py lowers it for small local context windows.\n"
                "_CHUNK_LINES = max(20, int(os.environ.get(\"CODEBOARDING_READ_FILE_LINES\", \"300\")))\n"
                "_HALF_CHUNK = _CHUNK_LINES // 2\n",
            ),
            (
                "        \"Returns 300 lines centered on the requested line. \"\n",
                "        f\"Returns {_CHUNK_LINES} lines centered on the requested line. \"\n",
            ),
            (
                "        if line_number < 150:\n"
                "            start_line = 0\n"
                "            end_line = min(total_lines, 300)\n"
                "        else:\n"
                "            start_line = max(0, line_number - 150)\n"
                "            end_line = min(total_lines, start_line + 300)\n"
                "            if end_line - start_line < 300 and start_line > 0:\n"
                "                potential_start = max(0, total_lines - 300)\n",
                "        if line_number < _HALF_CHUNK:\n"
                "            start_line = 0\n"
                "            end_line = min(total_lines, _CHUNK_LINES)\n"
                "        else:\n"
                "            start_line = max(0, line_number - _HALF_CHUNK)\n"
                "            end_line = min(total_lines, start_line + _CHUNK_LINES)\n"
                "            if end_line - start_line < _CHUNK_LINES and start_line > 0:\n"
                "                potential_start = max(0, total_lines - _CHUNK_LINES)\n",
            ),
        ],
    )


def install_middleware(site: Path) -> None:
    target = site / f"{MIDDLEWARE_MODULE}.py"
    shutil.copyfile(MIDDLEWARE_SOURCE, target)
    py_compile.compile(str(target), doraise=True)
    # Import it for real: this pulls in langchain's middleware API, so an
    # incompatible langchain bump fails the build here, not mid-run.
    module = importlib.import_module(MIDDLEWARE_MODULE)
    if not hasattr(module, "ContextBudgetMiddleware"):
        sys.exit(f"PATCH FAILED: {MIDDLEWARE_MODULE} has no ContextBudgetMiddleware")
    print(f"installed: {target}")


def main() -> None:
    site = _site_packages()
    install_middleware(site)
    patch_agent(site)
    patch_read_file(site)
    print("codeboarding patches applied")


if __name__ == "__main__":
    main()
