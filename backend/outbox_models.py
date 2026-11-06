"""Non-financial side effects only; immutable event identity with leased delivery state."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (
        UniqueConstraint('payment_id', 'event_type', name='uq_outbox_payment_type'),
        CheckConstraint("status IN ('PENDING','PROCESSING','PROCESSED','DEAD')", name='ck_outbox_status'),
        CheckConstraint('attempt_count >= 0', name='ck_outbox_attempts'),
        CheckConstraint("(status='PROCESSING' AND lease_token IS NOT NULL AND locked_until IS NOT NULL) OR (status<>'PROCESSING' AND lease_token IS NULL AND locked_until IS NULL)", name='ck_outbox_lease'),
        CheckConstraint("(status='PROCESSED') = (processed_at IS NOT NULL)", name='ck_outbox_processed'),
        Index('ix_outbox_ready', 'available_at', 'created_at', postgresql_where=text("status IN ('PENDING','PROCESSING')")),
    )
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(40), default='payment.posted.v1')
    payment_id: Mapped[str] = mapped_column(ForeignKey('payments.id', ondelete='RESTRICT'))
    payload: Mapped[dict] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(12), default='PENDING')
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))


class ActivityNotification(Base):
    __tablename__ = 'activity_notifications'
    __table_args__ = (UniqueConstraint('event_id', 'user_id', name='uq_notification_event_user'),
                     Index('ix_notifications_owner', 'user_id', 'created_at', 'id'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(ForeignKey('outbox_events.event_id', ondelete='RESTRICT'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    payment_id: Mapped[str] = mapped_column(ForeignKey('payments.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
