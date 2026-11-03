
import os
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))

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
