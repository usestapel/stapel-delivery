## What this is

Delivery for a Stapel shop: delivery methods (courier, pickup point,
digital), zones and rates, pickup points, a per-user address book, and
shipments with tracking. It plugs into **stapel-orders** without either
module importing the other: delivery is the orders shipping adjuster
(`delivery.quote`) and a checkout hook (`delivery.reserve` / `commit` /
`release`), and every placed order with a physical delivery gets a
shipment the buyer can track.

Without orders installed the catalog, the address book, the options
Function and the shipment API still work on their own.

## Quick start

```python
INSTALLED_APPS = [
    # ...
    "stapel_delivery",
]

# urls.py
path("delivery/api/", include("stapel_delivery.urls"))   # -> /delivery/api/v1/...

# carrier polling + intent purge (Celery optional: manage.py delivery_housekeeping)
from stapel_delivery.beat import get_delivery_beat_schedule
CELERY_BEAT_SCHEDULE = {**get_delivery_beat_schedule()}
```

Wire it into the orders checkout. A scaffolded project already calls the
merge helper in `settings.py`: add this brick's preset to that list (the
helper merges two levels deep, so other presets and your own keys stay):

<!-- orders-wiring:scaffold -->
```python
_stapel_merge_preset_defaults(globals(), [
    # ... the presets already listed (stapel_shop.preset, other companions),
    "stapel_delivery.preset",
])
```

A hand-wired project merges per key instead — **never assign**
`STAPEL_ORDERS = {...}`: pasted after another fragment it would drop that
fragment and the host's `PURCHASABLE_TYPES`:

<!-- orders-wiring:hand -->
```python
from stapel_delivery.preset import SETTINGS_DEFAULTS as _DELIVERY

STAPEL_ORDERS = globals().get("STAPEL_ORDERS") or {}
STAPEL_ORDERS = {
    **STAPEL_ORDERS,
    "ADJUSTERS": {**_DELIVERY["STAPEL_ORDERS"]["ADJUSTERS"], **STAPEL_ORDERS.get("ADJUSTERS", {})},
    "CHECKOUT_HOOKS": {**_DELIVERY["STAPEL_ORDERS"]["CHECKOUT_HOOKS"], **STAPEL_ORDERS.get("CHECKOUT_HOOKS", {})},
}
```

Methods, zones, rates and pickup points are configured in the Django admin.
At checkout the client sends its choice in the orders `context`:

```json
{"delivery": {"method": "courier", "address": {"name": "Ada", "phone": "+1 555 0100",
  "line1": "1 Main St", "city": "Springfield", "postal_code": "62701", "country": "US"}}}
```

(`address_id` instead of `address` for a saved address; `pickup_point`
for a pickup method; nothing more for a digital one.)

**Delivery owns the delivery address.** `context.delivery` (`address` /
`address_id` / `pickup_point`) is the address the shipment is sent to; the
order keeps no second copy to reconcile. The shipping adjustment's `code`
is the method code (e.g. `courier`), which orders records as the order's
shipping method.

## Concepts

- **Zone** — where a rate applies: lists of countries, regions and
  postcode prefixes (empty list = any). The most specific matching zone
  wins (longest postcode prefix, then region, then country); a rate with no
  zone applies everywhere. No GIS.
- **Rate** — per method, zone and currency: a flat amount, free above a
  cart subtotal, and an optional price per kilogram used when every
  shippable line carries `attrs.weight_grams` (the purchasable resolver's
  extra field); otherwise the flat amount. Never converted between
  currencies.
- **Free shipping from a promotion** — an earlier adjuster's adjustment
  with `meta.free_shipping: true` (optionally `meta.free_shipping_methods`)
  makes shipping 0.00.
- **Address book** — per user, one default, at most `MAX_ADDRESSES`.
  Checkout and shipments keep a **copy** of the address; editing or
  deleting a saved address never changes a placed order. Guests type the
  address inline.
- **Shipment** — one per order: `pending → packed → shipped → delivered`,
  `returned`, `cancelled`, with a timeline, a tracking number and link. An
  order cancelled before the parcel left cancels its shipment.
- **Carriers** — `manual` (staff type the tracking number) by default;
  `mock` advances shipments by itself for demos (prototype posture only);
  a real carrier is a small `Carrier` subclass registered by slug.
- **GDPR** — erasure deletes the address book and blanks the recipient on
  shipments; money, status and city/country stay.
