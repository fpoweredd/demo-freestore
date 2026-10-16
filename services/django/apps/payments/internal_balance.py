"""Wallet-backed internal balance rail for checkout and account history."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import WalletTransaction

# Identifier for checkout / future use (not an external PaymentProviderSettings row).
INTERNAL_BALANCE_PROVIDER_ID = "site_balance"


def internal_balance_channel_info(*, balance: Decimal) -> dict[str, Any]:
    """Flags for internal wallet rail at checkout (top-up remains external PSP only)."""
    return {
        "id": INTERNAL_BALANCE_PROVIDER_ID,
        "available": balance > 0,
    }

def get_wallet_transactions(*, user_id: int, limit: int = 50) -> list[WalletTransaction]:
    return list(
        WalletTransaction.objects.filter(user_id=user_id)
        .order_by("-created_at")
        .only(
            "id",
            "kind",
            "amount",
            "currency",
            "description",
            "created_at",
            "balance_before",
            "balance_after",
            "metadata",
        )[:limit]
    )
