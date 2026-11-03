from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_SECRET_KEY
from database import get_db
from models import User


password_hasher = PasswordHash.recommended()
# Unknown emails still perform a hash verification to reduce timing differences.
dummy_password_hash = password_hasher.hash(token_urlsafe(32))
bearer = HTTPBearer(auto_error=False)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "payflow"
JWT_AUDIENCE = "payflow-web"


def unauthorized(detail: str = "Invalid or expired access token") -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "token_use": "access",
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        claims = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["sub", "iat", "exp", "iss", "aud", "token_use"]},
        )
        subject = claims["sub"]
        if (
            claims["token_use"] != "access"
            or not isinstance(subject, str)
            or not subject.isascii()
            or not subject.isdecimal()
            or not 0 < int(subject) <= 2_147_483_647
            or subject != str(int(subject))
            or type(claims["iat"]) is not int
            or type(claims["exp"]) is not int
            or claims["exp"] <= claims["iat"]
        ):
            raise unauthorized()
        user_id = int(subject)
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise unauthorized() from None

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized()
    return user
