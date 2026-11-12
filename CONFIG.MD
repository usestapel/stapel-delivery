# CONFIG.MD — stapel-delivery

Config registry for **stapel-delivery**. One row per configuration key the
module reads, its **source** (`env` = the process environment / the
`STAPEL_DELIVERY` settings dict), what it is for, whether it is required,
and its default.

Every key is read through `delivery_settings` (`stapel_delivery.conf`,
namespace `STAPEL_DELIVERY`). Resolution order per key:
`settings.STAPEL_DELIVERY` dict → a flat Django setting of the same name →
environment variable → the default below. `REQUIRE_METHOD` and
`DEFAULT_CARRIER` are CTO-facing config axes.

## stapel-delivery

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| REQUIRE_METHOD | env | axis: a checkout without `context.delivery` is refused with `error.400.delivery_method_required` (a cart where nothing ships is exempt); false = no shipping line, no shipment. | no | true |
| DEFAULT_CARRIER | env | axis: carrier of methods without their own: `manual` (staff), `mock` (auto-advancing; prototype stage only, E002/W002) or a registered slug; a dotted path only from the settings module. | no | manual |
| CARRIERS | settings | carrier registry {slug: "dotted.path.Carrier" or None} merged over the built-ins manual and mock; None removes one. Malformed is E001. | no | {} |
| MOCK_STEP_MINUTES | env | the mock carrier advances one status per this many minutes (beat pass). | no | 2 |
| MAX_ADDRESSES | env | saved addresses per user; over is `error.409.too_many_addresses`. | no | 20 |
| GEOCODE_FUNCTION | env | comm Function with the geo.geocode contract that fills missing coordinates of a saved address after commit (best-effort); "" = off; unreachable is W004. | no | "" |
| NOTIFY | env | best-effort buyer notification delivery.shipment_status_changed. | no | true |
| SHIPMENT_URL_TEMPLATE | env | `{shipment_id}` / `{number}` / `{order_id}` template for notification links; empty = no link. | no | "" |
| INTENT_TTL_HOURS | env | reserved/released checkout intents older than this are purged by the beat; also the window in which an `orders.order.placed` without an attempt key is matched to an intent. | no | 72 |
