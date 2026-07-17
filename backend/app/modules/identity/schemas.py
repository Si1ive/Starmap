"""Request and response schemas for learning-user authentication."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    """Authenticate an existing email password without applying new rules."""

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False
    anti_bot_token: Optional[str] = Field(default=None, max_length=2048)


class RegisterRequest(BaseModel):
    """Create or resume a pending email registration."""

    display_name: str = Field(min_length=1, max_length=64)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    password_confirmation: str = Field(min_length=1, max_length=128)
    accept_terms: bool
    accept_privacy: bool
    anti_bot_token: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("昵称不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_registration_contract(self) -> "RegisterRequest":
        if self.password != self.password_confirmation:
            raise ValueError("两次输入的密码不一致")
        if not self.accept_terms or not self.accept_privacy:
            raise ValueError("必须同意服务条款和隐私说明")
        return self


class ResendEmailVerificationRequest(BaseModel):
    """Request another email for the current registration transaction."""

    anti_bot_token: Optional[str] = Field(default=None, max_length=2048)


class ConfirmEmailVerificationRequest(BaseModel):
    """Confirm an email with either a link token or a browser-bound code."""

    token: Optional[str] = Field(default=None, min_length=20, max_length=256)
    code: Optional[str] = Field(
        default=None,
        pattern=r"^\d{6}$",
    )

    @model_validator(mode="after")
    def require_exactly_one_credential(self) -> "ConfirmEmailVerificationRequest":
        if (self.token is None) == (self.code is None):
            raise ValueError("必须且只能提交一种邮箱验证凭据")
        return self
