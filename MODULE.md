# stapel-delivery — MODULE.md

> Agent-facing map of this module: what it provides, where to extend it
> without forking, and what not to do. Kept in the same change as any edit
> to a seam. See also README.md, CHANGELOG.md and docs/SPEC.md.

## What this module provides

- **Catalog** (configured in the Django admin): `DeliveryMethod`
  (`courier` / `pickup` / `digital`, enabled, sort, carrier, tracking URL
  template, ETA), `Zone` (country / region / postcode-prefix lists, no GIS),
  `Rate` (per method × zone × currency: flat, `free_above`, `per_kg`,
  `max_weight_kg`), `PickupPoint` (address, coordinates, weekly hours).
- **Pricing** in one function, `services/rates.py:price_for` — options, the
  adjuster and the checkout hook all call it.
- **Address book** per user (`Address`, one default, `MAX_ADDRESSES`), and
  snapshot semantics: checkout intents and shipments copy the address.
- **The orders seam** (`services/checkout.py`): adjuster `delivery.quote`,
  checkout hook `delivery.reserve/commit/release`, consumers of
  `orders.order.placed` / `orders.order.status_changed`. Orders is never
  imported.
- **Shipments** (`Shipment` + `ShipmentEvent` timeline) with a table FSM
  (`fsm.py`), tracking number / carrier / URL, buyer "my shipments", staff
  operations, facts `delivery.shipment.created|status_changed`.
- API under `/delivery/api/v1/`.

## Extension points (fork-free)

### Settings — `STAPEL_DELIVERY` namespace (`conf.py`, registry in CONFIG.MD)

| Key | Default | What it customizes |
|---|---|---|
| `REQUIRE_METHOD` | `True` | Axis. Missing `context.delivery` → `error.400.delivery_method_required`. |
| `DEFAULT_CARRIER` | `"manual"` | Axis. REPLACE strategy: slug or dotted path; env may set slugs only. |
| `CARRIERS` | `{}` | MERGE registry `{slug: dotted path | None}` over `manual`, `mock`. |
| `MOCK_STEP_MINUTES` | `2` | Mock carrier pace. |
| `MAX_ADDRESSES` | `20` | Address book cap (409 over). |
| `GEOCODE_FUNCTION` | `""` | Function name with the `geo.geocode` contract; off when empty. |
| `NOTIFY` | `True` | Buyer notification on every shipment move. |
| `SHIPMENT_URL_TEMPLATE` | `""` | Link in notifications. |
| `INTENT_TTL_HOURS` | `72` | Intent purge and the placed-fact matching window. |

### Wiring into orders (`preset.py`)

`preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]` registers the adjuster
(`{"delivery": {"quote": "delivery.quote", "order": 200}}`) and the hook
(`{"delivery": {"reserve", "commit", "release", "order": 200}}`). The
stapel-tools scaffold merges presets of composites only today, so a host
pastes it (check `stapel_delivery.W003` fires when orders is installed and
the fragment is missing).

### The checkout context (what a client sends to orders)

`context.delivery = {"method": code, "address": {...} | "address_id": id |
"pickup_point": code}`. A guest (`user_id` null) must send the address
inline (`address_id` reads the book of `user_id` only).

Ownership: the payloads' `actor_id` (the acting account, a guest's own id
too) owns intents and shipments when present; without it, `user_id`. A
guest's shipments are therefore listed, merged (`user.merged`) and
exported/erased by the guest id. Validation is `AddressSnapshotSerializer` (the same rules as the
book). Errors come back as `{"code": "error.<4xx>.<slug>", "field":
"delivery.<…>", "params"}`.

### Weight and free shipping

- Weight: cart line `attrs.weight_grams` (integer grams — the purchasable
  resolver's extra field, which orders snapshots on the cart line). Every
  shippable line needs it for a per-kg price; otherwise flat. A line with
  `attrs.shippable: false` is ignored; a cart of only such lines needs no
  delivery.
- Free shipping from a promotion: an earlier adjustment with
  `meta.free_shipping: true` (optionally `meta.free_shipping_methods:
  [codes]`).

### Carriers (`carriers.py`)

```python
from stapel_delivery.carriers import Carrier, Registration, CarrierUpdate, register_carrier

class AcmeCarrier(Carrier):
    def register(self, shipment):          # in the creation transaction
        return Registration(tracking_number=book_parcel(shipment))
    def poll(self, shipment, now):          # beat, active shipments
        return [CarrierUpdate(status="shipped", occurred_at=now, location="Hub")]
    def tracking_url(self, shipment):
        return f"https://acme.example/t/{shipment.tracking_number}"

register_carrier("acme", AcmeCarrier)       # or STAPEL_DELIVERY["CARRIERS"]
```

A push-style carrier's webhook view (host code) calls
`services.shipments.apply_carrier_update(shipment, update)`; illegal or
stale updates are logged and skipped. No real carrier ships here.

### Serializer seams and presenters (`views.py`, `presenters.py`)

Views inherit `StapelAPIView`. Presentation swaps via `STAPEL_SWAP`
`STAPEL_DELIVERY_{ADDRESS,METHOD,OPTIONS,PICKUP_POINT,SHIPMENT}_PRESENTER`.

| View | Guest stance | Request | Response |
|---|---|---|---|
| `MethodListView` | allowed (AllowAny) | — | `DeliveryMethodListSerializer` |
| `OptionsView` (POST) | allowed | `DeliveryOptionsRequestSerializer` | `DeliveryOptionsResponseSerializer` |
| `PickupPointListView` | allowed | — | `PickupPointPage` |
| `AddressListView`, `AddressDetailView`, `AddressDefaultView` | allowed (guest session keeps a book), `user_id == me`, foreign = 404 | `AddressRequestSerializer` | `AddressResponseSerializer` / `AddressListSerializer` |
| `ShipmentListView`, `ShipmentDetailView` | allowed, `user_id == me`, no staff bypass | — | `ShipmentPage` / `ShipmentResponseSerializer` |
| `StaffShipmentListView`, `StaffShipmentTrackingView`, `StaffShipmentTransitionView` | denied, `IsStaffUser` | `ShipmentTrackingRequestSerializer` / `ShipmentTransitionRequestSerializer` | `ShipmentPage` / `ShipmentResponseSerializer` |

### Events & functions (comm surface)

| Kind | Name | Payload | Schema |
|---|---|---|---|
| Function | `delivery.options` | cart + destination → `{options}` | `schemas/functions/delivery.options.json` |
| Function | `delivery.quote` | orders adjuster request → `{adjustments, errors}` | `schemas/functions/delivery.quote.json` |
| Function | `delivery.reserve` | adjuster request + `attempt_key` → `{ok, token, errors}` | `schemas/functions/delivery.reserve.json` |
| Function | `delivery.commit` | `{attempt_key, token, order_id, user_id}` → `{ok}` | `schemas/functions/delivery.commit.json` |
| Function | `delivery.release` | `{attempt_key, token, order_id, reason}` → `{ok}` | `schemas/functions/delivery.release.json` |
| Function | `delivery.shipment.status` | `{order_id}` or `{shipment_id}` → status + tracking | `schemas/functions/delivery.shipment.status.json` |
| Emits | `delivery.shipment.created` | ids, method, carrier, amount — no recipient | `schemas/emits/delivery.shipment.created.json` |
| Emits | `delivery.shipment.status_changed` | `{shipment_id, order_id, user_id, from, to, actor, tracking_number, …}` | `schemas/emits/delivery.shipment.status_changed.json` |
| Consumes | `orders.order.placed` | creates the shipment (fallback to commit) | `schemas/consumes/orders.order.placed.json` |
| Consumes | `orders.order.status_changed` | `to == cancelled` cancels a pending/packed shipment | `schemas/consumes/orders.order.status_changed.json` |
| Consumes | `user.merged` | book, shipments, intents follow the guest | `schemas/consumes/user.merged.json` |

Notification type: `delivery.shipment_status_changed` (best-effort, `NOTIFY`).

### System checks

E001 carriers malformed / unknown default; E002/W002 mock outside/inside
the prototype stage (method-level under the `database` tag); W003 orders
installed without the preset fragment; W004 geocoder unreachable.

### GDPR

`register_gdpr_owner("delivery", ["account"], erase_subject)`: book and
intents deleted; shipments pseudonymized (recipient blanked, city/country
and money kept). Export = addresses + shipments.

## Anti-patterns

- **Don't import `stapel_orders`, `stapel_geo`, `stapel_promotions`** — names
  in settings and comm only (`tests/test_architecture.py`).
- **Don't put the address in adjustment `meta`** — orders keeps meta past
  GDPR erasure. The snapshot lives in `DeliveryIntent` / `Shipment`.
- **Don't edit a shipment's status field directly** — `services.shipments.transition`
  checks the FSM, writes the timeline and emits the fact.
- **Don't reference `Address` from anything that outlives an edit** — copy it.
- **Don't fork to change behavior** — every knob above is a seam.

## App-layer override vs upstream contribution — rule of thumb

**App-layer** (host project, no fork): a settings key, a carrier class, a
presenter swap, a comm subscriber to `delivery.shipment.*`.

**Upstream** if it needs new model fields/migrations, new endpoints, a new
settings key or seam, or changes a committed schema.
