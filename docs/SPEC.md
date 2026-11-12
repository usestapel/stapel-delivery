# SPEC — stapel-delivery 0.1.0

Status: **built locally, waiting to go public** (brigade DL, brick wave
2026-11-12). Queue: the `stapel-delivery` row of
`SPEC-BRICKS-WAVE-2026-11-12.md` §1. Consumers: this repo's tests (every
decision below has a named test), `MODULE.md`, the react pair brief. House
style: `SPEC-STAPEL-ORDERS.md` applies verbatim. No client names.

## 1. Scope boundary

| Decision | Reason |
|---|---|
| **In:** delivery methods (`courier` / `pickup` / `digital`), zones, rates, pickup points, a per-user address book, the orders shipping adjuster, shipments with an FSM, tracking number + carrier slug + tracking URL, a carrier strategy registry. | The wave row. |
| **Zones are matched by country / region / postcode prefix only.** No polygons, no distance pricing, no GIS dependency. | Covers "Moscow region costs more, the rest of the country is flat" and "this postcode area is free"; a polygon needs PostGIS and a map editor — a product, not a brick. |
| **Money is Decimal, strings on the wire, one currency per rate, never converted.** A rate in another currency than the cart does not apply. | The orders canon: a converted price is a quote that drifts. |
| **Address snapshots, never a foreign key.** Checkout and shipments copy the address; editing or deleting a book entry never changes a placed order. | The orders canon; GDPR erasure of the book must not reach into the shipment's economics. |
| **One shipment per order** (unique `order_id`). Split parcels are out of v1. | At-least-once delivery of `orders.order.placed` must be idempotent by construction; a split needs a lines-to-parcel UI first. |
| **No real carrier ships.** `manual` (staff types the tracking number) is the default; `mock` (auto-advancing, posture-gated) is for demos; a documented ABC is the seam. | Carrier credentials and hosts are per-client; a brick must not carry any. |
| **Config (methods, zones, rates, pickup points) is edited in the Django admin in 0.1.0.** The HTTP surface is buyer + staff shipment operations. | A staff config API with its pair is the next slice once a client asks for it. |
| **Out:** returns management (RMA), label printing, customs, cash-on-delivery accounting, delivery slots/time windows, multi-parcel, carrier webhooks (the seam `apply_carrier_update` exists; the view is host code). | Each is a product decision; none is needed for "methods and prices, pickup points, track my parcel, saved addresses". |

## 2. Models

All user references are `user_id CharField(64)` (pseudonymizable), never FKs.

- **`Zone`** — `code` (slug ≤32, unique), `name` ≤120, `countries`
  (ISO-3166 alpha-2 list; empty = any), `regions` (list, compared
  case-insensitively; empty = any), `postcode_prefixes` (list, compared
  without spaces, case-insensitively; empty = any). An address matches when
  every non-empty list matches. **Specificity** decides between two matching
  zones: longest matched postcode prefix, then "has regions", then "has
  countries", then the rate's `sort`, then id. A rate without a zone matches
  everything and is the least specific.
- **`DeliveryMethod`** — `code` (slug ≤32, unique), `name` ≤120,
  `description` ≤500, `kind` (`courier` / `pickup` / `digital`), `enabled`,
  `sort`, `carrier` (slug ≤32, blank = `DEFAULT_CARRIER`),
  `tracking_url_template` ≤500 (`{tracking_number}`, `{number}`; blank = the
  carrier's), `eta_min_days` / `eta_max_days` (nullable).
- **`Rate`** — `method` FK, `zone` FK nullable (null = everywhere),
  `currency` (3), `amount` Decimal(12,2) (flat), `free_above` Decimal(12,2)
  nullable (cart `subtotal >= free_above` → 0), `per_kg` Decimal(12,2)
  nullable, `max_weight_kg` Decimal(10,3) nullable, `enabled`, `sort`.
- **`PickupPoint`** — `method` FK (kind `pickup`), `code` (≤64, unique),
  `name`, address fields, `latitude` / `longitude` Decimal(9,6) nullable,
  `hours` (weekly windows `[{weekday 0-6, opens HH:MM, closes HH:MM}]`),
  `hours_note` ≤200, `enabled`, `sort`.
- **`Address`** — `user_id`, `label` ≤60, recipient `name` ≤120, `phone` ≤32,
  `line1`/`line2` ≤200, `city` ≤100, `region` ≤100, `postal_code` ≤20,
  `country` (2, upper-case ISO), `latitude`/`longitude` nullable,
  `is_default` (at most one per user: conditional unique constraint, and the
  flag moves under `select_for_update` on the user's rows). At most
  `MAX_ADDRESSES` per user.
- **`DeliveryIntent`** (`@access.ops`) — what the buyer chose at checkout,
  keyed on the orders checkout `attempt_key` (unique): `user_id`, method
  code/kind/carrier, recipient snapshot (JSON), pickup point snapshot (JSON),
  `amount`/`currency`, `weight_kg`, `lines_fingerprint`, `order_id`, `status`
  (`reserved` → `committed` | `released`).
- **`Shipment`** (`@access.standard`) — `number` (`YYYYMMDD-XXXXXX`, unique,
  never the pk), `order_id` (unique), `user_id`, method code/name/kind,
  `carrier`, `status`, `tracking_number` ≤64, `tracking_url` ≤500, recipient
  snapshot fields (name, phone, line1, line2, city, region, postal_code,
  country), `pickup_point` snapshot (JSON: code, name, address), `amount` /
  `currency` (the shipping charged), `weight_kg`, `lines` (JSON:
  purchasable type/key/quantity from the placed event), `shipped_at`,
  `delivered_at`, timestamps.
- **`ShipmentEvent`** — `shipment` FK, `from_status`, `to_status`, `actor`
  (`staff` / `carrier` / `system`), `note` ≤200, `location` ≤120,
  `occurred_at`. The buyer's tracking timeline.

## 3. Shipment FSM

```
pending → packed → shipped → delivered
pending → shipped                       (a manual carrier may skip packing)
shipped → returned,  delivered → returned
pending | packed → cancelled
```

`delivered`, `returned` (from delivered: terminal), `cancelled` are terminal;
`returned` is reachable from `shipped` (refused at the door) and from
`delivered` (sent back). Actors: `staff` and `carrier` may take any edge of
the table; `system` (an order cancelled through orders) only
`pending|packed → cancelled`. An illegal edge is
`error.409.shipment_transition_invalid`. `fsm.TRANSITIONS` is the table; the
test walks every pair of statuses (inversion: every edge not in the table is
refused).

## 4. Rate model (one function: `services/rates.py:price_for`)

For one method and one destination (the address, or the pickup point's
address; `digital` has none):

1. Candidate rates = enabled rates of the method in the cart currency whose
   zone matches (or is null). None → the method is not offered
   (`error.409.delivery_unavailable`). `digital` without any rate costs 0.
2. The most specific candidate wins (§2).
3. Weight: lines whose `attrs.shippable` is `false` are ignored. When every
   remaining line has `attrs.weight_grams` (integer grams — the purchasable
   resolver's extra field that orders snapshots on the cart line,
   CONTRACT-DELTAS 2), `weight = Σ grams × quantity / 1000` kg; otherwise
   the weight is unknown.
4. Price: `per_kg` set **and** the weight known → `amount + per_kg × weight`
   (`meta.weight_basis = "weight"`); otherwise `amount`
   (`"flat"`, or `"flat_fallback"` when `per_kg` is set but a weight is
   missing). `max_weight_kg` set and a known weight above it → not offered.
5. Free: `free_above` set and `subtotal >= free_above` → 0
   (`meta.free_reason = "threshold"`); a **free-shipping marker** in
   `adjustments_so_far` → 0 (`meta.free_reason = "promotion"`).
6. Quantize `ROUND_HALF_UP` to 2 dp; a price at or above `10^10` is not
   offered (the column bound; `tests/test_money_bounds.py`).

**Free-shipping marker** (the contract with `stapel-promotions`): any entry
of `adjustments_so_far` with `meta.free_shipping == true`. An optional
`meta.free_shipping_methods: [code, ...]` limits it to those methods. The
marker's own amount is the promotion's business (typically `"0.00"`).

A cart in which every line is `attrs.shippable == false` needs no delivery:
the adjuster answers no adjustment and no error, and no shipment is created.

## 5. The orders seam (contract §2 of the wave spec)

`delivery.quote` (adjuster, `kind=shipping`, order 200) reads
`context.delivery`:

```json
{"method": "<code>",
 "address": {"name", "phone", "line1", "line2"?, "city", "region"?, "postal_code"?, "country"},
 "address_id": 12,
 "pickup_point": "<code>"}
```

`courier` needs `address` or `address_id` (an entry of the request's
`user_id`; a foreign or absent id is `error.404.address_not_found`);
`pickup` needs `pickup_point` of that method; `digital` needs nothing. No
`delivery` key: `REQUIRE_METHOD` (default true) answers
`error.400.delivery_method_required` (field `delivery.method`); false
answers no adjustment. Response: one adjustment
`{"kind": "shipping", "code": "<method code>", "label": "<method name>",
"amount": "<price>", "line_index": null, "meta": {method, kind, carrier,
zone, weight_basis, free_reason?, pickup_point?}}` — a free delivery still
answers `"0.00"` so the order records the method.

**Address authority.** Delivery is authoritative for the delivery address:
`context.delivery.address` / `address_id` / `pickup_point` is what the
shipment is sent to (snapshotted on the intent at reserve, copied to the
shipment at commit). The shipping adjustment's `code` is the method code
(≤ 32, non-personal), which orders copies into `Order.shipping_method`.

The request follows orders' CONTRACT-DELTAS: `user_id` is null for a guest
(a guest has no book, so the address must be inline; `address_id` reads the
book of `user_id` only), `adjustments_so_far`
items carry `"adjuster"`, an adjustment `code` is ≤64 and `meta` is kept
past GDPR erasure — so `meta` never carries the address.

Checkout hooks `delivery.reserve` / `.commit` / `.release` (entry order 200):

- **reserve** (adjuster request + `attempt_key`) re-validates the choice
  exactly like quote and writes a `DeliveryIntent` keyed on `attempt_key`
  (a replay updates it while `reserved`) → `{"ok", "token", "errors"}`.
  The intent carries the recipient snapshot: that is how the address
  reaches the shipment without riding the bus.
- **commit** `{attempt_key, token|null, order_id, user_id|null}` (after the
  order transaction commits, retried by orders until `ok`) marks the intent
  committed and creates the shipment → `{"ok": true}`. A commit after a
  `checkout_failed` / `orphaned` release still ships (the placed order is
  the fact); after a `cancelled` release it is a no-op.
- **release** `{attempt_key, token|null, order_id|null, reason}`: on a
  reserved intent any reason releases it (a later reserve on the same key
  reserves anew; the reason is recorded, and a later `cancelled` overwrites
  an earlier one). **Only `cancelled` undoes a commit:** it cancels a
  `pending`/`packed` shipment (actor `system`); `checkout_failed` /
  `orphaned` on a committed intent is a no-op answering `{"ok": true}`. All
  three act on `attempt_key` alone (the token is a convenience) and are
  idempotent. `tests/test_release_semantics.py` is the full (state, event)
  table.

**Ownership (`actor_id`).** Orders sends `actor_id` — the acting account
id, a guest's own id included, always present — next to `user_id` (null for
a guest on every payload, commit and `orders.order.placed` included).
Intents and shipments are owned by `actor_id` when the payload has it
(stored in their `user_id` column, so the buyer's `shipments/`,
`user.merged` and GDPR export/erase find a guest's rows by the guest id);
payloads without it fall back to `user_id` (and, at commit/placed, fill a
blank owner from it).

`orders.order.placed` → one shipment per order (a fallback for the commit
hook, and the source of the order lines; of the buyer id for a guest when
the payload predates `actor_id`).
The intent is found by, in order: `attempt_key` in the event (if orders adds it), the intent a commit
already linked to that `order_id`, then the oldest `reserved` intent of the
same `user_id` whose **lines fingerprint** (currency + sorted
`(type, key, quantity, unit_price)`) equals the event's (a guest intent has
a blank user and matches any user with the same fingerprint). The
fingerprint step runs only for events without `actor_id`: an orders that
names the actor also sends `attempt_key`. No intent → no
shipment, logged at INFO (an order placed without delivery). A `digital`
intent or an all-unshippable cart creates no shipment.
`orders.order.status_changed` to `cancelled` cancels a `pending`/`packed`
shipment of that order.

## 6. Carriers (`carriers.py`)

`Carrier` ABC: `slug`, `register(shipment) -> Registration | None` (called
once at creation: tracking number / URL a carrier assigns), `poll(shipment)
-> list[CarrierUpdate]` (called by the beat for active shipments),
`tracking_url(shipment) -> str`. Built-ins: `manual` (no-ops; staff sets the
tracking number) and `mock` (assigns `MOCK-<number>`, advances one step per
`MOCK_STEP_MINUTES`: pending → packed → shipped → delivered). Registry
`CARRIERS` merges over built-ins (dotted path or `None` to remove);
`DEFAULT_CARRIER` is a resolver key, env may pick a registered short name.
**Posture:** any use of `mock` (the default carrier or a method's carrier)
is `stapel_delivery.E002` outside the prototype posture stage and `W002`
inside it — the mock is derived from the posture, never a `USE_MOCK_*`
switch. A real carrier's webhook view calls
`services.shipments.apply_carrier_update(shipment, update)`.

## 7. API (`/delivery/api/v1/`, plain paths, `StapelAPIView`)

| Method/path | Who | Request → Response |
|---|---|---|
| `GET methods/` | anyone | → `DeliveryMethodList {items: [DeliveryMethodResponse]}` (enabled, by sort) |
| `POST options/` | anyone | `DeliveryOptionsRequest {currency, subtotal, lines, address?, address_id?, adjustments_so_far?}` → `DeliveryOptionsResponse {options: [DeliveryOption]}` |
| `GET pickup-points/` | anyone | `?method=&country=&city=` + anchor → `PickupPointPage` |
| `GET/POST addresses/` | a real account (guest 403), own rows | → `AddressList` / `AddressRequest` → `201 AddressResponse` |
| `GET/PATCH/DELETE addresses/{id}/` | own rows (foreign = 404) | `PatchedAddressRequest` → `AddressResponse` / 204 |
| `POST addresses/{id}/default/` | own rows | → `AddressResponse` |
| `GET shipments/` | own rows | `?status=&order_id=` + anchor → `ShipmentPage` |
| `GET shipments/{id}/` | own rows | → `ShipmentResponse` (with `events`) |
| `GET staff/shipments/` | staff | `?status=&order_id=` + anchor → `ShipmentPage` |
| `GET staff/shipments/{id}/` | staff | → `ShipmentResponse` (with `allowed_transitions`) |
| `POST staff/shipments/{id}/transition/` | staff | `ShipmentTransitionRequest {to, note?, location?}` → `ShipmentResponse` |
| `POST staff/shipments/{id}/tracking/` | staff | `ShipmentTrackingRequest {tracking_number, carrier?}` → `ShipmentResponse` |

Field lengths are the orders canon (name 120, phone 32, line1/line2 200,
city 100, region 100, postal_code 20, country 2).

## 8. Settings (`STAPEL_DELIVERY`, registry in CONFIG.MD)

`REQUIRE_METHOD` (True), `DEFAULT_CARRIER` ("manual", resolver + env_enum),
`CARRIERS` ({} merge), `MOCK_STEP_MINUTES` (2), `MAX_ADDRESSES` (20),
`GEOCODE_FUNCTION` ("" = off; e.g. `geo.geocode` fills missing coordinates
of a saved address, best-effort), `NOTIFY` (True), `SHIPMENT_URL_TEMPLATE`
(""), `INTENT_TTL_HOURS` (72).

`preset.SETTINGS_DEFAULTS` registers the adjuster and the hooks with orders.

## 9. Functions, facts, consumers

Functions: `delivery.options`, `delivery.quote`, `delivery.reserve`,
`delivery.commit`, `delivery.release`, `delivery.shipment.status`. Emits:
`delivery.shipment.created`, `delivery.shipment.status_changed` (inside
`mutate_and_emit`, key = shipment id, no recipient fields). Consumes:
`orders.order.placed`, `orders.order.status_changed`, `user.merged`.
Notification `delivery.shipment_status_changed` to the buyer (best-effort,
`NOTIFY`).

## 10. GDPR

`register_gdpr_owner("delivery", ["account"], erase)`: the address book and
intents are deleted; shipments keep method, status, money, lines, city and
country, while `user_id` becomes the fleet pseudonym and the recipient
name/phone/lines/postcode/region are blanked. Export = addresses +
shipments with their recipient snapshot.

## 11. Checks

E001 malformed `CARRIERS`/unknown `DEFAULT_CARRIER`; E002/W002 mock by
posture; W003 orders is installed but `STAPEL_ORDERS["ADJUSTERS"]` does not
name `delivery.quote` (shipping would be free); W004 `GEOCODE_FUNCTION` set
but unreachable. Without orders installed nothing fires.
