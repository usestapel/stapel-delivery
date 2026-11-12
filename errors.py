"""i18n error keys of stapel-delivery.

Only ``error.<status>.<slug>`` keys leave this package — human-readable
strings are translations, never literals in responses. The orders adjuster
and checkout hooks answer the same keys in their ``errors[].code``.
"""
from stapel_core.django.api.errors import register_service_errors

ERR_400_DELIVERY_METHOD_REQUIRED = "error.400.delivery_method_required"
ERR_400_DELIVERY_METHOD_UNKNOWN = "error.400.delivery_method_unknown"
ERR_400_DELIVERY_ADDRESS_REQUIRED = "error.400.delivery_address_required"
ERR_400_DELIVERY_ADDRESS_INVALID = "error.400.delivery_address_invalid"
ERR_400_PICKUP_POINT_REQUIRED = "error.400.pickup_point_required"
ERR_400_PICKUP_POINT_UNKNOWN = "error.400.pickup_point_unknown"
ERR_404_ADDRESS_NOT_FOUND = "error.404.address_not_found"
ERR_404_SHIPMENT_NOT_FOUND = "error.404.shipment_not_found"
ERR_409_DELIVERY_UNAVAILABLE = "error.409.delivery_unavailable"
ERR_409_SHIPMENT_TRANSITION_INVALID = "error.409.shipment_transition_invalid"
ERR_409_TOO_MANY_ADDRESSES = "error.409.too_many_addresses"

STAPEL_DELIVERY_ERRORS = {
    ERR_400_DELIVERY_METHOD_REQUIRED: "Choose a delivery method",
    ERR_400_DELIVERY_METHOD_UNKNOWN: "This delivery method is not available",
    ERR_400_DELIVERY_ADDRESS_REQUIRED: "Enter a delivery address",
    ERR_400_DELIVERY_ADDRESS_INVALID: "Check the delivery address",
    ERR_400_PICKUP_POINT_REQUIRED: "Choose a pickup point",
    ERR_400_PICKUP_POINT_UNKNOWN: "This pickup point is not available",
    ERR_404_ADDRESS_NOT_FOUND: "Address not found",
    ERR_404_SHIPMENT_NOT_FOUND: "Shipment not found",
    ERR_409_DELIVERY_UNAVAILABLE: "This delivery method does not deliver to this address",
    ERR_409_SHIPMENT_TRANSITION_INVALID: "The shipment cannot move from {from} to {to}",
    ERR_409_TOO_MANY_ADDRESSES: "You can save at most {max} addresses",
}

STAPEL_DELIVERY_REMEDIATION = {
    ERR_409_DELIVERY_UNAVAILABLE: "fix_input",
}

register_service_errors(STAPEL_DELIVERY_ERRORS, remediation=STAPEL_DELIVERY_REMEDIATION)

__all__ = [
    "STAPEL_DELIVERY_ERRORS",
    "ERR_400_DELIVERY_METHOD_REQUIRED",
    "ERR_400_DELIVERY_METHOD_UNKNOWN",
    "ERR_400_DELIVERY_ADDRESS_REQUIRED",
    "ERR_400_DELIVERY_ADDRESS_INVALID",
    "ERR_400_PICKUP_POINT_REQUIRED",
    "ERR_400_PICKUP_POINT_UNKNOWN",
    "ERR_404_ADDRESS_NOT_FOUND",
    "ERR_404_SHIPMENT_NOT_FOUND",
    "ERR_409_DELIVERY_UNAVAILABLE",
    "ERR_409_SHIPMENT_TRANSITION_INVALID",
    "ERR_409_TOO_MANY_ADDRESSES",
]
