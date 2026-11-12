"""Zones and rates: what one method costs for one cart to one destination.

One function prices everything (:func:`price_for`); options, the adjuster
and the checkout hook all call it, so the price a buyer is shown and the
one the order records cannot disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .. import money
from ..models import DeliveryMethod, MethodKind, Rate, Zone

WEIGHT_BASIS_FLAT = "flat"
WEIGHT_BASIS_WEIGHT = "weight"
WEIGHT_BASIS_FALLBACK = "flat_fallback"

#: The cart-line attribute carrying a unit weight in integer grams.
WEIGHT_ATTR = "weight_grams"

FREE_THRESHOLD = "threshold"
FREE_PROMOTION = "promotion"


@dataclass(frozen=True)
class Destination:
    """The part of an address that zones read."""

    country: str
    region: str = ""
    postal_code: str = ""


@dataclass(frozen=True)
class CartShape:
    """What pricing needs from the cart."""

    currency: str
    subtotal: Decimal
    shippable: bool
    weight_kg: Decimal | None


@dataclass(frozen=True)
class Price:
    amount: Decimal
    currency: str
    zone: str | None
    weight_basis: str
    free_reason: str | None = None


def _norm_postcode(value: str) -> str:
    return "".join(str(value or "").split()).upper()


def zone_score(zone: Zone | None, dest: Destination | None) -> tuple | None:
    """Specificity of a zone for a destination; ``None`` = no match.

    Higher is more specific: (matched postcode prefix length, has regions,
    has countries). A missing zone matches everything with the lowest score.
    """
    if zone is None:
        return (-1, 0, 0)
    if dest is None:
        return None
    countries = [str(c).upper() for c in (zone.countries or [])]
    regions = [str(r).strip().casefold() for r in (zone.regions or [])]
    prefixes = [_norm_postcode(p) for p in (zone.postcode_prefixes or []) if _norm_postcode(p)]
    if countries and dest.country.upper() not in countries:
        return None
    if regions and dest.region.strip().casefold() not in regions:
        return None
    matched = 0
    if prefixes:
        code = _norm_postcode(dest.postal_code)
        hits = [len(p) for p in prefixes if code.startswith(p)]
        if not hits:
            return None
        matched = max(hits)
    return (matched, 1 if regions else 0, 1 if countries else 0)


def cart_shape(currency: str, subtotal, lines: list[dict]) -> CartShape:
    """Shippable flag and known weight of a cart (orders adjuster lines).

    A line with ``attrs.shippable is False`` is ignored; the weight is known
    only when every remaining line has ``attrs.weight_grams`` (the
    purchasable resolver's extra field, integer grams, snapshotted by orders).
    """
    shippable_lines = [
        line for line in lines
        if (line.get("attrs") or {}).get("shippable", True) is not False
    ]
    weight: Decimal | None = Decimal(0)
    for line in shippable_lines:
        unit = money.parse_grams((line.get("attrs") or {}).get(WEIGHT_ATTR))
        if unit is None:
            weight = None
            break
        weight += unit * int(line.get("quantity") or 0)
    if weight is not None:
        weight = money.quantize_weight(weight)
        if weight >= money.WEIGHT_LIMIT:
            weight = None
    return CartShape(
        currency=str(currency or "").upper(),
        subtotal=money.parse_decimal(subtotal, field="subtotal"),
        shippable=bool(shippable_lines),
        weight_kg=weight if shippable_lines else None,
    )


def free_shipping_marker(adjustments_so_far, method_code: str) -> bool:
    """Did an earlier adjuster (a promotion) grant free shipping for this method?

    The marker is ``meta.free_shipping == true`` on any earlier adjustment;
    ``meta.free_shipping_methods`` (a list of codes) narrows it.
    """
    for adjustment in adjustments_so_far or []:
        meta = (adjustment or {}).get("meta") or {}
        if meta.get("free_shipping") is not True:
            continue
        only = meta.get("free_shipping_methods")
        if isinstance(only, list) and only and method_code not in only:
            continue
        return True
    return False


def best_rate(method: DeliveryMethod, currency: str, dest: Destination | None) -> Rate | None:
    """The most specific enabled rate of the method in this currency."""
    candidates = []
    for rate in method.rates.filter(enabled=True, currency=currency).select_related("zone"):
        score = zone_score(rate.zone, dest)
        if score is not None:
            candidates.append((score, -rate.sort, -rate.pk, rate))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[:3], reverse=True)
    return candidates[0][3]


def price_for(method: DeliveryMethod, cart: CartShape, dest: Destination | None,
              adjustments_so_far=None) -> Price | None:
    """The price of ``method`` for ``cart`` to ``dest``; ``None`` = not offered."""
    rate = best_rate(method, cart.currency, dest)
    if rate is None:
        if method.kind == MethodKind.DIGITAL:
            return Price(Decimal("0.00"), cart.currency, None, WEIGHT_BASIS_FLAT)
        return None
    if (rate.max_weight_kg is not None and cart.weight_kg is not None
            and cart.weight_kg > rate.max_weight_kg):
        return None
    amount = Decimal(rate.amount)
    basis = WEIGHT_BASIS_FLAT
    if rate.per_kg is not None:
        if cart.weight_kg is not None:
            amount = amount + Decimal(rate.per_kg) * cart.weight_kg
            basis = WEIGHT_BASIS_WEIGHT
        else:
            basis = WEIGHT_BASIS_FALLBACK
    amount = money.quantize(amount)
    if amount >= money.AMOUNT_LIMIT:
        return None
    zone = rate.zone.code if rate.zone_id else None
    if rate.free_above is not None and cart.subtotal >= rate.free_above:
        return Price(Decimal("0.00"), cart.currency, zone, basis, FREE_THRESHOLD)
    if free_shipping_marker(adjustments_so_far, method.code):
        return Price(Decimal("0.00"), cart.currency, zone, basis, FREE_PROMOTION)
    return Price(amount, cart.currency, zone, basis)


__all__ = [
    "CartShape", "Destination", "Price", "best_rate", "cart_shape", "free_shipping_marker",
    "price_for", "zone_score",
]
