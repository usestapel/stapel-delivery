"""The rate model: zone specificity, weight, thresholds, the free-shipping marker."""
from decimal import Decimal

import pytest

from stapel_delivery.models import DeliveryMethod, MethodKind, Rate, Zone
from stapel_delivery.services import rates

from .factories import line

pytestmark = pytest.mark.django_db

SPRINGFIELD = rates.Destination(country="US", region="IL", postal_code="627 01")
ELSEWHERE = rates.Destination(country="US", region="NY", postal_code="10001")
ABROAD = rates.Destination(country="DE", postal_code="10115")


def shape(lines, subtotal="20.00", currency="USD"):
    return rates.cart_shape(currency, subtotal, lines)


class TestZones:
    def test_null_zone_matches_everything_least_specific(self):
        assert rates.zone_score(None, ABROAD) == (-1, 0, 0)

    def test_country_region_postcode_all_must_match(self):
        zone = Zone(code="z", name="z", countries=["us"], regions=["il"], postcode_prefixes=["62"])
        assert rates.zone_score(zone, SPRINGFIELD) == (2, 1, 1)
        assert rates.zone_score(zone, ELSEWHERE) is None
        assert rates.zone_score(zone, ABROAD) is None
        assert rates.zone_score(zone, None) is None

    def test_longest_prefix_is_most_specific(self, catalog):
        rate = rates.best_rate(catalog.courier, "USD", SPRINGFIELD)
        assert rate.zone.code == "metro"
        assert rates.best_rate(catalog.courier, "USD", ELSEWHERE).zone.code == "domestic"

    def test_no_rate_abroad_or_in_another_currency(self, catalog):
        assert rates.best_rate(catalog.courier, "USD", ABROAD) is None
        assert rates.best_rate(catalog.courier, "EUR", SPRINGFIELD) is None

    def test_sort_breaks_ties_then_id(self, catalog):
        cheap = Rate.objects.create(method=catalog.courier, zone=catalog.metro, currency="USD",
                                    amount=Decimal("1.00"), sort=1)
        assert rates.best_rate(catalog.courier, "USD", SPRINGFIELD) == cheap


class TestPrice:
    def test_flat_in_metro(self, catalog):
        price = rates.price_for(catalog.courier, shape([line()]), SPRINGFIELD)
        assert (price.amount, price.zone, price.weight_basis) == (Decimal("5.00"), "metro", "flat")

    def test_weight_when_every_line_has_weight_grams(self, catalog):
        lines = [line(0, quantity=2, attrs={"weight_grams": 1250}), line(1, key="b", attrs={"weight_grams": "500"})]
        price = rates.price_for(catalog.courier, shape(lines), ELSEWHERE)
        # 9.00 + 1.50 * (2 * 1.25 + 0.5) = 13.50
        assert (price.amount, price.weight_basis) == (Decimal("13.50"), "weight")

    def test_flat_fallback_when_a_weight_is_missing(self, catalog):
        lines = [line(0, attrs={"weight_grams": 1000}), line(1, key="b")]
        price = rates.price_for(catalog.courier, shape(lines), ELSEWHERE)
        assert (price.amount, price.weight_basis) == (Decimal("9.00"), "flat_fallback")

    @pytest.mark.parametrize("bad", [1.5, -3, "1.5kg", True, None, "  "])
    def test_unreadable_weight_is_unknown(self, bad):
        assert shape([line(attrs={"weight_grams": bad})]).weight_kg is None

    def test_unshippable_lines_are_ignored(self):
        cart = shape([line(0, attrs={"shippable": False}), line(1, key="b", attrs={"weight_grams": 2000})])
        assert cart.shippable and cart.weight_kg == Decimal("2.000")
        assert not shape([line(attrs={"shippable": False})]).shippable

    def test_free_above_threshold(self, catalog):
        price = rates.price_for(catalog.courier, shape([line(unit_price="100.00")], subtotal="100.00"),
                                SPRINGFIELD)
        assert (price.amount, price.free_reason) == (Decimal("0.00"), "threshold")

    def test_just_below_threshold_pays(self, catalog):
        price = rates.price_for(catalog.courier, shape([line()], subtotal="99.99"), SPRINGFIELD)
        assert price.amount == Decimal("5.00") and price.free_reason is None

    def test_free_shipping_marker_from_a_promotion(self, catalog):
        marker = [{"kind": "discount", "code": "FREESHIP", "amount": "0.00", "adjuster": "promotions",
                   "line_index": None, "meta": {"free_shipping": True}}]
        price = rates.price_for(catalog.courier, shape([line()]), SPRINGFIELD, marker)
        assert (price.amount, price.free_reason) == (Decimal("0.00"), "promotion")

    def test_marker_narrowed_to_other_methods_does_not_apply(self, catalog):
        marker = [{"meta": {"free_shipping": True, "free_shipping_methods": ["pickup"]}}]
        assert rates.price_for(catalog.courier, shape([line()]), SPRINGFIELD, marker).amount == Decimal("5.00")

    def test_marker_must_be_literally_true(self, catalog):
        marker = [{"meta": {"free_shipping": "yes"}}]
        assert rates.price_for(catalog.courier, shape([line()]), SPRINGFIELD, marker).amount == Decimal("5.00")

    def test_max_weight_refuses(self, catalog):
        Rate.objects.filter(method=catalog.courier).update(max_weight_kg=Decimal("1.000"))
        heavy = shape([line(attrs={"weight_grams": 1001})])
        assert rates.price_for(catalog.courier, heavy, SPRINGFIELD) is None
        unknown = shape([line()])
        assert rates.price_for(catalog.courier, unknown, SPRINGFIELD) is not None

    def test_digital_without_rate_is_free(self, catalog):
        price = rates.price_for(catalog.digital, shape([line()]), None)
        assert price.amount == Decimal("0.00")

    def test_courier_without_destination_needs_a_zoneless_rate(self, catalog):
        assert rates.price_for(catalog.courier, shape([line()]), None) is None

    def test_rounding_half_up(self):
        method = DeliveryMethod.objects.create(code="m", name="m", kind=MethodKind.COURIER)
        Rate.objects.create(method=method, currency="USD", amount=Decimal("0.00"), per_kg=Decimal("0.05"))
        price = rates.price_for(method, shape([line(attrs={"weight_grams": 100})]), ABROAD)
        assert price.amount == Decimal("0.01")  # 0.005 -> 0.01
