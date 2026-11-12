"""Admin for stapel-delivery — where staff configure methods, zones, rates
and pickup points in 0.1.0.

Shipment snapshots and money are read-only; status moves only through the
service (transition actions), never a raw field edit, so every move is
checked by the FSM, recorded on the timeline and announced on the bus.
"""
from django.contrib import admin

from .models import (
    Address,
    DeliveryMethod,
    PickupPoint,
    Rate,
    Shipment,
    ShipmentEvent,
    ShipmentStatus,
    Zone,
)


def _transition_action(to_status: str):
    def action(modeladmin, request, queryset):
        from django.contrib import messages

        from . import fsm
        from .services import DeliveryError
        from .services.shipments import transition

        moved = refused = 0
        for shipment in queryset:
            try:
                transition(shipment.pk, to_status, actor=fsm.STAFF, note="admin")
                moved += 1
            except DeliveryError:
                refused += 1
        if moved:
            modeladmin.message_user(request, f"{moved} shipment(s) moved to {to_status}.")
        if refused:
            modeladmin.message_user(
                request, f"{refused} shipment(s) cannot move to {to_status}.", messages.WARNING
            )

    action.__name__ = f"mark_{to_status}"
    action.short_description = f"Mark selected shipments {to_status}"
    return action


class RateInline(admin.TabularInline):
    model = Rate
    extra = 0
    fields = ("zone", "currency", "amount", "free_above", "per_kg", "max_weight_kg", "enabled", "sort")


@admin.register(DeliveryMethod)
class DeliveryMethodAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "enabled", "sort", "carrier")
    list_filter = ("kind", "enabled")
    search_fields = ("code", "name")
    inlines = [RateInline]


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "method", "city", "country", "enabled")
    list_filter = ("method", "country", "enabled")
    search_fields = ("code", "name", "city")


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("user_id", "label", "city", "country", "is_default")
    search_fields = ("user_id", "city")
    readonly_fields = ("user_id", "created_at", "updated_at")


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 0
    can_delete = False
    fields = ("occurred_at", "from_status", "to_status", "actor", "note", "location")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("number", "order_id", "method_code", "carrier", "status", "tracking_number", "created_at")
    list_filter = ("status", "method_code", "carrier")
    search_fields = ("number", "order_id", "user_id", "tracking_number")
    readonly_fields = (
        "number", "order_id", "user_id", "method_code", "method_name", "method_kind", "carrier",
        "status", "recipient_name", "recipient_phone", "line1", "line2", "city", "region",
        "postal_code", "country", "pickup_point", "amount", "currency", "weight_kg", "lines",
        "shipped_at", "delivered_at", "created_at", "updated_at", "tracking_url",
    )
    inlines = [ShipmentEventInline]
    actions = [
        _transition_action(ShipmentStatus.PACKED),
        _transition_action(ShipmentStatus.SHIPPED),
        _transition_action(ShipmentStatus.DELIVERED),
        _transition_action(ShipmentStatus.CANCELLED),
    ]

    def has_add_permission(self, request):
        return False
