"""人员定位业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.shift import ShiftService
from app.store import store

MODULE = "personnel"
SHIFT_MODULE = "shift"
REQUIRED_FIELDS = ["终端编号", "携带人员", "所在位置"]
STATUS_ORDER = ["在线", "离线", "低电量", "已更换"]
ACTION_RULES = {"记录离线": "离线", "低电提醒": "低电量", "办理更换": "已更换"}
NEGATIVE_ACTIONS = []

# 批量处置的逐台校验口径：命中即跳过并回执原因，未命中的照常处理。
BATCH_SKIP_REASONS = {
    "记录离线": {
        "离线": "终端已处于离线状态，无需重复记录",
        "已更换": "该终端已换卡，不再记录离线",
    },
    "低电提醒": {
        "在线": "终端电量正常，无需低电提醒",
        "离线": "终端不在线，提醒无法送达",
        "已更换": "该终端已换过卡，无需低电提醒",
    },
    "办理更换": {
        "离线": "终端不在线，无法办理更换",
        "已更换": "该终端已换过卡，无需重复更换",
    },
}

# 终端进入这些状态后不再跟踪，携带人员的在井记录同步销记，在井人数随之减少。
UNTRACKED_STATUSES = {"离线", "已更换"}

MAX_RECEIPTS = 200


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PersonnelService:
    def __init__(self) -> None:
        self._shift = ShiftService()
        self._ledger: list[dict[str, Any]] = []
        self._receipts: dict[str, dict[str, Any]] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("终端编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = str(row.get("status", ""))
            if status in counts:
                counts[status] += 1
        return counts

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"定位终端 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于人员定位可执行范围"
        message = self._apply_action(entry, action)
        return entry, message

    def _apply_action(self, entry: dict[str, Any], action: str) -> str:
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["最近处置"] = action
        entry["最近处置时间"] = _now()
        return f"定位终端已{action}"

    @staticmethod
    def _dedupe_ids(entry_ids: list[Any]) -> list[int]:
        """同一批里重复勾到同一台只算一次，保持勾选顺序。"""
        seen: set[int] = set()
        ordered: list[int] = []
        for raw in entry_ids:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id not in seen:
                seen.add(entry_id)
                ordered.append(entry_id)
        return ordered

    def _check_item(self, entry_id: int, action: str) -> dict[str, Any]:
        """逐台校验：返回该台的当前快照与可否处理、跳过原因。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return {
                "id": entry_id,
                "终端编号": "",
                "携带人员": "",
                "当前状态": "",
                "可处理": False,
                "原因": f"定位终端 {entry_id} 不存在或已归档",
            }
        reason = BATCH_SKIP_REASONS[action].get(str(entry.get("status", "")), "")
        return {
            "id": entry_id,
            "终端编号": entry.get("终端编号", ""),
            "携带人员": entry.get("携带人员", ""),
            "当前状态": entry.get("status", ""),
            "可处理": not reason,
            "原因": reason,
        }

    def preview_batch(self, action: str, entry_ids: list[Any]) -> tuple[dict[str, Any] | None, str]:
        """提交前核对：按最新状态逐台预检，给出会受影响的台数，不产生任何变更。"""
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于人员定位可执行范围"
        ids = self._dedupe_ids(entry_ids)
        if not ids:
            return None, "未选择任何定位终端，请先在列表里勾选"
        items = [self._check_item(entry_id, action) for entry_id in ids]
        affected = sum(1 for item in items if item["可处理"])
        return {
            "动作": action,
            "提交台数": len(items),
            "可处理台数": affected,
            "跳过台数": len(items) - affected,
            "明细": items,
        }, ""

    def run_batch(
        self,
        action: str,
        entry_ids: list[Any],
        *,
        request_id: str | None = None,
        operator: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """整组提交：逐台校验，不满足条件的原样跳过并回执原因，其余照常处理。

        request_id 是幂等键：重复提交直接返回首次结果，不重复生效。
        """
        if request_id and request_id in self._receipts:
            cached = dict(self._receipts[request_id])
            cached["重复提交"] = True
            cached["message"] = "该批次已提交过，本次未重复生效"
            return cached, ""
        preview, error = self.preview_batch(action, entry_ids)
        if preview is None:
            return None, error
        receipts: list[dict[str, Any]] = []
        done = 0
        shift_closed = 0
        for item in preview["明细"]:
            receipt = dict(item)
            if not item["可处理"]:
                receipt["结果"] = "跳过"
                receipts.append(receipt)
                continue
            entry = store.find(MODULE, int(item["id"]))
            # 提交瞬间再校验一次，防止核对到提交之间状态已变化。
            reason = BATCH_SKIP_REASONS[action].get(str(entry.get("status", "")), "") if entry else "终端已不存在"
            if entry is None or reason:
                receipt["结果"] = "跳过"
                receipt["原因"] = reason
                receipts.append(receipt)
                continue
            self._apply_action(entry, action)
            closed = 0
            if ACTION_RULES[action] in UNTRACKED_STATUSES:
                closed = self._shift.close_in_mine_for_carrier(
                    str(entry.get("携带人员", "")),
                    note=f"终端{entry.get('终端编号', '')}{action}，系统同步销记在井记录",
                )
            shift_closed += closed
            done += 1
            receipt["结果"] = "成功"
            receipt["同步销记在井记录"] = closed
            receipts.append(receipt)
        skipped = len(receipts) - done
        ledger = self._append_ledger(
            action=action,
            total=len(receipts),
            done=done,
            skipped=skipped,
            shift_closed=shift_closed,
            operator=operator or "值班管理员",
            request_id=request_id or "",
            receipts=receipts,
        )
        result = {
            "动作": action,
            "提交台数": len(receipts),
            "成功台数": done,
            "跳过台数": skipped,
            "在井人数变动": -shift_closed,
            "台账编号": ledger["台账编号"],
            "回执": receipts,
            "重复提交": False,
            "message": f"批量{action}完成：成功 {done} 台，跳过 {skipped} 台",
        }
        if request_id:
            if len(self._receipts) >= MAX_RECEIPTS:
                self._receipts.pop(next(iter(self._receipts)))
            self._receipts[request_id] = {key: value for key, value in result.items() if key != "message"}
        return result, ""

    def _append_ledger(self, *, action: str, total: int, done: int, skipped: int,
                       shift_closed: int, operator: str, request_id: str,
                       receipts: list[dict[str, Any]]) -> dict[str, Any]:
        """每批处置写一条值班台账，逐台回执随台账留痕。"""
        entry = {
            "台账编号": f"LEDG-{len(self._ledger) + 1:04d}",
            "处置动作": action,
            "提交台数": total,
            "成功台数": done,
            "跳过台数": skipped,
            "在井人数变动": -shift_closed,
            "办理人": operator,
            "办理时间": _now(),
            "请求编号": request_id,
            "明细": receipts,
        }
        self._ledger.insert(0, entry)
        return entry

    def list_ledger(self) -> list[dict[str, Any]]:
        return list(self._ledger)

    def list_carriers(self) -> list[dict[str, Any]]:
        """携带人员名单：由定位终端实时汇总，批量处置后跟着变。"""
        in_mine = self._shift.in_mine_carriers()
        carriers = []
        for row in store.rows(MODULE):
            carrier = str(row.get("携带人员", ""))
            carriers.append({
                "携带人员": carrier,
                "终端编号": row.get("终端编号", ""),
                "终端状态": row.get("status", ""),
                "是否在井": "是" if carrier in in_mine else "否",
                "最近处置": row.get("最近处置", "—"),
                "最近处置时间": row.get("最近处置时间", "—"),
            })
        return carriers
