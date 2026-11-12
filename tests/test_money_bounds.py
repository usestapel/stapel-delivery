"""The price bound, derived from the constants and the column declarations.

A rate's flat part fits the column by declaration; the weight part is
``per_kg × weight`` and can exceed it, so a computed price at or above
``AMOUNT_LIMIT`` is "not offered" — never written. The test fails if anyone
widens a constant past a column.
"""
from decimal import Decimal

import pytest

from stapel_delivery import money
from stapel_delivery.models import DeliveryIntent, DeliveryMethod, MethodKind, Rate, Shipment
from stapel_delivery.services import rates

from .factories import line


def test_amount_limit_is_the_column():
    for model in (Rate, DeliveryIntent, Shipment):
        field = model._meta.get_field("amount")
        assert field.max_digits == money.AMOUNT_MAX_DIGITS
        assert field.decimal_places == money.DECIMAL_PLACES
        assert Decimal(10) ** (field.max_digits - field.decimal_places) == money.AMOUNT_LIMIT


def test_weight_limit_is_the_column():
    field = Shipment._meta.get_field("weight_kg")
    assert Decimal(10) ** (field.max_digits - field.decimal_places) == money.WEIGHT_LIMIT


@pytest.mark.django_db
def test_a_price_past_the_column_is_not_offered():
    method = DeliveryMethod.objects.create(code="heavy", name="Heavy", kind=MethodKind.COURIER)
    Rate.objects.create(method=method, currency="USD", amount=Decimal("1.00"),
                        per_kg=Decimal("9999999999.99"))
    cart = rates.cart_shape("USD", "1.00", [line(attrs={"weight_grams": 2000})])
    assert rates.price_for(method, cart, rates.Destination(country="US")) is None


@pytest.mark.django_db
def test_inversion_a_price_inside_the_column_is_offered():
    method = DeliveryMethod.objects.create(code="light", name="Light", kind=MethodKind.COURIER)
    Rate.objects.create(method=method, currency="USD", amount=Decimal("1.00"), per_kg=Decimal("1.00"))
    cart = rates.cart_shape("USD", "1.00", [line(attrs={"weight_grams": 2000})])
    assert rates.price_for(method, cart, rates.Destination(country="US")).amount == Decimal("3.00")
