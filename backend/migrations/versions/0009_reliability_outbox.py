"""Add durable non-financial events; preserve all historical financial/security rows."""
from alembic import op
import sqlalchemy as sa

revision = '0009_reliability_outbox'
down_revision = '0008_payment_security'
branch_labels = depends_on = None


def upgrade():
    # Measured isolated actor/time query: see benchmarks/results/query-plan.json.
    op.create_index('ix_payments_actor_time','payments',['actor_user_id','created_at'])
    op.create_table('outbox_events',
        sa.Column('event_id', sa.String(36), primary_key=True),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('payment_id', sa.String(36), sa.ForeignKey('payments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('correlation_id', sa.String(36)),
        sa.Column('status', sa.String(12), nullable=False), sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True)), sa.Column('lease_token', sa.String(36)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True)), sa.Column('last_error', sa.String(40)),
        sa.UniqueConstraint('payment_id','event_type', name='uq_outbox_payment_type'),
        sa.CheckConstraint("status IN ('PENDING','PROCESSING','PROCESSED','DEAD')", name='ck_outbox_status'),
        sa.CheckConstraint('attempt_count >= 0', name='ck_outbox_attempts'),
        sa.CheckConstraint("(status='PROCESSING' AND lease_token IS NOT NULL AND locked_until IS NOT NULL) OR (status<>'PROCESSING' AND lease_token IS NULL AND locked_until IS NULL)", name='ck_outbox_lease'),
        sa.CheckConstraint("(status='PROCESSED') = (processed_at IS NOT NULL)", name='ck_outbox_processed'))
    op.create_index('ix_outbox_ready','outbox_events',['available_at','created_at'], postgresql_where=sa.text("status IN ('PENDING','PROCESSING')"))
    op.create_table('activity_notifications',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('event_id',sa.String(36),sa.ForeignKey('outbox_events.event_id',ondelete='RESTRICT'),nullable=False),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('payment_id',sa.String(36),sa.ForeignKey('payments.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.text('CURRENT_TIMESTAMP'),nullable=False),
        sa.UniqueConstraint('event_id','user_id',name='uq_notification_event_user'))
    op.create_index('ix_notifications_owner','activity_notifications',['user_id','created_at','id'])
    op.execute("""CREATE FUNCTION payflow_guard_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF ROW(NEW.event_id,NEW.event_type,NEW.payment_id,NEW.payload::text,NEW.correlation_id,NEW.created_at)
         IS DISTINCT FROM ROW(OLD.event_id,OLD.event_type,OLD.payment_id,OLD.payload::text,OLD.correlation_id,OLD.created_at)
      THEN RAISE EXCEPTION 'Event identity is immutable' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
    op.execute('CREATE TRIGGER guard_outbox BEFORE UPDATE ON outbox_events FOR EACH ROW EXECUTE FUNCTION payflow_guard_outbox()')
    op.execute("""CREATE FUNCTION payflow_require_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.status='SUCCESS' AND NOT EXISTS(SELECT 1 FROM outbox_events WHERE payment_id=NEW.id AND event_type='payment.posted.v1')
      THEN RAISE EXCEPTION 'Successful payment requires an outbox event' USING ERRCODE='23514'; END IF; RETURN NULL; END $$""")
    op.execute('CREATE CONSTRAINT TRIGGER require_outbox AFTER INSERT ON payments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_require_outbox()')


def downgrade():
    raise RuntimeError('Preserve financial and event history; use a reviewed forward migration')
