"""人员定位业务规则：状态流转、批量处置、幂等控制与跨模块同步都收在这里。

批量处置的口径：
- 同一批里重复勾选、重复提交，都只生效一次；
- 不满足前置条件的终端原样跳过，逐条给出原因；
- 处置结果同步写入值班台账，并联动入井记录、携带人员名单与在井人数。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "personnel"
SHIFT_MODULE = "shift"
LEDGER_MODULE = "dutylog"
JOURNAL_MODULE = "terminal_action_journal"
BATCH_MODULE = "terminal_action_batch"

REQUIRED_FIELDS = ["终端编号", "携带人员", "所在位置"]
STATUS_ORDER = ["在线", "离线", "低电量", "已更换"]
ACTION_RULES = {"记录离线": "离线", "低电提醒": "低电量", "办理更换": "已更换"}
NEGATIVE_ACTIONS = []
BATCH_LIMIT = 500

# 各动作的前置条件：命中状态即跳过，值就是逐条回执给值班员的原因
SKIP_RULES: dict[str, dict[str, str]] = {
    "记录离线": {
        "离线": "终端已处于离线状态，无需重复记录",
        "已更换": "终端已换卡停用，不再上报在线状态",
    },
    "低电提醒": {
        "低电量": "已发送过低电提醒，请勿重复提醒",
        "已更换": "终端已办理更换，低电提醒不再下发",
    },
    "办理更换": {
        "离线": "终端不在线，换卡指令无法送达，待恢复在线后再办理",
        "已更换": "该终端已换过卡，请勿重复办理",
    },
}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PersonnelService:
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

    # ---- 单台处置 --------------------------------------------------------

    def run_action(
        self, entry_id: int, action: str, *, operator: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"定位终端 {entry_id} 不存在或已归档"
        message = self._validate_action(action)
        if message:
            return None, message
        reason = self._skip_reason(action, str(entry.get("status")))
        if reason:
            return None, reason
        now = _now_text()
        self._apply(entry, action, now)
        self._sync_shift(action, entry, now)
        self._write_journal(entry, action, "", operator, now)
        self._append_ledger(action, [entry], [], 1, "", operator, now)
        return entry, f"定位终端已{action}"

    # ---- 批量处置 --------------------------------------------------------

    def fetch_selection(self, raw_ids: list[int]) -> dict[str, Any]:
        """按 id 清单重新回捞终端最新数据，供跨页勾选后提交前核对。"""
        unique_ids = self._dedupe(raw_ids)
        terminals = []
        missing_ids: list[int] = []
        for terminal_id in unique_ids:
            entry = store.find(MODULE, terminal_id)
            if entry is None:
                missing_ids.append(terminal_id)
            else:
                terminals.append(self._brief(entry))
        return {
            "selected": len(unique_ids),
            "duplicates": len(raw_ids) - len(unique_ids),
            "terminals": terminals,
            "missing_ids": missing_ids,
        }

    def preview_batch(self, action: str, raw_ids: list[int]) -> tuple[dict[str, Any] | None, str]:
        """提交前试算：去重后台数、预计生效台数、逐台跳过原因，全部按当前最新状态回算。"""
        message = self._validate_action(action)
        if message:
            return None, message
        if not raw_ids:
            return None, "未勾选任何定位终端，请先勾选后再提交"
        if len(raw_ids) > BATCH_LIMIT:
            return None, f"单批最多 {BATCH_LIMIT} 台，请分批提交"
        unique_ids = self._dedupe(raw_ids)
        selection = self.fetch_selection(raw_ids)
        receipts = self._dry_run(action, unique_ids)
        affected = sum(1 for item in receipts if item["result"] == "succeeded")
        return {
            "action": action,
            "selected": len(unique_ids),
            "duplicates": len(raw_ids) - len(unique_ids),
            "affected": affected,
            "skipped": sum(1 for item in receipts if item["result"] != "succeeded"),
            "terminals": selection["terminals"],
            "missing_ids": selection["missing_ids"],
            "receipts": receipts,
        }, ""

    def run_batch(
        self,
        action: str,
        raw_ids: list[int],
        *,
        batch_no: str | None = None,
        operator: str | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        message = self._validate_action(action)
        if message:
            return None, message
        if not raw_ids:
            return None, "未勾选任何定位终端，请先勾选后再提交"
        if len(raw_ids) > BATCH_LIMIT:
            return None, f"单批最多 {BATCH_LIMIT} 台，请分批提交"

        unique_ids = self._dedupe(raw_ids)
        request_hash = self._request_hash(action, unique_ids)

        # 重复提交：同动作 + 同一组终端（与提交顺序、重复勾选无关）只生效一次，回放首次回执
        id_set = set(unique_ids)
        for batch in store.rows(BATCH_MODULE):
            if batch.get("status") != "done" or batch.get("action") != action:
                continue
            if set(batch.get("terminal_ids", [])) == id_set:
                result = dict(batch["result"])
                result["replayed"] = True
                return result, ""

        now = _now_text()
        batch_no = batch_no or f"BAT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{request_hash[:6]}"
        batch_row = {
            "id": max((int(row.get("id", 0)) for row in store.rows(BATCH_MODULE)), default=0) + 1,
            "batch_no": batch_no,
            "action": action,
            "request_hash": request_hash,
            "terminal_ids": unique_ids,
            "status": "running",
            "created_at": now,
        }
        store.rows(BATCH_MODULE).append(batch_row)

        receipts: list[dict[str, Any]] = []
        succeeded_entries: list[dict[str, Any]] = []
        for terminal_id in unique_ids:
            entry = store.find(MODULE, terminal_id)
            if entry is None:
                receipts.append(self._receipt(terminal_id, None, "not_found",
                                              "终端不存在或已归档", None, None))
                continue
            before = str(entry.get("status"))
            reason = self._skip_reason(action, before)
            if reason:
                receipts.append(self._receipt(terminal_id, entry, "skipped", reason, before, before))
                continue
            self._apply(entry, action, now)
            self._sync_shift(action, entry, now)
            self._write_journal(entry, action, batch_no, operator, now)
            succeeded_entries.append(entry)
            receipts.append(self._receipt(terminal_id, entry, "succeeded", None, before,
                                          str(entry.get("status"))))

        succeeded = len(succeeded_entries)
        skipped = len(receipts) - succeeded
        ledger = self._append_ledger(action, succeeded_entries, receipts, len(unique_ids),
                                     batch_no, operator, now, remark)

        result = {
            "ok": True,
            "replayed": False,
            "batch_no": batch_no,
            "action": action,
            "message": f"批量{action}完成：生效 {succeeded} 台，跳过 {skipped} 台",
            "selected": len(unique_ids),
            "duplicates": len(raw_ids) - len(unique_ids),
            "succeeded": succeeded,
            "skipped": skipped,
            "receipts": receipts,
            "ledger": ledger,
            "operator": operator or "值班管理员",
            "finished_at": now,
        }
        batch_row["status"] = "done"
        batch_row["result"] = result
        return result, ""

    # ---- 统计与名单 ------------------------------------------------------

    def stats(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = str(row.get("status"))
            if status in counts:
                counts[status] += 1
        counts["在册终端"] = len(store.rows(MODULE))
        counts["携带人员名单"] = sum(1 for row in store.rows(MODULE) if row.get("status") != "已更换")
        return counts

    def carriers(self) -> dict[str, Any]:
        """携带人员名单：只列未停用（未换卡）终端的携带人，换卡后自动出名单。"""
        shift_by_device = {
            str(row.get("携带设备", "")): row for row in store.rows(SHIFT_MODULE)
        }
        items = []
        for row in store.rows(MODULE):
            if row.get("status") == "已更换":
                continue
            shift_row = shift_by_device.get(str(row.get("终端编号", "")))
            items.append({
                "终端编号": row.get("终端编号"),
                "携带人员": row.get("携带人员"),
                "所在位置": row.get("所在位置"),
                "终端状态": row.get("status"),
                "所属班组": (shift_row or {}).get("所属班组", ""),
                "入井状态": (shift_row or {}).get("status", ""),
            })
        return {"total": len(items), "items": items}

    # ---- 内部辅助 --------------------------------------------------------

    def _validate_action(self, action: str) -> str:
        if action not in ACTION_RULES:
            return f"动作「{action}」不属于人员定位可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return f"目标状态「{target}」不在允许的状态序列里"
        return ""

    def _skip_reason(self, action: str, status: str) -> str | None:
        return SKIP_RULES.get(action, {}).get(status)

    def _dedupe(self, raw_ids: list[int]) -> list[int]:
        """同一批重复勾到同一台只算一次，保留首次出现顺序。"""
        seen: set[int] = set()
        unique: list[int] = []
        for terminal_id in raw_ids:
            if terminal_id not in seen:
                seen.add(terminal_id)
                unique.append(terminal_id)
        return unique

    def _request_hash(self, action: str, unique_ids: list[int]) -> str:
        raw = f"{action}|{','.join(str(terminal_id) for terminal_id in unique_ids)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _dry_run(self, action: str, unique_ids: list[int]) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        for terminal_id in unique_ids:
            entry = store.find(MODULE, terminal_id)
            if entry is None:
                receipts.append(self._receipt(terminal_id, None, "not_found",
                                              "终端不存在或已归档", None, None))
                continue
            before = str(entry.get("status"))
            reason = self._skip_reason(action, before)
            if reason:
                receipts.append(self._receipt(terminal_id, entry, "skipped", reason, before, before))
            else:
                target = ACTION_RULES[action]
                receipts.append(self._receipt(terminal_id, entry, "succeeded", None, before, target))
        return receipts

    def _apply(self, entry: dict[str, Any], action: str, now: str) -> None:
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["终端状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["最后处置"] = f"{action} {now}"

    def _sync_shift(self, action: str, terminal: dict[str, Any], now: str) -> None:
        """联动入井管理：离线转超时未升仍计在井；换卡停用按升井处理，在井人数随之减少。"""
        record = self._find_shift_for(terminal)
        if record is None:
            return
        if action == "办理更换" and record.get("status") in ("入井中", "超时未升"):
            record["status"] = "已升井"
            record["入井状态"] = "已升井"
            record["升井时间"] = now
            record["pending"] = False
            record["abnormal"] = False
            record["联动备注"] = f"终端{action}，按升井注销在井登记"
        elif action == "记录离线" and record.get("status") == "入井中":
            record["status"] = "超时未升"
            record["入井状态"] = "超时未升"
            record["abnormal"] = True
            record["联动备注"] = f"终端{action}，列入超时未升名单"

    def _find_shift_for(self, terminal: dict[str, Any]) -> dict[str, Any] | None:
        device_code = str(terminal.get("终端编号", ""))
        carrier = str(terminal.get("携带人员", ""))
        fallback: dict[str, Any] | None = None
        for row in store.rows(SHIFT_MODULE):
            if str(row.get("携带设备", "")) == device_code:
                return row
            if fallback is None and str(row.get("入井人员", "")) == carrier:
                fallback = row
        return fallback

    def _write_journal(
        self, entry: dict[str, Any], action: str, batch_no: str,
        operator: str | None, now: str,
    ) -> None:
        rows = store.rows(JOURNAL_MODULE)
        rows.append({
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "terminal_id": entry.get("id"),
            "终端编号": entry.get("终端编号"),
            "action": action,
            "batch_no": batch_no,
            "operator": operator or "值班管理员",
            "created_at": now,
        })

    def _append_ledger(
        self,
        action: str,
        succeeded_entries: list[dict[str, Any]],
        receipts: list[dict[str, Any]],
        total: int,
        batch_no: str,
        operator: str | None,
        now: str,
        remark: str | None = None,
    ) -> dict[str, Any]:
        """处置结果同步到人员定位值班台账。"""
        rows = store.rows(LEDGER_MODULE)
        succeeded = len(succeeded_entries)
        skipped = total - succeeded
        scope = "批量" if total > 1 or batch_no else "单台"
        ledger = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": "已登记",
            "pending": True,
            "abnormal": skipped > 0,
            "台账编号": f"DUTY-{len(rows) + 1:04d}",
            "处置事项": f"{scope}{action}",
            "批次号": batch_no,
            "动作": action,
            "涉及终端数": total,
            "成功台数": succeeded,
            "跳过台数": skipped,
            "终端清单": "、".join(str(entry.get("终端编号")) for entry in succeeded_entries),
            "值班人员": operator or "值班管理员",
            "处置时间": now,
            "备注": remark or "",
            "跳过明细": [
                {"终端编号": item.get("终端编号"), "携带人员": item.get("携带人员"),
                 "原因": item.get("reason")}
                for item in receipts if item.get("result") != "succeeded"
            ],
        }
        rows.append(ledger)
        return ledger

    def _brief(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": entry.get("id"),
            "终端编号": entry.get("终端编号"),
            "携带人员": entry.get("携带人员"),
            "所在位置": entry.get("所在位置"),
            "status": entry.get("status"),
        }

    def _receipt(
        self, terminal_id: int, entry: dict[str, Any] | None, result: str,
        reason: str | None, before: str | None, after: str | None,
    ) -> dict[str, Any]:
        return {
            "terminal_id": terminal_id,
            "终端编号": (entry or {}).get("终端编号", f"PERS-{terminal_id:04d}"),
            "携带人员": (entry or {}).get("携带人员", "—"),
            "result": result,
            "reason": reason,
            "before_status": before,
            "after_status": after,
        }
