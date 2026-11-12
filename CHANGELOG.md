# Changelog

All notable changes to stapel-delivery are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0 semver: **minor = breaking**, patch = compatible.

## [Unreleased]

## [0.1.0]

First release: delivery methods, rates, pickup points, an address book and
shipments with tracking, wired into the orders checkout by name.

### Added
- Error params declared: `delivery_method_unknown` / `delivery_unavailable`
  (`method`), `pickup_point_unknown` (`pickup_point`),
  `delivery_address_invalid` (`field`); an unknown carrier on the tracking
  endpoint is its own key `error.400.carrier_unknown` (`carrier`).
  `tests/test_error_params.py` requires every raise site's params to equal
  its template's placeholders.
- `GET staff/shipments/{id}/` (staff): one shipment with its timeline and
  `allowed_transitions`.
- `ShipmentResponse.allowed_transitions`: the statuses the caller may move
  the shipment to now (FSM table + role; empty for a buyer), so a staff UI
  never mirrors the state table.
- Explicit checkout hook order (`preset.py`): inventory 50 (stock first),
  promotions 100, delivery 200 — never a tie broken by name.
- README wiring snippets in the merge forms (the scaffold's
  `_stapel_merge_preset_defaults` list, or a per-key hand merge); pasting
  them never drops the host's `STAPEL_ORDERS` keys — executed against a
  populated settings module by `tests/test_readme_wiring.py`.
- **Catalog**: `DeliveryMethod` (courier / pickup / digital), `Zone`
  (country / region / postcode-prefix lists, most specific wins), `Rate`
  (flat, free above a subtotal, per kilogram from `attrs.weight_grams` with
  a flat fallback, weight cap; one currency, never converted),
  `PickupPoint` (address, coordinates, weekly hours). Admin for all of it.
- **Address book** `addresses/` (CRUD, one default under a constraint and a
  row lock, `MAX_ADDRESSES`), optional geocoding through a named Function.
- **Options** `POST options/` and `delivery.options`: every method with its
  price for a cart and a destination, or the reason it is not offered.
- **Orders adjuster** `delivery.quote` (`kind=shipping`, order 200):
  validates `context.delivery`, honours a promotion's `meta.free_shipping`,
  refuses with `error.<4xx>.*` keys; no personal data in `meta`.
- **Checkout hook** `delivery.reserve` / `commit` / `release`: the choice
  and the recipient snapshot are kept under the checkout attempt key; commit
  creates the order's shipment; only a `cancelled` release undoes a commit
  (cancels the shipment) — `checkout_failed` / `orphaned` on a committed
  intent answer ok and change nothing, and a commit after such a release
  still ships. Idempotent; reserve after release reserves anew.
- **Ownership by `actor_id`**: the hook payloads and `orders.order.placed`
  may carry `actor_id` (the acting account, a guest's own id too) next to
  `user_id` (null for a guest); intents and shipments are owned by it when
  present, so a guest's rows are found, merged and erased by the guest id;
  the lines-fingerprint fallback runs only for payloads without it. GDPR
  export includes the checkout intents.
- **Shipments**: one per order (unique), FSM pending → packed → shipped →
  delivered / returned / cancelled with a timeline, tracking number,
  carrier slug and URL; buyer `shipments/` (anchor-paginated, own rows
  only) and staff `staff/shipments/` (list, tracking, transition);
  `orders.order.placed` and `orders.order.status_changed` consumers.
- **Carriers**: registry with `manual` (default) and an auto-advancing
  `mock` (posture-gated, E002/W002); `Carrier` ABC for real carriers.
- Facts `delivery.shipment.created|status_changed`; notification
  `delivery.shipment_status_changed`; `delivery.shipment.status` Function.
- `preset.SETTINGS_DEFAULTS` registering the adjuster and the hook with
  orders; checks E001, E002/W002, W003, W004; GDPR owner; `user.merged`;
  beat (`poll_carriers`, `purge_intents`) and `delivery_housekeeping`.
