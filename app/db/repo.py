from __future__ import annotations

from app.db.models import RunRecord


class Repository:
    def __init__(self, session_factory) -> None:
        self.sf = session_factory

    def add_record(self, event: str, message: str = "") -> None:
        s = self.sf()
        try:
            s.add(RunRecord(event=event, message=message))
            s.commit()
        finally:
            s.close()

    def stats(self) -> dict:
        s = self.sf()
        try:
            total = s.query(RunRecord).count()
            return {"total_records": total}
        finally:
            s.close()

    def recent_records(self, limit: int = 50) -> list[dict]:
        s = self.sf()
        try:
            rows = (
                s.query(RunRecord)
                .order_by(RunRecord.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "event": r.event,
                    "message": r.message,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
        finally:
            s.close()