"""A green run must mean a published run.

The publish and live-check steps of build-watch-guide-daily used to carry
`if: inputs.publish != false`. Push and schedule runs have no inputs, and
GitHub compares null and false as equal (both coerce to 0), so every merge
and daily build went green without publishing. These tests evaluate each
publishing step's `if:` the way GitHub would, for every event the workflow
runs on, and fail if one would skip.

The workflow files are read with a small line parser rather than PyYAML,
which is not in requirements.txt and so not installed in CI."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))

# Step outputs a publishing step may depend on, set to the run that must
# publish: a game day for the 30-minute refresh. Any other reference fails the
# test, so a new condition has to be added here on purpose.
STEP_OUTPUTS = {"steps.games.outputs.has_games": "true"}


# --------------------------------------------------------------------------
# GitHub Actions expressions (the subset the workflows use)
# --------------------------------------------------------------------------

TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>==|!=|&&|\|\||!|\(|\))"
                   r"|(?P<num>-?\d+(?:\.\d+)?)|(?P<name>[A-Za-z_][\w.-]*))")


def _tokens(expr: str) -> list[tuple[str, str]]:
    expr = expr.strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2]
    out, pos = [], 0
    expr = expr.strip()
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot read expression at {expr[pos:]!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
        while pos < len(expr) and expr[pos].isspace():
            pos += 1
    return out


def _number(value) -> float:
    """GitHub's coercion for loose equality: null 0, false 0, true 1,
    strings parsed as numbers ('' is 0, anything else unparseable is NaN)."""
    if value is None or value is False:
        return 0.0
    if value is True:
        return 1.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _equal(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()       # string comparison ignores case
    if type(a) is type(b):
        return a == b
    return _number(a) == _number(b)


def _truthy(value) -> bool:
    return value not in (None, False, 0, "") and value == value   # NaN is falsy


def evaluate(expr: str, context: dict):
    """Evaluate an `if:` expression. Unknown names raise KeyError."""
    tokens = _tokens(expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def primary():
        kind, text = take()
        if text == "(":
            value = or_()
            assert take()[1] == ")", expr
            return value
        if text == "!":
            return not _truthy(primary())
        if kind == "str":
            return text[1:-1].replace("''", "'")
        if kind == "num":
            return float(text)
        if kind == "name":
            literals = {"true": True, "false": False, "null": None}
            if text in literals:
                return literals[text]
            if text.startswith("inputs."):
                return context.get("inputs", {}).get(text[len("inputs."):])
            if text not in context:
                raise KeyError(f"unknown context {text!r} in {expr!r}")
            return context[text]
        raise ValueError(f"unexpected {text!r} in {expr!r}")

    def compare():
        left = primary()
        while peek()[1] in ("==", "!="):
            op = take()[1]
            right = primary()
            left = _equal(left, right) if op == "==" else not _equal(left, right)
        return left

    def and_():
        left = compare()
        while peek()[1] == "&&":
            take()
            right = compare()
            left = right if _truthy(left) else left
        return left

    def or_():
        left = and_()
        while peek()[1] == "||":
            take()
            right = and_()
            left = left if _truthy(left) else right
        return left

    value = or_()
    assert pos == len(tokens), f"trailing tokens in {expr!r}"
    return value


# --------------------------------------------------------------------------
# Workflow files (just enough structure: triggers, inputs, jobs, steps)
# --------------------------------------------------------------------------

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block(lines: list[str], start: int) -> list[str]:
    """Lines nested under lines[start], blank and comment lines dropped."""
    base = _indent(lines[start])
    out = []
    for line in lines[start + 1:]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if _indent(line) <= base:
            break
        out.append(line)
    return out


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def triggers(text: str) -> dict[str, dict]:
    """{event: {input name: default}} from the top-level `on:` block."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^on:\s*$", line))
    block = _block(lines, start)
    level = min(_indent(line) for line in block)
    events: dict[str, dict] = {}
    for i, line in enumerate(block):
        if _indent(line) == level:
            event = line.strip().split(":")[0]
            events[event] = {}
            if event == "workflow_dispatch":
                body = _block(block, i)
                names = [j for j, l in enumerate(body) if re.match(r"^\s+\w[\w-]*:\s*$", l)
                         and l.strip() != "inputs:"]
                for j in names:
                    default = next((re.match(r"\s*default:\s*(.+)$", l).group(1)
                                    for l in _block(body, j) if l.strip().startswith("default:")), None)
                    value = {"true": True, "false": False}.get(default, default) if default else None
                    events[event][body[j].strip().rstrip(":")] = value
    return events


def steps(text: str) -> list[dict[str, str]]:
    """Every step of every job: {job, job_if, name, if, run}."""
    lines = text.splitlines()
    out = []
    jobs_at = next(i for i, line in enumerate(lines) if re.match(r"^jobs:\s*$", line))
    jobs = _block(lines, jobs_at)
    job_level = min(_indent(line) for line in jobs)
    for j, line in enumerate(jobs):
        if _indent(line) != job_level:
            continue
        job = line.strip().rstrip(":")
        body = _block(jobs, j)
        key_level = min(_indent(l) for l in body)
        job_if = next((l.split("if:", 1)[1].strip() for l in body
                       if _indent(l) == key_level and l.strip().startswith("if:")), "")
        steps_at = next(k for k, l in enumerate(body) if l.strip() == "steps:")
        items = _block(body, steps_at)
        item_level = min(_indent(l) for l in items)
        starts = [k for k, l in enumerate(items) if _indent(l) == item_level and l.lstrip().startswith("- ")]
        for n, k in enumerate(starts):
            chunk = items[k:starts[n + 1] if n + 1 < len(starts) else len(items)]
            first = chunk[0].replace("- ", "  ", 1)
            field_level = _indent(first)
            fields: dict[str, str] = {}
            rows = [first] + chunk[1:]
            for r, row in enumerate(rows):
                m = re.match(r"^(\s*)([\w-]+):\s?(.*)$", row)
                if not m or len(m.group(1)) != field_level:
                    continue
                key, value = m.group(2), m.group(3)
                if value.strip() in ("|", ">"):
                    value = "\n".join(l.strip() for l in rows[r + 1:]
                                      if _indent(l) > field_level)
                fields[key] = _scalar(value)
            out.append({"job": job, "job_if": job_if, "name": fields.get("name", ""),
                        "if": fields.get("if", ""), "run": fields.get("run", "")})
    return out


def _is_publish(step) -> bool:
    return ("publish.sh" in step["run"] and "gh-pages" in step["run"]
            and "PUBLISH_CHECK_ONLY" not in step["run"])


def _is_live_check(step) -> bool:
    return "live_check.py" in step["run"]


def _runs(step, event: str, inputs: dict) -> bool:
    context = {"github.event_name": event, "inputs": inputs, **STEP_OUTPUTS}
    return all(_truthy(evaluate(cond, context)) for cond in (step["job_if"], step["if"]) if cond)


def _publishing():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        found = [s for s in steps(text) if _is_publish(s) or _is_live_check(s)]
        if found:
            yield path, triggers(text), found


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_the_daily_build_publishes_and_checks_the_live_site():
    text = (WORKFLOW_DIR / "build-watch-guide-daily.yml").read_text(encoding="utf-8")
    found = steps(text)
    assert any(_is_publish(s) for s in found), "the daily build lost its publish step"
    assert any(_is_live_check(s) for s in found), "the daily build lost its live check"
    assert {"push", "schedule", "workflow_dispatch"} <= set(triggers(text))


@pytest.mark.parametrize("path,events,found", list(_publishing()), ids=lambda v: getattr(v, "name", ""))
def test_publish_and_live_check_run_on_push_schedule_and_default_dispatch(path, events, found):
    for event, defaults in events.items():
        if event not in ("push", "schedule", "workflow_dispatch"):
            continue
        inputs = defaults if event == "workflow_dispatch" else {}
        for step in found:
            assert _runs(step, event, inputs), (
                f"{path.name}: '{step['name']}' would skip on {event} "
                f"(if: {step['if'] or step['job_if']})")


def test_dispatch_with_publish_off_still_skips():
    """The manual 'publish: false' switch keeps working."""
    text = (WORKFLOW_DIR / "build-watch-guide-daily.yml").read_text(encoding="utf-8")
    for step in (s for s in steps(text) if _is_publish(s) or _is_live_check(s)):
        assert not _runs(step, "workflow_dispatch", {"publish": False}), step["name"]


def test_the_old_condition_is_caught():
    """The condition that shipped green-but-unpublished runs is read as skipping."""
    old = {"job": "build", "job_if": "", "name": "old", "if": "inputs.publish != false", "run": ""}
    assert not _runs(old, "push", {})
    assert not _runs(old, "schedule", {})
    assert _runs(old, "workflow_dispatch", {"publish": True})


def test_expression_rules_follow_github():
    ctx = {"github.event_name": "push", "inputs": {}}
    assert evaluate("null == false", ctx) is True             # both coerce to 0
    assert evaluate("inputs.publish != false", ctx) is False
    assert evaluate("github.event_name == 'PUSH'", ctx) is True   # strings ignore case
    assert evaluate("github.event_name != 'workflow_dispatch' || inputs.publish", ctx) is True
    assert evaluate("!inputs.publish", ctx) is True
    assert evaluate("'true' == 'true' && 'a'", ctx) == "a"
    with pytest.raises(KeyError):
        evaluate("steps.unknown.outputs.x == 'true'", ctx)
