"""Delivery never imports a sibling module — orders, geo and promotions are names."""
import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
FORBIDDEN = ("stapel_orders", "stapel_promotions", "stapel_inventory", "stapel_geo",
             "stapel_listings", "stapel_billing", "stapel_shop", "stapel_classified",
             "stapel_currencies", "stapel_notifications", "stapel_realtime", "stapel_auth")


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def _sources():
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE).parts
        if rel[0] in ("tests", "build", "dist", ".venv") or ".egg-info" in str(path):
            continue
        yield path


def test_no_sibling_import_anywhere():
    offenders = [
        (str(path.relative_to(PACKAGE)), name)
        for path in _sources()
        for name in _imports(path)
        if name.split(".")[0] in FORBIDDEN
    ]
    assert offenders == []


def test_the_scan_sees_the_package():
    """Inversion: the walk reaches the modules it claims to check."""
    names = {p.name for p in _sources()}
    assert {"models.py", "carriers.py", "views.py", "checkout.py", "rates.py", "checks.py"} <= names


def test_the_rule_fires_on_a_sibling_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from stapel_orders.models import Order\n")
    assert list(_imports(bad)) == ["stapel_orders.models"]
