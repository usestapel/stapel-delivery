"""Every response body the committed schema declares is the body the views send.

The operation list is DERIVED from ``docs/schema.json``: an operation with a
declared JSON 2xx body and no recipe here fails loudly. Every body is
validated against its declared schema (OAS ``nullable`` honoured), and each
read is driven in a populated and an empty state.
"""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from .factories import HOME
from .shipping import make_shipment

REPO = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO / "docs" / "schema.json").read_text())
V1 = "/delivery/api/v1"

pytestmark = pytest.mark.django_db


def _json_schema(node):
    if isinstance(node, list):
        return [_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    rebuilt = {k: _json_schema(v) for k, v in node.items() if k != "nullable"}
    if node.get("nullable"):
        return {"anyOf": [rebuilt, {"type": "null"}]}
    return rebuilt


def _validator(body_schema):
    root = copy.deepcopy(body_schema)
    root["components"] = copy.deepcopy(SCHEMA["components"])
    return jsonschema.Draft202012Validator(_json_schema(root))


def _operations():
    ops = []
    for path, methods in SCHEMA["paths"].items():
        for method, op in methods.items():
            for code, response in op.get("responses", {}).items():
                body = response.get("content", {}).get("application/json", {}).get("schema")
                if body is not None and code.startswith("2"):
                    ops.append((method.upper(), path, int(code), body))
    return sorted(ops, key=lambda o: (o[1], o[0], o[2]))


OPERATIONS = _operations()


def _url(path, **params):
    for name, value in params.items():
        path = path.replace("{%s}" % name, str(value))
    assert "{" not in path, f"unfilled path parameter in {path}"
    return path


def _address(env, **over):
    return env.client.post(V1 + "/addresses/", {**HOME, **over}, format="json")


def r_addresses_list(env):
    empty = env.client.get(V1 + "/addresses/")
    _address(env)
    _address(env, label="Office")
    return [env.client.get(V1 + "/addresses/")], [empty]


def r_addresses_create(env):
    return [_address(env, label="Home", latitude="39.781721", longitude="-89.650148"), _address(env)], []


def r_address_get(env):
    a = _address(env).json()
    return [env.client.get(_url(V1 + "/addresses/{address_id}/", address_id=a["id"]))], []


def r_address_patch(env):
    a = _address(env).json()
    return [env.client.patch(_url(V1 + "/addresses/{address_id}/", address_id=a["id"]),
                             {"label": "Cottage", "is_default": True}, format="json")], []


def r_address_default(env):
    _address(env)
    b = _address(env).json()
    return [env.client.post(_url(V1 + "/addresses/{address_id}/default/", address_id=b["id"]))], []


def r_methods(env):
    return [env.client.get(V1 + "/methods/")], []


def r_options(env):
    body = {"currency": "USD", "subtotal": "20.00", "lines": [{"quantity": 1, "attrs": {"weight_grams": 500}}]}
    with_address = env.client.post(V1 + "/options/", {**body, "address": {"country": "US"}}, format="json")
    return [env.client.post(V1 + "/options/", body, format="json"), with_address], []


def r_pickup_points(env):
    empty = env.client.get(V1 + "/pickup-points/?country=DE")
    return [env.client.get(V1 + "/pickup-points/")], [empty]


def r_shipments(env):
    empty = env.client.get(V1 + "/shipments/")
    for i in range(3):
        make_shipment(env.user.pk, order_id=f"w{i}")
    return [env.client.get(V1 + "/shipments/?limit=2")], [empty]


def r_shipment(env):
    s = make_shipment(env.user.pk)
    return [env.client.get(_url(V1 + "/shipments/{shipment_id}/", shipment_id=s.pk))], []


def r_staff_shipments(env):
    c = env.client_for(env.staff)
    empty = c.get(V1 + "/staff/shipments/")
    make_shipment(env.user.pk)
    return [c.get(V1 + "/staff/shipments/")], [empty]


def r_staff_shipment(env):
    s = make_shipment(env.user.pk)
    return [env.client_for(env.staff).get(
        _url(V1 + "/staff/shipments/{shipment_id}/", shipment_id=s.pk))], []


def r_tracking(env):
    s = make_shipment(env.user.pk)
    return [env.client_for(env.staff).post(
        _url(V1 + "/staff/shipments/{shipment_id}/tracking/", shipment_id=s.pk),
        {"tracking_number": "TRK1"}, format="json")], []


def r_transition(env):
    s = make_shipment(env.user.pk)
    return [env.client_for(env.staff).post(
        _url(V1 + "/staff/shipments/{shipment_id}/transition/", shipment_id=s.pk),
        {"to": "shipped", "note": "left the warehouse"}, format="json")], []


RECIPES = {
    ("GET", V1 + "/addresses/", 200): r_addresses_list,
    ("POST", V1 + "/addresses/", 201): r_addresses_create,
    ("GET", V1 + "/addresses/{address_id}/", 200): r_address_get,
    ("PATCH", V1 + "/addresses/{address_id}/", 200): r_address_patch,
    ("POST", V1 + "/addresses/{address_id}/default/", 200): r_address_default,
    ("GET", V1 + "/methods/", 200): r_methods,
    ("POST", V1 + "/options/", 200): r_options,
    ("GET", V1 + "/pickup-points/", 200): r_pickup_points,
    ("GET", V1 + "/shipments/", 200): r_shipments,
    ("GET", V1 + "/shipments/{shipment_id}/", 200): r_shipment,
    ("GET", V1 + "/staff/shipments/", 200): r_staff_shipments,
    ("GET", V1 + "/staff/shipments/{shipment_id}/", 200): r_staff_shipment,
    ("POST", V1 + "/staff/shipments/{shipment_id}/tracking/", 200): r_tracking,
    ("POST", V1 + "/staff/shipments/{shipment_id}/transition/", 200): r_transition,
}


class Env:
    def __init__(self, client, client_for, user, staff):
        self.client, self.client_for, self.user, self.staff = client, client_for, user, staff


def test_every_declared_operation_has_a_recipe():
    declared = {(m, p, c) for m, p, c, _ in OPERATIONS}
    assert declared == set(RECIPES), {
        "missing": sorted(declared - set(RECIPES)),
        "stale": sorted(set(RECIPES) - declared),
    }


@pytest.mark.parametrize("method,path,code,body_schema", OPERATIONS,
                         ids=[f"{m} {p} {c}" for m, p, c, _ in OPERATIONS])
def test_wire_matches_the_declared_body(method, path, code, body_schema,
                                         auth_client, client_for, user, staff, catalog):
    populated, empty = RECIPES[(method, path, code)](Env(auth_client, client_for, user, staff))
    validator = _validator(body_schema)
    for resp in populated + empty:
        assert resp.status_code == code, (method, path, resp.status_code, resp.content)
        errors = sorted(validator.iter_errors(resp.json()), key=str)
        assert not errors, [e.message for e in errors[:5]]
    for resp in populated:
        data = resp.json()
        for key in ("items", "options", "events"):
            if key in data:
                assert data[key], f"{method} {path}: populated '{key}' came back empty"
    for resp in empty:
        data = resp.json()
        if "items" in data:
            assert not data["items"], f"{method} {path}: the empty state is not empty"


def test_the_gate_is_not_blind(auth_client, user, catalog):
    """Inversion: a body validated against a wrong schema must fail."""
    s = make_shipment(user.pk)
    body = auth_client.get(f"{V1}/shipments/{s.pk}/").json()
    assert list(jsonschema.Draft202012Validator({"type": "string"}).iter_errors(body))
    broken = dict(body, amount=12.5)
    schema = SCHEMA["paths"][V1 + "/shipments/{shipment_id}/"]["get"]["responses"]["200"][
        "content"]["application/json"]["schema"]
    assert list(_validator(schema).iter_errors(broken))
