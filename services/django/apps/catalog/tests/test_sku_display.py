from django.test import SimpleTestCase

from apps.catalog.sku_display import build_selected_sku_rows, sku_row_values


class SkuDisplayTests(SimpleTestCase):
    def test_custom_axes_use_attribute_values_not_product_id(self):
        rows = build_selected_sku_rows(
            product_id=16,
            price="350.00",
            attributes={"type": "Pro", "duration": "1 месяц"},
            selector_axes=["duration"],
            ui_labels={"duration": "На"},
        )
        values = sku_row_values(rows)
        self.assertIn("1 месяц", values)
        self.assertIn("Pro", values)
        self.assertNotIn("#16", values)

    def test_variant_axis_shows_product_id(self):
        rows = build_selected_sku_rows(
            product_id=16,
            price="350.00",
            attributes={"duration": "1 месяц"},
            selector_axes=["duration", "variant"],
            ui_labels={},
        )
        values = sku_row_values(rows)
        self.assertEqual(values, ["1 месяц", "#16"])

    def test_legacy_region_nominal_still_work(self):
        rows = build_selected_sku_rows(
            product_id=5,
            price="100",
            attributes={"region": "TR", "nominal": "100 TL"},
            selector_axes=[],
            ui_labels={},
        )
        values = sku_row_values(rows)
        self.assertIn("TR", values)
        self.assertIn("100 TL", values)
