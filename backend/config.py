
import os
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlsplit
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


load_dotenv(Path(__file__).with_name(".env"))

ENVIRONMENT = os.getenv('PAYFLOW_ENV', 'development')
if ENVIRONMENT not in {'development', 'test', 'demo'}:
    raise RuntimeError('PAYFLOW_ENV must be development, test or demo')


def parse_origins(value, environment):
    origins = []
    for item in value.split(','):
        origin = item.strip().rstrip('/')
        parsed = urlsplit(origin)
        if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or '*' in origin or
            (environment == 'demo' and parsed.scheme != 'https')):
            raise RuntimeError('CORS_ALLOWED_ORIGINS must contain exact origins; demo requires HTTPS')
        try:
            parsed.port
        except ValueError:
            raise RuntimeError('Invalid CORS origin port') from None
        origins.append(origin)
    if not origins:
        raise RuntimeError('Configure at least one CORS origin')
    return list(dict.fromkeys(origins))


CORS_ALLOWED_ORIGINS = parse_origins(os.getenv('CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173'), ENVIRONMENT)
EXPOSE_DOCS = os.getenv('PAYFLOW_EXPOSE_DOCS', '0' if ENVIRONMENT == 'demo' else '1')
if EXPOSE_DOCS not in {'0','1'}:
    raise RuntimeError('PAYFLOW_EXPOSE_DOCS must be 0 or 1')
LOG_LEVEL = os.getenv('LOG_LEVEL','INFO').upper()
if LOG_LEVEL not in {'INFO','WARNING','ERROR'}:
    raise RuntimeError('LOG_LEVEL must be INFO, WARNING or ERROR')

# Configurable ten-digit demo syntax; digit-only prefixes cannot inject a regex.
DEMO_MOBILE_PREFIXES = os.getenv("PAYFLOW_DEMO_MOBILE_PREFIXES", "6789")
if not DEMO_MOBILE_PREFIXES or len(DEMO_MOBILE_PREFIXES) > 10 or any(c not in "0123456789" for c in DEMO_MOBILE_PREFIXES):
    raise RuntimeError("PAYFLOW_DEMO_MOBILE_PREFIXES must contain one to ten ASCII digits")
DEMO_MOBILE_PATTERN = "^[" + DEMO_MOBILE_PREFIXES + "][0-9]{9}$"

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")
try:
    parsed_database = make_url(DATABASE_URL)
    if parsed_database.drivername in {'postgres','postgresql'}:
        parsed_database = parsed_database.set(drivername='postgresql+psycopg')
    if parsed_database.drivername != 'postgresql+psycopg' or not parsed_database.database:
        raise ValueError()
    if ENVIRONMENT == 'demo' and parsed_database.query.get('sslmode') not in {'require','verify-ca','verify-full'}:
        raise RuntimeError('Demo PostgreSQL connections require sslmode=require or certificate verification')
    DATABASE_URL = parsed_database.render_as_string(hide_password=False)
except (ValueError, TypeError, ArgumentError):
    raise RuntimeError('Configure a valid PostgreSQL psycopg connection URL') from None

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if len(JWT_SECRET_KEY.encode()) < 32:
    raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes; see .env.example")
if ENVIRONMENT == 'demo' and any(marker in JWT_SECRET_KEY.lower() for marker in ('replace','your_secret','test-only','example')):
    raise RuntimeError('Generate a new random JWT secret for the demo environment')

try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
except ValueError:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be an integer") from None
if not 1 <= ACCESS_TOKEN_EXPIRE_MINUTES <= 60:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 60")
