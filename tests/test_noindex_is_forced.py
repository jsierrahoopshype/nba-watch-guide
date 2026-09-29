"""No test may read the noindex value that data/copy.json ships with.

The shipped value flips when the section launches, so a test that reads it
passes in one state and fails in the other. Tests that care about noindex
force it in their own fixture (conftest.data_with_noindex, or setting it on
a copy they own) and assert against that. Writing the key is fine; reading
it is not.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def noindex_reads(source: str) -> list[int]:
    """Line numbers where `source` reads a noindex value: x["noindex"],
    x.get("noindex"), or x.noindex (SiteContext.noindex comes straight from
    copy.json). Stores such as copy["noindex"] = True are not reads."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                and isinstance(node.slice, ast.Constant) and node.slice.value == "noindex"):
            lines.append(node.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "noindex"):
            lines.append(node.lineno)
        elif (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and node.attr == "noindex"):
            lines.append(node.lineno)
    return sorted(set(lines))


def test_the_check_catches_each_kind_of_read():
    assert noindex_reads('json.loads(open("data/copy.json").read())["noindex"]') == [1]
    assert noindex_reads('copy = load_copy()\nif copy.get("noindex", False): pass') == [2]
    assert noindex_reads("assert ctx.noindex") == [1]
    assert noindex_reads('copy["noindex"] = True\nenv.globals["noindex"] = False') == []


def test_no_test_file_reads_the_shipped_noindex_value():
    offenders = [f"{path.name}:{line}"
                 for path in sorted(TESTS.glob("*.py"))
                 for line in noindex_reads(path.read_text(encoding="utf-8"))]
    assert offenders == [], (
        "these lines read noindex; force it in a fixture instead "
        f"(conftest.data_with_noindex): {', '.join(offenders)}")
