"""The in-app feedback links must line up with the issue forms they open.

GitHub prefills an issue form by matching query keys to field ``id``s, and
silently ignores a key that does not exist. That failure is invisible in the
browser, so it gets caught here instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "optodraw" / "app" / "static" / "js" / "app.js"
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"


def _prefill_calls() -> list[tuple[str, list[str]]]:
    """Return ``(template, [prefilled field ids])`` for each openIssue() call."""

    source = APP_JS.read_text(encoding="utf-8")
    calls = []
    for match in re.finditer(r'openIssue\("([^"]+)",\s*\{(.*?)\n    \}\)', source, re.S):
        template, body = match.group(1), match.group(2)
        keys = re.findall(r"^\s{6}(\w+):", body, re.M)
        calls.append((template, keys))
    return calls


def test_the_editor_prefills_two_issue_forms():
    assert {template for template, _ in _prefill_calls()} == {
        "bug_report.yml",
        "component_request.yml",
    }


@pytest.mark.parametrize("template, keys", _prefill_calls())
def test_prefilled_keys_exist_in_the_form(template, keys):
    form = yaml.safe_load((TEMPLATES / template).read_text(encoding="utf-8"))
    ids = {field.get("id") for field in form["body"] if field.get("id")}
    assert keys, f"{template}: nothing prefilled — the link is doing no work"
    assert set(keys) <= ids, f"{template}: {set(keys) - ids} are not fields in the form"


def test_help_menu_points_at_the_real_repository():
    source = APP_JS.read_text(encoding="utf-8")
    assert 'const REPO_URL = "https://github.com/Acceluma/optodraw"' in source


def test_the_link_type_rule_names_types_that_exist():
    """The Route tool picks a link type from the two port kinds.

    It used to draw whatever sat first in the list — a free-space beam, even
    between two waveguide ports on a chip. The rule now names routing-type ids,
    and a renamed id would silently fall back to that same first entry.
    """

    source = APP_JS.read_text(encoding="utf-8")
    ids = set(re.findall(r'\{\s*id:\s*"([^"]+)"', source))
    assert {"beam", "wg_manhattan", "fiber"} <= ids

    rule = re.search(r"function linkTypeFor\(.*?\n\}", source, re.S)
    assert rule, "the port-kind rule is gone"
    for referenced in re.findall(r'routingTypeById\("([^"]+)"\)', rule.group(0)):
        assert referenced in ids, f"linkTypeFor names a routing type that does not exist: {referenced}"
    # and both port kinds the app distinguishes are actually handled
    assert '"free_space"' in rule.group(0) and '"optical"' in rule.group(0)
