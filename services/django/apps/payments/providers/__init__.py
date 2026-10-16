from __future__ import annotations

from typing import Type

from .base import BasePaymentProvider
from .enot import EnotProvider
from .nowpayments import NowPaymentsProvider
from .rollypay import RollyPayProvider
from .stub import StubPaymentProvider

PAYMENT_PROVIDERS: dict[str, Type[BasePaymentProvider]] = {
    "nowpayments": NowPaymentsProvider,
    "rollypay": RollyPayProvider,
    "enot": EnotProvider,
    "stub": StubPaymentProvider,
}

# Providers that show in UI without real API credentials (checkout blocked).
STUB_PROVIDER_IDS: frozenset[str] = frozenset({"stub"})


def get_provider(name: str) -> BasePaymentProvider:
    key = (name or "").strip().lower()
    cls = PAYMENT_PROVIDERS.get(key)
    if not cls:
        raise ValueError(f"Unknown payment provider: {name}")
    return cls()
