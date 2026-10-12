from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RunRecord(Base):
    __tablename__ = "run_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now, index=True)