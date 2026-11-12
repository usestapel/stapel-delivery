"""A committed shipment in one call (fake orders caller)."""
from stapel_core.comm import call

from stapel_delivery.models import Shipment

from .factories import HOME, reserve_request


def make_shipment(user_id="1", order_id="1"):
    req = reserve_request(user_id=str(user_id), delivery={"method": "courier", "address": HOME})
    call("delivery.reserve", req)
    call("delivery.commit", {"attempt_key": req["attempt_key"], "token": None, "order_id": str(order_id),
                             "user_id": str(user_id)})
    return Shipment.objects.get(order_id=str(order_id))
