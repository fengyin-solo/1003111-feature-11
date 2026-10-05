"""人员定位值班台账业务规则：台账由人员定位处置自动登记，这里只提供查询口径。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "dutylog"
STATUS_ORDER = ["已登记", "已核对", "已归档"]


class DutylogService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(reversed(store.rows(MODULE)))  # 台账按登记时间倒序展示
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("台账编号", ""))
                or keyword in str(row.get("处置事项", ""))
                or keyword in str(row.get("值班人员", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def review_entry(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"值班台账 {entry_id} 不存在"
        entry["status"] = "已核对"
        entry["pending"] = False
        return entry, "台账已核对"
