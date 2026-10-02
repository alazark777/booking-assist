"""initial appointment assistant schema"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("conversation_sessions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("principal_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"), sa.Column("turn_claimed_until", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_session_principal", "conversation_sessions", ["principal_id"])
    op.create_table("conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), nullable=False), sa.Column("principal_id", sa.String(100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("client_message_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "sequence", name="uq_message_sequence"),
    )
    op.create_index("ix_message_session", "conversation_messages", ["session_id"])
    op.create_table("message_idempotency",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("principal_id", sa.String(100), nullable=False), sa.Column("client_message_id", sa.String(36), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("response_json", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("principal_id", "client_message_id", name="uq_client_message"),
    )
    op.create_table("availability_slots",
        sa.Column("id", sa.String(100), primary_key=True), sa.Column("service", sa.String(100), nullable=False), sa.Column("location", sa.String(100), nullable=False), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("timezone", sa.String(60), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"), sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_slot_service", "availability_slots", ["service"])
    op.create_index("ix_slot_start", "availability_slots", ["starts_at"])
    op.create_table("booking_proposals",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("principal_id", sa.String(100), nullable=False), sa.Column("session_id", sa.String(36), nullable=False), sa.Column("slot_id", sa.String(100), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="active"), sa.Column("approved_message_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_proposal_principal", "booking_proposals", ["principal_id"])
    op.create_index("ix_proposal_session", "booking_proposals", ["session_id"])
    op.create_table("mock_bookings",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("proposal_id", sa.String(36), nullable=False), sa.Column("principal_id", sa.String(100), nullable=False), sa.Column("slot_id", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("proposal_id", name="uq_booking_proposal"), sa.UniqueConstraint("slot_id", name="uq_booking_slot"),
    )
    op.create_index("ix_booking_principal", "mock_bookings", ["principal_id"])


def downgrade() -> None:
    op.drop_table("mock_bookings")
    op.drop_table("booking_proposals")
    op.drop_table("availability_slots")
    op.drop_table("message_idempotency")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_sessions")
