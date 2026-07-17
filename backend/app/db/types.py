"""Project-specific SQLAlchemy column types."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import LargeBinary
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UUIDBinary(TypeDecorator[uuid.UUID]):
    """Store UUID values as 16-byte binary values and expose ``uuid.UUID``."""

    impl = LargeBinary(16)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.BINARY(16))
        return dialect.type_descriptor(LargeBinary(16))

    def process_bind_param(
        self,
        value: uuid.UUID | str | bytes | None,
        dialect: Dialect,
    ) -> bytes | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value.bytes
        if isinstance(value, bytes):
            if len(value) != 16:
                raise ValueError("UUID binary values must contain exactly 16 bytes")
            return value
        return uuid.UUID(str(value)).bytes

    def process_result_value(
        self,
        value: Any,
        dialect: Dialect,
    ) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(bytes=bytes(value))


def new_uuid7() -> uuid.UUID:
    """Generate the sortable UUID used by new identity aggregates."""

    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is None:
        return uuid.uuid4()
    return uuid7()
