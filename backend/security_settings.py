"""Validated demo controls. Never use a process-local counter for authorization."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


def integer(name, default, minimum=1, maximum=100000):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} is outside the supported range")
    return value


def money(name, default):
    try:
        value = Decimal(os.getenv(name, default))
        if not value.is_finite() or not Decimal("0.01") <= value <= Decimal("1000000000") or value.as_tuple().exponent < -2:
            raise ValueError()
        return value
    except (InvalidOperation, ValueError):
        raise RuntimeError(f"{name} must be a positive exact amount with at most two decimal places") from None


@dataclass(frozen=True)
class SecuritySettings:
    single_amount: Decimal = money("PAYMENT_SINGLE_LIMIT", "100000.00")
    daily_amount: Decimal = money("PAYMENT_DAILY_LIMIT", "200000.00")
    daily_count: int = integer("PAYMENT_DAILY_COUNT", 50)
    requests_per_day: int = integer("REQUEST_DAILY_COUNT", 20)
    pin_attempts: int = integer("PIN_MAX_ATTEMPTS", 5, maximum=10)
    pin_lock_seconds: int = integer("PIN_LOCK_SECONDS", 900, maximum=86400)
    authorization_seconds: int = integer("PAYMENT_AUTH_SECONDS", 120, maximum=300)
    login_per_ip: int = integer("LOGIN_IP_LIMIT", 30)
    login_per_identity: int = integer("LOGIN_IDENTITY_LIMIT", 10)
    register_per_ip: int = integer("REGISTER_IP_LIMIT", 10)
    pin_per_minute: int = integer("PIN_RATE_LIMIT", 10)
    submit_per_minute: int = integer("PAYMENT_RATE_LIMIT", 30)
    risk_velocity: int = integer("RISK_VELOCITY_COUNT", 8)
    risk_distinct: int = integer("RISK_DISTINCT_RECIPIENTS", 5)
    risk_large: Decimal = money("RISK_BLOCK_AMOUNT", "75000.00")
    risk_medium: Decimal = money("RISK_REVIEW_AMOUNT", "10000.00")
    risk_insufficient: int = integer("RISK_INSUFFICIENT_COUNT", 5)
    risk_services: int = integer("RISK_SERVICE_COUNT", 8)
    risk_new_contact: int = integer("RISK_NEW_CONTACT_COUNT", 3)
    risk_requests: int = integer("RISK_REQUEST_COUNT", 10)
    audit_days: int = integer("SECURITY_RETENTION_DAYS", 90, maximum=3650)


settings = SecuritySettings()
