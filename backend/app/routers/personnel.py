"""人员定位接口：维护定位终端，覆盖记录离线、低电提醒、办理更换的单台与批量处置。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchActionPayload,
    EntryPayload,
    PageResult,
    SelectionPayload,
)
from app.services.personnel import BATCH_LIMIT, PersonnelService

router = APIRouter(prefix="/api/personnel", tags=["人员定位"])

service = PersonnelService()

LIST_FIELDS = ["终端编号", "携带人员", "所在位置", "入井时刻", "区域停留", "定位精度", "信号强度", "终端状态"]
STATUSES = ["在线", "离线", "低电量", "已更换"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按终端编号检索"),
    status: str | None = Query(default=None, description="在线、离线、低电量、已更换"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按终端编号与状态过滤人员定位列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/batch/selection")
def fetch_selection(payload: SelectionPayload) -> dict[str, Any]:
    """跨页勾选核对：按 id 清单回捞终端最新数据，提交前供值班员逐条确认。"""
    if not payload.terminal_ids:
        raise HTTPException(status_code=400, detail="勾选清单为空，请先勾选定位终端")
    if len(payload.terminal_ids) > BATCH_LIMIT:
        raise HTTPException(status_code=400, detail=f"单批最多 {BATCH_LIMIT} 台，请分批提交")
    return service.fetch_selection(payload.terminal_ids)


@router.post("/batch/preview")
def preview_batch(payload: BatchActionPayload) -> dict[str, Any]:
    """批量提交前试算：返回去重后台数、预计生效台数与逐台跳过原因，不落任何数据。"""
    result, message = service.preview_batch(payload.action, payload.terminal_ids)
    if result is None:
        raise HTTPException(status_code=400, detail=message)
    return result


@router.post("/batch/actions")
def run_batch(payload: BatchActionPayload) -> dict[str, Any]:
    """整组提交同一类动作；不满足条件的终端原样跳过并逐台回执，其余照常处理。

    同一动作 + 同一去重清单重复提交时，只回放首次结果，不会二次生效。
    """
    result, message = service.run_batch(
        payload.action,
        payload.terminal_ids,
        batch_no=payload.batch_no,
        operator=payload.operator,
        remark=payload.remark,
    )
    if result is None:
        raise HTTPException(status_code=400, detail=message)
    return result


@router.get("/stats/overview")
def stats_overview() -> dict[str, Any]:
    """终端状态与携带人员名单数量；换卡停用后名单人数随之减少。"""
    return service.stats()


@router.get("/carriers")
def carriers() -> dict[str, Any]:
    """携带人员名单：只包含未停用终端的携带人，与在井名单联动。"""
    return service.carriers()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出人员定位清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "personnel", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条定位终端明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"定位终端 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条定位终端，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="定位终端已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条定位终端执行记录离线、低电提醒、办理更换；前置条件不满足会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    operator = payload.values.get("operator")
    entry, message = service.run_action(entry_id, action, operator=operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
