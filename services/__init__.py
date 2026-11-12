"""Service layer of stapel-delivery: rates, addresses, the orders seam, shipments.

Views and comm handlers call these; nothing here knows about HTTP. A
refusal is a :class:`DeliveryError` carrying the status, the error key, its
params and (for the orders seam) the request field it is about — the view
layer renders it as the fleet error envelope, the adjuster as an
``errors[]`` entry.
"""
from __future__ import annotations


class DeliveryError(Exception):
    """A domain refusal with its HTTP status and i18n error key."""

    def __init__(self, status: int, key: str, params: dict | None = None, field: str | None = None):
        self.status = status
        self.key = key
        self.params = params or {}
        self.field = field
        super().__init__(key)

    def as_contract_error(self) -> dict:
        """The orders contract shape: ``{"code", "field", "params"}``."""
        return {"code": self.key, "field": self.field, "params": dict(self.params)}


__all__ = ["DeliveryError"]
