from django import forms

from .models import Product


class DigitalItemBulkUploadForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.select_related("product_card").order_by("product_card__name", "id"),
        help_text="Choose the purchasable product (former variant) for these keys.",
    )
    payloads = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 16, "cols": 120}),
        help_text="One key per line. Empty lines are ignored.",
    )

    def clean_payloads(self):
        raw_value = self.cleaned_data["payloads"]
        items = [line.strip() for line in raw_value.splitlines() if line.strip()]
        if not items:
            raise forms.ValidationError("Paste at least one non-empty key.")
        return items
