"""Classified step failures, immediate evidence, and bounded safe recovery."""
from datetime import datetime
import json
import traceback

from ok.task.exceptions import TaskDisabledException

from src.vision import ROOT


class RoutineError(RuntimeError):
    pass


class RecoverableStageError(RoutineError):
    """A known non-consuming navigation or target-recognition failure."""


RECOVERABLE_STAGES = {"sign_in", "resources", "shop", "wishes", "raids", "recovery", "mail", "event",
                      "event_sign_in", "event_sweeps", "event_rewards"}


def persist_error(task, entry):
    if getattr(task, "_record_evidence", False):
        path = ROOT / "docs" / entry["record"]
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        path.with_suffix(".log").write_text(entry["traceback"], encoding="utf-8")


def record_error(task, stage, error):
    if not hasattr(task, "stage_errors"):
        task.stage_errors = []
    image = getattr(error, "evidence", None)
    if image is None and task.image is not None:
        image = task.save_evidence("stage-"+stage+"-failure")
    entry = {"stage": stage, "at": datetime.now().isoformat(), "error": str(error),
             "error_type": type(error).__name__, "screenshot": str(image) if image else None,
             "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
             "actions": [dict(a) for a in getattr(task, "action_audit", [])],
             "navigation": [dict(a) for a in getattr(task, "navigation_audit", [])],
             "disposition": "stopped", "home_confirmed": False,
             "record": "stage-error-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f-")+stage+".json"}
    task.stage_errors.append(entry)
    task._last_stage_exception = error
    task.info["失败步骤"] = [e["stage"] for e in task.stage_errors]
    persist_error(task, entry)  # Evidence must exist before any recovery input.
    return entry


def pending_consumption(task):
    if any(a.get("dispatched") and not a.get("confirmed") and not a.get("undispatched")
           for a in getattr(task, "action_audit", [])):
        return True
    paths = (getattr(task, "journal_path", ROOT / "configs/purchase_journal.json"),
             ROOT / "configs/event_journal.json")
    for path in paths:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("state") == "pending" or state.get("pending"):
                return True
    return False


def recover_step(task, stage, error):
    entry = record_error(task, stage, error)
    if not isinstance(error, RecoverableStageError) or stage not in RECOVERABLE_STAGES:
        return False
    try:
        if entry["screenshot"] is None:
            entry["recovery_error"] = "没有可保存的故障画面"
            return False
        if pending_consumption(task):
            entry["recovery_error"] = "存在未核实的消耗或领取结果"
            return False
        task.observe()
        if any(task.has(t) for t in ("CLEAR", "GetItem", "点击屏幕继续")) \
                or task.templates.find(task.image, "battle_pause") is not None:
            entry["recovery_error"] = "仍在战斗或未退出的结算中"
            return False
        task.home()  # Existing recognized menus only; no extra retry loop.
        task.wait(task.is_home, "故障恢复后确认首页", seconds=15)
        if pending_consumption(task):
            entry["recovery_error"] = "恢复后仍存在未核实结果"
            return False
        entry["recovery_screenshot"] = str(task.save_evidence("stage-"+stage+"-recovered-home"))
        entry["home_confirmed"] = True
        entry["disposition"] = "skipped_error"
        task.info["故障恢复"] = stage+"失败，已确认首页并继续后续任务"
        return True
    except TaskDisabledException:
        entry["recovery_error"] = "用户停止运行"
        raise
    except Exception as recovery_error:
        entry["recovery_error"] = str(recovery_error)
        return False
    finally:
        persist_error(task, entry)


def result_label(data):
    if data.get("status") == "partial":
        return "每日奖励已领，部分步骤失败" if data.get("daily_rewards_complete") else "部分完成"
    return "已完成" if data.get("success") else "已停止"
