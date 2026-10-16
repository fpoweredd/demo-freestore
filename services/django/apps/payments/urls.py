from django.urls import path

from .views import BalanceTopupInitAPIView, PaymentInitAPIView, WalletTransactionsAPIView

urlpatterns = [
    path("payments/init/", PaymentInitAPIView.as_view(), name="payment-init"),
    path(
        "payments/balance-topup/init/",
        BalanceTopupInitAPIView.as_view(),
        name="payment-balance-topup-init",
    ),
    path(
        "payments/wallet/transactions/",
        WalletTransactionsAPIView.as_view(),
        name="payment-wallet-transactions",
    ),
]
