"""The ``delivery.quote`` adjuster, called the way orders calls it (comm, §2 payloads)."""
import copy
import json
import re

import jsonschema
import pytest
from stapel_core.comm import call

from stapel_delivery.models import Address

from .factories import HOME, line, order_request

pytestmark = pytest.mark.django_db

#: The adjuster response contract (wave spec §2 + orders CONTRACT-DELTAS 5).
RESPONSE = {
    "type": "object",
    "required": ["adjustments", "errors"],
    "additionalProperties": False,
    "properties": {
        "adjustments": {"type": "array", "maxItems": 20, "items": {
            "type": "object",
            "required": ["kind", "code", "label", "amount", "line_index", "meta"],
            "properties": {
                "kind": {"enum": ["discount", "shipping", "tax", "fee"]},
                "code": {"type": "string", "maxLength": 64},
                "label": {"type": "string"},
                "amount": {"type": "string", "pattern": r"^-?[0-9]{1,14}(\.[0-9]{1,2})?$"},
                "line_index": {"type": ["integer", "null"]},
                "meta": {"type": "object"},
            }}},
        "errors": {"type": "array", "items": {
            "type": "object", "required": ["code", "field", "params"],
            "properties": {"code": {"type": "string", "pattern": r"^error\.[0-9]{3}\.[a-z_]+$"},
                           "field": {"type": ["string", "null"]}, "params": {"type": "object"}}}},
    },
}


def quote(payload):
    answer = call("delivery.quote", payload)
    jsonschema.validate(answer, RESPONSE)
    return answer


def error_codes(answer):
    return [e["code"] for e in answer["errors"]]


class TestHappyPaths:
    def test_courier_inline_address(self, catalog):
        answer = quote(order_request(delivery={"method": "courier", "address": HOME}))
        assert answer["errors"] == []
        [adj] = answer["adjustments"]
        assert (adj["kind"], adj["code"], adj["label"], adj["amount"], adj["line_index"]) == (
            "shipping", "courier", "Courier", "5.00", None)
        assert adj["meta"] == {"method": "courier", "kind": "courier", "carrier": "manual",
                               "zone": "metro", "weight_basis": "flat"}

    def test_meta_carries_no_personal_data(self, catalog):
        answer = quote(order_request(delivery={"method": "courier", "address": HOME}))
        blob = json.dumps(answer["adjustments"])
        for value in HOME.values():
            assert value not in blob

    def test_courier_from_the_address_book(self, catalog, user):
        a = Address.objects.create(user_id=str(user.pk), **{**HOME, "postal_code": "10001", "region": "NY"})
        answer = quote(order_request(user_id=str(user.pk), delivery={"method": "courier", "address_id": a.pk}))
        assert answer["adjustments"][0]["amount"] == "9.00"

    def test_pickup_point(self, catalog):
        answer = quote(order_request(delivery={"method": "pickup", "pickup_point": "pp-1"}))
        adj = answer["adjustments"][0]
        assert adj["amount"] == "2.00" and adj["meta"]["pickup_point"] == "pp-1"

    def test_digital_is_zero_and_still_recorded(self, catalog):
        answer = quote(order_request(delivery={"method": "email"}))
        assert answer["adjustments"][0]["amount"] == "0.00"

    def test_free_shipping_marker_honoured(self, catalog):
        marker = {"kind": "discount", "code": "SHIPFREE", "label": "Free shipping", "amount": "0.00",
                  "line_index": None, "meta": {"free_shipping": True}, "adjuster": "promotions"}
        answer = quote(order_request(delivery={"method": "courier", "address": HOME}, adjustments=[marker]))
        adj = answer["adjustments"][0]
        assert adj["amount"] == "0.00" and adj["meta"]["free_reason"] == "promotion"

    def test_weight_grams_price(self, catalog):
        far = {**HOME, "postal_code": "10001"}
        answer = quote(order_request(lines=[line(attrs={"weight_grams": 2000})],
                                     delivery={"method": "courier", "address": far}))
        assert answer["adjustments"][0]["amount"] == "12.00"
        assert answer["adjustments"][0]["meta"]["weight_basis"] == "weight"

    def test_unshippable_cart_needs_no_delivery(self, catalog):
        answer = quote(order_request(lines=[line(attrs={"shippable": False})]))
        assert answer == {"adjustments": [], "errors": []}

    def test_other_context_keys_are_left_alone(self, catalog):
        answer = quote(order_request(delivery={"method": "email"}, extra_context={"codes": ["X"]}))
        assert answer["errors"] == []


class TestRefusals:
    def test_no_delivery_choice_under_the_default(self, catalog):
        answer = quote(order_request())
        assert answer["adjustments"] == []
        assert answer["errors"] == [{"code": "error.400.delivery_method_required",
                                     "field": "delivery.method", "params": {}}]

    def test_no_delivery_choice_allowed_when_switched_off(self, catalog, settings):
        settings.STAPEL_DELIVERY = {"REQUIRE_METHOD": False}
        assert quote(order_request()) == {"adjustments": [], "errors": []}

    def test_unknown_and_disabled_methods(self, catalog):
        assert error_codes(quote(order_request(delivery={"method": "teleport"}))) == [
            "error.400.delivery_method_unknown"]
        catalog.courier.enabled = False
        catalog.courier.save()
        assert error_codes(quote(order_request(delivery={"method": "courier", "address": HOME}))) == [
            "error.400.delivery_method_unknown"]

    def test_courier_without_address(self, catalog):
        assert error_codes(quote(order_request(delivery={"method": "courier"}))) == [
            "error.400.delivery_address_required"]

    @pytest.mark.parametrize("field,value", [("country", "USA"), ("phone", "call me"), ("line1", ""),
                                             ("postal_code", "!!"), ("name", "x" * 121)])
    def test_invalid_inline_address_names_the_field(self, catalog, field, value):
        answer = quote(order_request(delivery={"method": "courier", "address": {**HOME, field: value}}))
        [err] = answer["errors"]
        assert err["code"] == "error.400.delivery_address_invalid"
        assert err["field"] == f"delivery.address.{field}"

    def test_guest_cannot_use_an_address_id(self, catalog, user):
        a = Address.objects.create(user_id=str(user.pk), **HOME)
        answer = quote(order_request(user_id=None, delivery={"method": "courier", "address_id": a.pk}))
        assert error_codes(answer) == ["error.404.address_not_found"]

    def test_foreign_address_id_is_not_found(self, catalog, user, other_user):
        a = Address.objects.create(user_id=str(other_user.pk), **HOME)
        answer = quote(order_request(user_id=str(user.pk), delivery={"method": "courier", "address_id": a.pk}))
        assert error_codes(answer) == ["error.404.address_not_found"]

    def test_pickup_point_required_and_known(self, catalog):
        assert error_codes(quote(order_request(delivery={"method": "pickup"}))) == [
            "error.400.pickup_point_required"]
        assert error_codes(quote(order_request(delivery={"method": "pickup", "pickup_point": "nope"}))) == [
            "error.400.pickup_point_unknown"]

    def test_unserved_destination(self, catalog):
        abroad = {**HOME, "country": "DE", "postal_code": "10115", "region": ""}
        answer = quote(order_request(delivery={"method": "courier", "address": abroad}))
        assert error_codes(answer) == ["error.409.delivery_unavailable"]

    def test_cart_currency_without_a_rate(self, catalog):
        answer = quote(order_request(currency="EUR", delivery={"method": "courier", "address": HOME}))
        assert error_codes(answer) == ["error.409.delivery_unavailable"]

    def test_every_code_is_a_registered_error_key(self):
        errors = json.loads(open(__file__.replace("tests/test_quote.py", "docs/errors.json")).read())
        text = json.dumps(errors)
        for key in ("delivery_method_required", "delivery_method_unknown", "delivery_address_required",
                    "delivery_address_invalid", "pickup_point_required", "pickup_point_unknown",
                    "address_not_found", "delivery_unavailable"):
            assert re.search(rf"error\.[0-9]{{3}}\.{key}", text), key


def test_the_request_schema_refuses_a_malformed_call(catalog):
    from stapel_core.comm import CommError

    bad = copy.deepcopy(order_request(delivery={"method": "email"}))
    bad["currency"] = "usd"
    with pytest.raises((CommError, jsonschema.ValidationError, ValueError)):
        call("delivery.quote", bad)
