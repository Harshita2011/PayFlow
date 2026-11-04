
import os
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))

# Configurable ten-digit demo syntax; digit-only prefixes cannot inject a regex.
DEMO_MOBILE_PREFIXES = os.getenv("PAYFLOW_DEMO_MOBILE_PREFIXES", "6789")
if not DEMO_MOBILE_PREFIXES or len(DEMO_MOBILE_PREFIXES) > 10 or any(c not in "0123456789" for c in DEMO_MOBILE_PREFIXES):
    raise RuntimeError("PAYFLOW_DEMO_MOBILE_PREFIXES must contain one to ten ASCII digits")
DEMO_MOBILE_PATTERN = "^[" + DEMO_MOBILE_PREFIXES + "][0-9]{9}$"

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if len(JWT_SECRET_KEY.encode()) < 32:
    raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes; see .env.example")

try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
except ValueError:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be an integer") from None
if not 1 <= ACCESS_TOKEN_EXPIRE_MINUTES <= 60:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 60")
