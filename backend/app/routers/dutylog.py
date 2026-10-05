"""人员定位值班台账接口：批量处置结果由人员定位服务自动写入，这里负责查询与核对。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, PageResult
from app.services.dutylog import DutylogService

router = APIRouter(prefix="/api/dutylog", tags=["人员定位值班台账"])

service = DutylogService()

LIST_FIELDS = ["台账编号", "处置事项", "批次号", "涉及终端数", "成功台数", "跳过台数", "值班人员", "处置时间", "状态"]
STATUSES = ["已登记", "已核对", "已归档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按台账编号、处置事项或值班人员检索"),
    status: str | None = Query(default=None, description="已登记、已核对、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """值班台账倒序展示，最新的批量处置记录在最前。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出值班台账全量记录。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "dutylog", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条台账明细，含跳过终端与原因。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"值班台账 {entry_id} 不存在")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def review_entry(entry_id: int) -> ActionResult:
    """值班长核对台账。"""
    entry, message = service.review_entry(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
