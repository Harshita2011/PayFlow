
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, test_connection
from accounts import router as accounts_router
from payments import router as payments_router
from social import router as social_router
from splits import router as splits_router
from commerce import router as commerce_router
from models import User
from config import ACCESS_TOKEN_EXPIRE_MINUTES
from schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from security import (
    create_access_token, dummy_password_hash, get_current_user,
    password_hasher, unauthorized,
)

# Create the FastAPI application
app = FastAPI(
    title="PayFlow API",
    description="Backend for PayFlow UPI Payment Simulation",
    version="1.0.0"
)
app.include_router(accounts_router)
app.include_router(payments_router)
app.include_router(social_router)
app.include_router(splits_router)
app.include_router(commerce_router)

# Allow React frontend to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.middleware("http")
async def prevent_auth_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/register", "/login", "/me", "/accounts", "/contacts", "/payment-requests", "/splits"} or request.url.path.startswith(("/accounts/", "/payments/", "/demo/", "/contacts/", "/payment-requests/", "/splits/", "/recharge", "/bills", "/billers", "/saved-billers")):
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
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing_user = db.scalar(
        select(User.id).where(func.lower(User.email) == payload.email)
    )
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=password_hasher.hash(payload.password.get_secret_value()),
    )
    db.add(user)
    try:
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
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    stored_hash = user.password_hash if user else dummy_password_hash
    try:
        valid = password_hasher.verify(payload.password.get_secret_value(), stored_hash)
    except (UnknownHashError, ValueError):
        valid = False
    if not valid or user is None:
        raise unauthorized("Invalid email or password")
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
