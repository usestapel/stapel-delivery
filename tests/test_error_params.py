"""Every raised error's params are the placeholders of its English template.

``docs/errors.json`` declares an error's params from the ``{placeholders}``
of its template, so a client (and the translation catalogs) know what to
interpolate. This gate walks every raise site in the package source — calls
of RAISERS with an error-key constant and a literal params dict — and
requires the dict keys to equal the template's placeholders. It cannot see
params built dynamically (a non-literal dict fails the gate, by design).
"""
import ast
from pathlib import Path

import pytest
from stapel_core.i18n.domains import params_of

from stapel_delivery import errors

ROOT = Path(__file__).resolve().parent.parent
#: call name -> (index of the key argument, index of the params argument)
RAISERS = {"DeliveryError": (1, 2), "StapelValidationError": (0, 1), "StapelErrorResponse": (1, 2)}
TEMPLATES = getattr(errors, "STAPEL_DELIVERY_ERRORS")


def _sources():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in ("tests", ".venv", "migrations", "build") or rel.name.startswith("_codegen"):
            continue
        yield rel, ast.parse(path.read_text(encoding="utf-8"))


def _name(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def raise_sites():
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _name(node.func) not in RAISERS:
                continue
            key_at, params_at = RAISERS[_name(node.func)]
            if len(node.args) <= key_at:
                continue
            key_name = _name(node.args[key_at])
            if key_name is None or not key_name.startswith("ERR_") or not hasattr(errors, key_name):
                continue
            params = node.args[params_at] if len(node.args) > params_at else next(
                (k.value for k in node.keywords if k.arg == "params"), None)
            yield f"{rel}:{node.lineno}", getattr(errors, key_name), params


SITES = list(raise_sites())


def test_the_gate_sees_raise_sites():
    assert len(SITES) >= 15, f"checked {len(SITES)} raise sites"


@pytest.mark.parametrize("where,key,params", SITES, ids=[s[0] for s in SITES])
def test_params_are_the_declared_placeholders(where, key, params):
    if params is None or (isinstance(params, ast.Constant) and params.value is None):
        sent = set()
    else:
        assert isinstance(params, ast.Dict), f"{where}: params of {key} must be a literal dict"
        assert all(isinstance(k, ast.Constant) for k in params.keys), f"{where}: non-literal param name"
        sent = {k.value for k in params.keys}
    assert sent == set(params_of(TEMPLATES[key])), f"{where}: {key} sends {sorted(sent)}"
