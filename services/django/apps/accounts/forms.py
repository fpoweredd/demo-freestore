from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)


class RegisterForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(min_length=8, widget=forms.PasswordInput)
    password_confirm = forms.CharField(min_length=8, widget=forms.PasswordInput)
    telegram_handle = forms.CharField(required=False, max_length=64)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") and cleaned.get("password_confirm") and cleaned["password"] != cleaned["password_confirm"]:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField()


class PasswordResetConfirmForm(forms.Form):
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput,
        error_messages={
            "required": "Enter a new password.",
            "blank": "Enter a new password.",
            "min_length": "Password must be at least 8 characters.",
        },
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput,
        error_messages={
            "required": "Confirm your password.",
            "blank": "Confirm your password.",
        },
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") and cleaned.get("password_confirm") and cleaned["password"] != cleaned["password_confirm"]:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class OAuthStepUpForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput)


class ProfileUpdateForm(forms.Form):
    first_name = forms.CharField(required=False, max_length=150)
    last_name = forms.CharField(required=False, max_length=150)
    telegram_handle = forms.CharField(required=False, max_length=64)

    @staticmethod
    def _validate_human_name(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        allowed_separators = {" ", "-", "'"}
        for ch in value:
            if ch in allowed_separators:
                continue
            if ch.isalpha():
                continue
            raise forms.ValidationError("Enter your real name (letters only).")
        return value

    def clean_first_name(self):
        return self._validate_human_name(self.cleaned_data.get("first_name"))

    def clean_last_name(self):
        return self._validate_human_name(self.cleaned_data.get("last_name"))

    def clean_telegram_handle(self):
        value = (self.cleaned_data.get("telegram_handle") or "").strip()
        if value.startswith("@"):
            value = value[1:].strip()
        return value


class PasswordChangeFromProfileForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput)
    new_password = forms.CharField(min_length=8, widget=forms.PasswordInput)
    new_password_confirm = forms.CharField(min_length=8, widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        value = self.cleaned_data.get("current_password") or ""
        if not self.user:
            raise forms.ValidationError("User not found.")
        if not self.user.check_password(value):
            raise forms.ValidationError("Current password is incorrect.")
        return value

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("new_password_confirm")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password_confirm", "Passwords do not match.")
        return cleaned


class PasswordSetFromGoogleForm(forms.Form):
    new_password = forms.CharField(min_length=8, widget=forms.PasswordInput)
    new_password_confirm = forms.CharField(min_length=8, widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("new_password_confirm")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password_confirm", "Passwords do not match.")
        return cleaned


class SetEmailOnceForm(forms.Form):
    email = forms.EmailField()

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return email
        if User.objects.filter(email__iexact=email).exclude(id=getattr(self.user, "id", None)).exists():
            raise forms.ValidationError("This email is already used by another account.")
        return email
