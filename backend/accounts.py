import re
import secrets
import unicodedata
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from account_schemas import AccountCreate, AccountResponse
from database import get_db
from models import BankAccount, DemoBank, User
from security import get_current_user


router = APIRouter(prefix="/accounts", tags=["Simulated accounts"])


def generate_account_number() -> str:
    return "SIM" + "".join(secrets.choice("0123456789") for _ in range(16))


def generate_upi_id(full_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:20].rstrip("-")
    return f"{slug or 'learner'}-{secrets.token_hex(6)}@payflow"


def public_account(account: BankAccount) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        bank_name=account.bank_name,
        masked_account_number="SIM •••• •••• •••• " + account.account_number[-4:],
        upi_id=account.upi_id,
        balance=account.balance,
        created_at=account.created_at,
        is_primary=account.is_primary,
    )


@router.get("/banks", response_model=list[DemoBank])
def list_banks(user: User = Depends(get_current_user)):
    return list(DemoBank)


@router.post("", response_model=AccountResponse, status_code=201)
def create_account(
    payload: AccountCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id, full_name = user.id, user.full_name
    lock_account_config(db, user_id)
    count = db.scalar(select(func.count()).select_from(BankAccount).where(BankAccount.user_id == user_id))
    if count >= 4:
        raise HTTPException(status_code=409, detail="Maximum four simulated accounts per user")

    for _ in range(5):
        account = BankAccount(
            user_id=user_id, bank_name=payload.bank_name.value,
            account_number=generate_account_number(), upi_id=generate_upi_id(full_name),
            balance=Decimal("0.00"),
            is_primary=count == 0,
        )
        try:
            # A savepoint lets a collision retry without losing the outer transaction.
            with db.begin_nested():
                db.add(account)
                db.flush()
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint in {"uq_bank_accounts_account_number", "uq_bank_accounts_upi_id"}:
                continue
            # SQLite is used only in isolated tests; production uses PostgreSQL.
            if getattr(exc.orig, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE":
                continue
            raise
        db.commit()
        db.refresh(account)
        return public_account(account)
    raise HTTPException(status_code=503, detail="Could not allocate account identifiers. Please try again")


def lock_account_config(db: Session, user_id: int):
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SELECT pg_advisory_xact_lock(709,:uid)"), {"uid": user_id})


@router.patch("/{account_id}/primary", response_model=AccountResponse)
def set_primary(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lock_account_config(db, user.id)
    accounts = list(db.scalars(select(BankAccount).where(BankAccount.user_id == user.id).order_by(BankAccount.id).with_for_update().execution_options(populate_existing=True)))
    chosen = next((account for account in accounts if account.id == account_id), None)
    if chosen is None:
        from security_events import audit
        audit(db, "UNAUTHORIZED_ACCOUNT_ACCESS", user.id, code="ACCOUNT_UNAVAILABLE")
        db.commit()
        raise HTTPException(404, "Account not found")
    if not chosen.is_primary:
        for account in accounts:
            account.is_primary = False
        db.flush()  # Partial uniqueness is immediate; exactly-one is deferred to commit.
        chosen.is_primary = True
        db.flush()
        from security_events import audit
        audit(db, "ACCOUNT_PRIMARY_CHANGED", user.id, outcome="SUCCESS")
    db.commit()
    return public_account(chosen)


@router.get("", response_model=list[AccountResponse])
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = db.scalars(select(BankAccount).where(BankAccount.user_id == user.id).order_by(BankAccount.is_primary.desc(), BankAccount.id))
    return [public_account(account) for account in accounts]


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.scalar(select(BankAccount).where(
        BankAccount.id == account_id, BankAccount.user_id == user.id
    ))
    if account is None:
        # Other users' accounts and nonexistent accounts have the same response.
        from security_events import audit
        audit(db, "UNAUTHORIZED_ACCOUNT_ACCESS", user.id, code="ACCOUNT_UNAVAILABLE")
        db.commit()
        raise HTTPException(status_code=404, detail="Account not found")
    return public_account(account)
