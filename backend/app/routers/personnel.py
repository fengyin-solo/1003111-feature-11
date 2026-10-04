"""人员定位接口：维护定位终端，覆盖记录离线、低电提醒、办理更换等动作，支持整组批量处置。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchPayload, EntryPayload, PageResult
from app.services.personnel import PersonnelService

router = APIRouter(prefix="/api/personnel", tags=["人员定位"])

service = PersonnelService()

LIST_FIELDS = ["终端编号", "携带人员", "所在位置", "入井时刻", "区域停留", "定位精度", "信号强度", "终端状态"]
STATUSES = ["在线", "离线", "低电量", "已更换"]


@router.get("/stats")
def personnel_stats() -> dict[str, int]:
    """按终端状态汇总台数，给列表页的统计卡片用。"""
    return service.stats()


@router.get("/ledger")
def list_ledger() -> dict[str, Any]:
    """值班台账：每批批量处置留一条账，逐台回执随账可查。"""
    items = service.list_ledger()
    return {"module": "personnel_ledger", "total": len(items), "items": items}


@router.get("/carriers")
def list_carriers() -> dict[str, Any]:
    """携带人员名单：由定位终端实时汇总，批量处置后跟着变。"""
    items = service.list_carriers()
    return {"module": "personnel_carriers", "total": len(items), "items": items}


@router.post("/batch/preview")
def preview_batch(payload: BatchPayload) -> dict[str, Any]:
    """提交前核对：按最新状态逐台预检，返回会受影响的台数与逐台结论，不产生变更。

    跨页勾选的清单在提交前用这里重新拉一遍即可核对。
    """
    preview, error = service.preview_batch(payload.action, payload.entry_ids)
    if preview is None:
        return {"ok": False, "message": error}
    return {"ok": True, **preview}


@router.post("/batch")
def run_batch(payload: BatchPayload) -> dict[str, Any]:
    """整组提交批量处置：不满足条件的终端原样跳过并逐条回执原因，其余照常处理。

    同一批重复勾选的终端只算一次；带相同 request_id 的重复提交只生效一次。
    处理结果同步值班台账、携带人员名单与入井管理的在井人数。
    """
    result, error = service.run_batch(
        payload.action,
        payload.entry_ids,
        request_id=payload.request_id,
        operator=payload.operator,
    )
    if result is None:
        return {"ok": False, "message": error}
    return {"ok": True, **result}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出人员定位清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "personnel", "total": total, "items": items}


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
    """对单条定位终端执行记录离线、低电提醒、办理更换；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
