"""Business flows of stapel-delivery (stapel_core.flows).

The Flow objects live here; HTTP steps are attached in ``views.py`` with
``@flow_step``. Literals are the canonical English source texts; i18n keys
are derived (``flow.<id>.title`` / ``.step.<order>.note``).
"""
from stapel_core.flows import Flow

CHOOSE = Flow(
    "delivery.choose",
    title="Choose how an order is delivered",
    description=(
        "At checkout the buyer picks a saved address (or types one), sees the "
        "delivery methods with their prices for this cart, and picks one or a "
        "pickup point. Orders asks the delivery.quote adjuster for the shipping "
        "line and the delivery checkout hook keeps the address for the shipment."
    ),
    actors=["Buyer (guests type the address inline)"],
)
CHOOSE.human(order=0, note="The buyer opens checkout with a cart")
CHOOSE.action("orders.order.placed", order=5, note="The order is placed; its shipment is created")

ADDRESSES = Flow(
    "delivery.addresses",
    title="Keep an address book",
    description="The buyer saves, edits, removes addresses and picks the default one.",
    actors=["Buyer"],
)

TRACK = Flow(
    "delivery.track",
    title="Track my parcel",
    description=(
        "The buyer pages through their shipments and opens one to see its "
        "status, tracking number and link, and the timeline of steps."
    ),
    actors=["Buyer"],
)
TRACK.action("delivery.shipment.status_changed", order=0, note="A step is announced to the buyer")

FULFIL = Flow(
    "delivery.fulfil",
    title="Ship orders",
    description=(
        "Staff work through pending shipments, record the carrier's tracking "
        "number, and move each one to packed, shipped and delivered (or "
        "cancelled / returned). A polling carrier advances them by itself."
    ),
    actors=["Staff", "Carrier"],
)
FULFIL.action("delivery.shipment.status_changed", order=4, note="Every status move is announced")
