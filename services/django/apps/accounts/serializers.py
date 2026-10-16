from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AccountProfile
from .services import (
    client_ip_from_request,
    consume_password_reset,
    issue_password_reset,
    register_user,
)

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            "required": "Enter your email.",
            "blank": "Enter your email.",
            "invalid": "Enter a valid email.",
        }
    )
    password = serializers.CharField(
        min_length=8,
        write_only=True,
        error_messages={
            "required": "Enter your password.",
            "blank": "Enter your password.",
            "min_length": "Password must be at least 8 characters.",
        },
    )
    telegram_handle = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        error_messages={
            "max_length": "Telegram handle is too long.",
        },
    )

    def create(self, validated_data):
        request = self.context.get("request")
        user, created = register_user(
            email=validated_data["email"],
            password=validated_data["password"],
            telegram_handle=validated_data.get("telegram_handle", ""),
            registration_ip=client_ip_from_request(request),
            request=request,
        )
        self._created = created
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            "required": "Enter your email.",
            "blank": "Enter your email.",
            "invalid": "Enter a valid email.",
        }
    )
    password = serializers.CharField(
        write_only=True,
        error_messages={
            "required": "Enter your password.",
            "blank": "Enter your password.",
        },
    )


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            "required": "Enter your email.",
            "blank": "Enter your email.",
            "invalid": "Enter a valid email.",
        }
    )

    def create(self, validated_data):
        return issue_password_reset(validated_data["email"])


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=64)
    password = serializers.CharField(
        min_length=8,
        write_only=True,
        error_messages={
            "required": "Enter a new password.",
            "blank": "Enter a new password.",
            "min_length": "Password must be at least 8 characters.",
        },
    )

    def create(self, validated_data):
        return consume_password_reset(validated_data["token"], validated_data["password"])


class AccountMeSerializer(serializers.ModelSerializer):
    public_id = serializers.IntegerField(source="account_profile.public_id", read_only=True)
    balance = serializers.DecimalField(
        source="account_profile.balance",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    telegram_handle = serializers.CharField(source="account_profile.telegram_handle", allow_blank=True, required=False)
    require_password_after_oauth = serializers.BooleanField(
        source="account_profile.require_password_after_oauth", required=False
    )

    class Meta:
        model = User
        fields = (
            "public_id",
            "balance",
            "username",
            "email",
            "telegram_handle",
            "require_password_after_oauth",
        )
        read_only_fields = ("public_id", "username", "email", "balance")

    def update(self, instance, validated_data):
        profile_data = validated_data.get("account_profile", {})
        profile, _ = AccountProfile.objects.get_or_create(user=instance)
        if "telegram_handle" in profile_data:
            profile.telegram_handle = profile_data["telegram_handle"]
        if "require_password_after_oauth" in profile_data:
            profile.require_password_after_oauth = profile_data["require_password_after_oauth"]
        profile.save()
        return instance
