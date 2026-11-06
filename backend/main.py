
from fastapi import Depends, FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import engine, get_db, test_connection
from operations import router as operations_router
from observability import RequestTelemetry
from accounts import router as accounts_router
from payments import router as payments_router
from social import router as social_router
from splits import router as splits_router
from commerce import router as commerce_router
from pin_security import router as pin_security_router
from security_events import PolicyError, audit, enforce_rate
from security_settings import settings
from models import User
from config import ACCESS_TOKEN_EXPIRE_MINUTES, CORS_ALLOWED_ORIGINS, ENVIRONMENT, EXPOSE_DOCS
from schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from security import (
    create_access_token, dummy_password_hash, get_current_user,
    password_hasher, unauthorized,
)

@asynccontextmanager
async def lifespan(app):
    yield
    engine.dispose()  # Each worker owns its own bounded pool; no worker runs in the API.


# Create the FastAPI application
app = FastAPI(
    lifespan=lifespan,
    title="PayFlow API",
    description="Backend for PayFlow UPI Payment Simulation",
    version="1.0.0",
    docs_url='/docs' if EXPOSE_DOCS == '1' else None,
    redoc_url='/redoc' if EXPOSE_DOCS == '1' else None,
    openapi_url='/openapi.json' if EXPOSE_DOCS == '1' else None,
)
app.include_router(accounts_router)
app.include_router(payments_router)
app.include_router(social_router)
app.include_router(splits_router)
app.include_router(commerce_router)
app.include_router(pin_security_router)
app.include_router(operations_router)
app.add_middleware(RequestTelemetry)

# Allow React frontend to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "Payment-Authorization", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-Correlation-ID", "Retry-After", "Idempotency-Replayed", "Payment-Posted"],
)


@app.exception_handler(PolicyError)
async def policy_error_handler(request: Request, error: PolicyError):
    return JSONResponse(status_code=error.status, content={"detail": error.message, "code": error.code, "retry_after": error.retry_after},
        headers={"Retry-After": str(error.retry_after)} if error.retry_after else None)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.middleware("http")
async def prevent_auth_caching(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'
    if 'text/html' not in response.headers.get('Content-Type',''):
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
    if ENVIRONMENT == 'demo':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    if request.url.path in {"/register", "/login", "/me", "/accounts", "/contacts", "/payment-requests", "/splits", "/metrics"} or request.url.path.startswith(("/accounts/", "/payments/", "/demo/", "/contacts/", "/payment-requests/", "/splits/", "/recharge", "/bills", "/billers", "/saved-billers", "/security/", "/activity/")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Default validation errors can echo submitted passwords, even on malformed JSON.
    errors = [
        {key: error[key] for key in ("type", "loc", "msg")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.post("/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # Use the socket peer only; arbitrary forwarding headers are not trusted.
    enforce_rate(db, "register-ip", request.client.host if request.client else "unknown", settings.register_per_ip, 3600)
    enforce_rate(db, "register-identity", payload.email, 3, 3600)
    existing_user = db.scalar(
        select(User.id).where(func.lower(User.email) == payload.email)
    )
    if existing_user is not None:
        audit(db, "REGISTRATION_FAILURE", code="REGISTRATION_UNAVAILABLE")
        db.commit()
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=password_hasher.hash(payload.password.get_secret_value()),
    )
    db.add(user)
    try:
        db.flush()
        audit(db, "REGISTRATION_SUCCESS", user.id, outcome="SUCCESS")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The database unique constraint also protects concurrent registrations.
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=409, detail="Email already registered"
            ) from None
        raise
    db.refresh(user)
    return user


@app.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate(db, "login-ip", request.client.host if request.client else "unknown", settings.login_per_ip, 60)
    enforce_rate(db, "login-identity", payload.email, settings.login_per_identity, 900)
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    stored_hash = user.password_hash if user else dummy_password_hash
    try:
        valid = password_hasher.verify(payload.password.get_secret_value(), stored_hash)
    except (UnknownHashError, ValueError):
        valid = False
    if not valid or user is None:
        audit(db, "LOGIN_FAILURE", user.id if user else None)
        db.commit()
        raise unauthorized("Invalid email or password")
    audit(db, "LOGIN_SUCCESS", user.id, outcome="SUCCESS")
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@app.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


# Home endpoint
@app.get("/")
def home():
    return {
        "message": "Welcome to PayFlow",
        "application": "UPI Payment Simulation"
    }


# Backend health check
@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


# PostgreSQL database connection check
@app.get("/db-health")
def db_health():
    try:
        result = test_connection()

        return {
            "database": "connected",
            "result": result
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )
