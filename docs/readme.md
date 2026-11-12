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

# settings.py — wire delivery into the orders checkout (merge per key)
from stapel_delivery import preset
STAPEL_ORDERS = {
    "ADJUSTERS": {**preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]["ADJUSTERS"]},
    "CHECKOUT_HOOKS": {**preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]["CHECKOUT_HOOKS"]},
}

# carrier polling + intent purge (Celery optional: manage.py delivery_housekeeping)
from stapel_delivery.beat import get_delivery_beat_schedule
CELERY_BEAT_SCHEDULE = {**get_delivery_beat_schedule()}
```

Methods, zones, rates and pickup points are configured in the Django admin.
At checkout the client sends its choice in the orders `context`:

```json
{"delivery": {"method": "courier", "address": {"name": "Ada", "phone": "+1 555 0100",
  "line1": "1 Main St", "city": "Springfield", "postal_code": "62701", "country": "US"}}}
```

(`address_id` instead of `address` for a saved address; `pickup_point`
for a pickup method; nothing more for a digital one.)

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
