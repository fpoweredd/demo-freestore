from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.catalog.models import Category, DigitalItem, Product, ProductAttribute, ProductCard, ProductInputField


def _d(value: str | int | float) -> Decimal:
    return Decimal(str(value))


DATASET = {
    "categories": [
        {"name": "Games", "slug": "games", "icon": "gamepad"},
        {"name": "Subscriptions", "slug": "subscriptions", "icon": "star"},
        {"name": "Game Keys", "slug": "game-keys", "icon": "key"},
        {"name": "Game Accounts", "slug": "game-accounts", "icon": "controller"},
        {"name": "Service Accounts", "slug": "service-accounts", "icon": "account"},
        {"name": "Top Up", "slug": "top-up", "icon": "wallet"},
    ],
    "cards": [
        {
            "category": "top-up",
            "name": "Apple & iTunes Gift Card",
            "slug": "apple-itunes-gift-card",
            "description": "Gift cards with multiple regions and nominals for Apple ID balance top-up.",
            "fulfillment_mode": "instant",
            "is_featured": True,
            "is_hidden": False,
            "attributes": [
                ("delivery", "instant"),
                ("platform", "Apple"),
                ("product_type", "gift_card"),
            ],
            "products": [
                {"price": "458", "old_price": "635", "stock": 25, "attrs": {"region": "USA", "nominal": "5 USD", "platform": "Apple"}},
                {"price": "911", "old_price": "1177", "stock": 22, "attrs": {"region": "Turkey", "nominal": "10 USD", "platform": "Apple"}},
                {"price": "1760", "old_price": "2040", "stock": 18, "attrs": {"region": "USA", "nominal": "20 USD", "platform": "Apple"}},
                {"price": "2866", "old_price": "3452", "stock": 12, "attrs": {"region": "Turkey", "nominal": "700 TRY", "platform": "Apple"}},
            ],
            "default_index": 0,
        },
        {
            "category": "top-up",
            "name": "Steam Wallet Top Up",
            "slug": "steam-wallet-top-up",
            "description": "Manual top-up service where user enters account details and custom amount.",
            "fulfillment_mode": "manual",
            "is_featured": True,
            "is_hidden": False,
            "attributes": [
                ("delivery", "manual"),
                ("platform", "Steam"),
                ("product_type", "wallet_top_up"),
            ],
            "input_fields": [
                {"key": "steam_login", "label": "Steam login", "field_type": "text", "required": True, "placeholder": "your_login"},
                {"key": "steam_password", "label": "Steam password", "field_type": "password", "required": True},
                {
                    "key": "amount",
                    "label": "Top-up amount",
                    "field_type": "number",
                    "required": True,
                    "min_value": "5",
                    "max_value": "1000",
                    "help_text": "Amount in USD equivalent.",
                },
                {"key": "note", "label": "Additional note", "field_type": "textarea", "required": False},
            ],
            "products": [
                {"price": "100", "old_price": None, "stock": 9999, "attrs": {"region": "Global", "currency": "USD", "fee": "service_fee_only"}},
            ],
            "default_index": 0,
        },
        {
            "category": "subscriptions",
            "name": "Spotify Premium Upgrade",
            "slug": "spotify-premium-upgrade",
            "description": "Manual upgrade for personal or family Spotify subscriptions.",
            "fulfillment_mode": "manual",
            "is_featured": False,
            "is_hidden": False,
            "attributes": [
                ("delivery", "manual"),
                ("platform", "Spotify"),
                ("product_type", "subscription_upgrade"),
            ],
            "input_fields": [
                {"key": "spotify_email", "label": "Spotify email", "field_type": "email", "required": True},
                {"key": "spotify_password", "label": "Spotify password", "field_type": "password", "required": True},
                {"key": "plan_type", "label": "Plan type", "field_type": "text", "required": True, "placeholder": "individual/family/duo"},
                {"key": "months", "label": "Months", "field_type": "number", "required": True, "min_value": "1", "max_value": "12"},
            ],
            "products": [
                {"price": "699", "old_price": "799", "stock": 9999, "attrs": {"region": "Turkey", "duration": "1 month", "plan": "individual"}},
                {"price": "1890", "old_price": "2100", "stock": 9999, "attrs": {"region": "Turkey", "duration": "3 months", "plan": "family"}},
            ],
            "default_index": 0,
        },
        {
            "category": "game-keys",
            "name": "PSN Game Keys",
            "slug": "psn-game-keys",
            "description": "Digital game keys for PlayStation network, instant delivery.",
            "fulfillment_mode": "instant",
            "is_featured": False,
            "is_hidden": False,
            "attributes": [
                ("delivery", "instant"),
                ("platform", "PSN"),
                ("product_type", "game_key"),
            ],
            "products": [
                {"price": "1544", "old_price": "3554", "stock": 8, "attrs": {"title": "Call to Arms - Gates of Hell", "edition": "Standard", "region": "RU/CIS"}},
                {"price": "2865", "old_price": None, "stock": 6, "attrs": {"title": "PSN Top Seller Bundle", "edition": "Standard", "region": "Global"}},
            ],
            "default_index": 0,
        },
        {
            "category": "games",
            "name": "Steam Featured Games",
            "slug": "steam-featured-games",
            "description": "Featured Steam games list similar to storefront tiles.",
            "fulfillment_mode": "instant",
            "is_featured": True,
            "is_hidden": False,
            "attributes": [
                ("delivery", "instant"),
                ("platform", "Steam"),
                ("product_type", "game_entitlement"),
            ],
            "products": [
                {"price": "1849", "old_price": "2982", "stock": 14, "attrs": {"title": "Styx: Blades of Greed", "edition": "Standard", "region": "RU"}},
                {"price": "4019", "old_price": "4619", "stock": 9, "attrs": {"title": "Death Stranding 2: On The Beach", "edition": "Standard", "region": "RU"}},
                {"price": "1955", "old_price": "2678", "stock": 15, "attrs": {"title": "Marathon", "edition": "Standard", "region": "RU"}},
                {"price": "4553", "old_price": "5294", "stock": 7, "attrs": {"title": "Code Vein II", "edition": "Standard", "region": "RU"}},
                {"price": "3298", "old_price": "4283", "stock": 12, "attrs": {"title": "Resident Evil Requiem", "edition": "Standard", "region": "RU"}},
            ],
            "default_index": 0,
        },
        {
            "category": "service-accounts",
            "name": "VPN Accounts",
            "slug": "vpn-accounts",
            "description": "Ready-to-use VPN accounts with instant delivery.",
            "fulfillment_mode": "instant",
            "is_featured": False,
            "is_hidden": False,
            "attributes": [
                ("delivery", "instant"),
                ("platform", "Mixed"),
                ("product_type", "service_account"),
            ],
            "products": [
                {"price": "299", "old_price": "399", "stock": 30, "attrs": {"provider": "NordLike", "duration": "1 month", "region": "Global"}},
                {"price": "1499", "old_price": "1899", "stock": 18, "attrs": {"provider": "NordLike", "duration": "12 months", "region": "Global"}},
            ],
            "default_index": 1,
        },
        {
            "category": "game-accounts",
            "name": "Epic Games Accounts",
            "slug": "epic-games-accounts",
            "description": "Pre-filled accounts with selected game libraries.",
            "fulfillment_mode": "instant",
            "is_featured": False,
            "is_hidden": True,
            "attributes": [
                ("delivery", "instant"),
                ("platform", "Epic Games"),
                ("product_type", "account_bundle"),
            ],
            "products": [
                {"price": "1290", "old_price": "1690", "stock": 5, "attrs": {"bundle": "Action Starter Pack", "region": "Global"}},
                {"price": "2490", "old_price": "2990", "stock": 3, "attrs": {"bundle": "AAA Collection", "region": "Global"}},
            ],
            "default_index": 0,
        },
    ],
}


def _scaled_money(value: str | int | float | None, multiplier: Decimal) -> Decimal | None:
    if value in (None, ""):
        return None
    base = _d(value)
    return (base * multiplier).quantize(Decimal("1"))


def _build_card_rows(card_multiplier: int) -> list[dict]:
    """Expand base cards into N synthetic batches.

    card_multiplier=1 -> base dataset only
    card_multiplier=3 -> base + two additional synthetic copies of each card
    """
    rows: list[dict] = []

    for card_row in DATASET["cards"]:
        for idx in range(card_multiplier):
            row = deepcopy(card_row)
            if idx == 0:
                rows.append(row)
                continue

            batch_num = idx + 1
            row["slug"] = f"{card_row['slug']}-b{batch_num}"
            row["name"] = f"{card_row['name']} Batch {batch_num}"
            row["description"] = (
                f"{card_row['description']} Synthetic batch {batch_num} for load testing and storefront density."
            )
            row["is_featured"] = False

            price_factor = Decimal("1") + (Decimal("0.07") * idx)
            old_price_factor = Decimal("1") + (Decimal("0.08") * idx)
            stock_bonus = 2 * idx

            for product_idx, product_row in enumerate(row["products"], start=1):
                product_row["price"] = str(_scaled_money(product_row["price"], price_factor))
                if product_row.get("old_price"):
                    product_row["old_price"] = str(_scaled_money(product_row["old_price"], old_price_factor))
                product_row["stock"] = max(1, int(product_row["stock"]) + stock_bonus)
                attrs = product_row.get("attrs", {})
                attrs["batch"] = f"B{batch_num}"
                attrs["edition_tag"] = f"Synthetic-{batch_num:02d}-{product_idx:02d}"
                product_row["attrs"] = attrs

            if row.get("input_fields"):
                for field in row["input_fields"]:
                    base_placeholder = field.get("placeholder", "")
                    if base_placeholder:
                        field["placeholder"] = f"{base_placeholder} (batch {batch_num})"

            rows.append(row)

    return rows


class Command(BaseCommand):
    help = "Seed synthetic catalog dataset for development and testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all catalog entities before seeding.",
        )
        parser.add_argument(
            "--card-multiplier",
            type=int,
            default=1,
            help=(
                "Scale product card volume by duplicating each base card with synthetic variants. "
                "Example: --card-multiplier 4 creates 4x cards."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        reset = options["reset"]
        card_multiplier = max(1, options["card_multiplier"])

        if reset:
            self.stdout.write(self.style.WARNING("Reset enabled: deleting existing catalog data..."))
            DigitalItem.objects.all().delete()
            ProductInputField.objects.all().delete()
            ProductAttribute.objects.all().delete()
            Product.objects.all().delete()
            ProductCard.objects.all().delete()
            Category.objects.all().delete()

        category_map: dict[str, Category] = {}
        for row in DATASET["categories"]:
            category, _ = Category.objects.update_or_create(
                slug=row["slug"],
                defaults={
                    "name": row["name"],
                    "icon": row["icon"],
                    "is_active": True,
                },
            )
            category_map[row["slug"]] = category

        created_cards = 0
        created_products = 0
        created_input_fields = 0
        created_digital_items = 0

        card_rows = _build_card_rows(card_multiplier=card_multiplier)
        self.stdout.write(
            self.style.WARNING(
                f"Seeding {len(card_rows)} product cards from {len(DATASET['cards'])} base templates "
                f"(multiplier={card_multiplier})..."
            )
        )

        for card_row in card_rows:
            category = category_map[card_row["category"]]
            card, _ = ProductCard.objects.update_or_create(
                slug=card_row["slug"],
                defaults={
                    "category": category,
                    "name": card_row["name"],
                    "description": card_row["description"],
                    "fulfillment_mode": card_row["fulfillment_mode"],
                    "is_featured": card_row["is_featured"],
                    "is_hidden": card_row["is_hidden"],
                    "is_active": True,
                    "image_url": f"https://images.example.com/catalog/{card_row['slug']}.jpg",
                },
            )
            created_cards += 1

            ProductAttribute.objects.filter(product_card=card).delete()
            ProductInputField.objects.filter(product_card=card).delete()
            Product.objects.filter(product_card=card).delete()

            for key, value in card_row.get("attributes", []):
                ProductAttribute.objects.create(product_card=card, key=key, value=value)

            for idx, field in enumerate(card_row.get("input_fields", [])):
                ProductInputField.objects.create(
                    product_card=card,
                    key=field["key"],
                    label=field["label"],
                    field_type=field["field_type"],
                    is_required=field.get("required", True),
                    placeholder=field.get("placeholder", ""),
                    help_text=field.get("help_text", ""),
                    sort_order=field.get("sort_order", idx),
                    min_value=_d(field["min_value"]) if field.get("min_value") else None,
                    max_value=_d(field["max_value"]) if field.get("max_value") else None,
                    regex=field.get("regex", ""),
                    is_active=True,
                )
                created_input_fields += 1

            created_variants: list[Product] = []
            for product_idx, product_row in enumerate(card_row["products"]):
                attrs = dict(product_row["attrs"])
                attrs["sku_code"] = f"{slugify(card.slug)}-{product_idx + 1:03d}"
                product = Product.objects.create(
                    product_card=card,
                    attributes=attrs,
                    price=_d(product_row["price"]),
                    old_price=_d(product_row["old_price"]) if product_row.get("old_price") else None,
                    stock_count=product_row["stock"],
                    is_hidden=False,
                    is_active=True,
                    image_url=f"https://images.example.com/sku/{slugify(card.slug)}-{product_idx + 1}.jpg",
                )
                created_variants.append(product)
                created_products += 1

                if card.fulfillment_mode == ProductCard.FulfillmentMode.INSTANT:
                    keys_to_create = min(product.stock_count, 15)
                    batch = [
                        DigitalItem(
                            product=product,
                            payload_encrypted=f"DEMO-{product.id}-{idx + 1:05d}-KEY",
                            is_used=False,
                        )
                        for idx in range(keys_to_create)
                    ]
                    DigitalItem.objects.bulk_create(batch)
                    created_digital_items += keys_to_create

            default_index = card_row.get("default_index", 0)
            if created_variants:
                card.default_product = created_variants[min(default_index, len(created_variants) - 1)]
                card.save(update_fields=["default_product", "updated_at"])

        self.stdout.write(self.style.SUCCESS("Synthetic catalog seed completed."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Categories: {len(category_map)}, Product cards: {created_cards}, "
                f"Products: {created_products}, Input fields: {created_input_fields}, "
                f"Digital items: {created_digital_items}, Multiplier: {card_multiplier}"
            )
        )
