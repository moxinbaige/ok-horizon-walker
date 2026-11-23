"""Local run evidence and a process-wide owner for game automation."""
from datetime import datetime
from functools import wraps
import json
import time

from src.vision import ROOT
from ok.task.exceptions import TaskDisabledException
from src.stage_recovery import record_error, result_label


def record_run(function):
    @wraps(function)
    def run(task, *args, **kwargs):
        # Unit fixtures without the framework are intentionally not persisted.
        persist = getattr(task, "_record_evidence", False)
        task.completed = False
        task.navigation_audit = []
        task.action_audit = []
        task.timings = {}
        task.stage_timings = []
        task.stage_errors = []
        task._last_stage_exception = None
        task.stage = "startup"
        task.daily_rewards_complete = False
        task.run_status = "running"
        task.templates.stats = {"count": 0, "seconds": 0.0}
        task.info.clear()
        task.run_options = dict(getattr(task, "config", None) or {})
        run_start = getattr(task, "start_time", None)
        started = time.perf_counter()
        started_at = datetime.now().isoformat()
        error = None
        try:
            return function(task, *args, **kwargs)
        except Exception as exc:
            error = str(exc)
            task.info["停止原因"] = error
            if not isinstance(exc, TaskDisabledException) and task._last_stage_exception is not exc:
                record_error(task, getattr(task, "stage", "startup"), exc)
            raise
        finally:
            elapsed = round(time.perf_counter()-started, 3)
            if error is not None:
                task.completed = False
                task.run_status = "stopped"
            elif task.stage_errors:
                task.completed = False
                task.run_status = "partial"
            else:
                task.run_status = "completed" if task.completed else "stopped"
            task.info["运行结果"] = result_label({"status": task.run_status, "success": task.completed,
                                                 "daily_rewards_complete": task.daily_rewards_complete})
            task.finished_run_timing = (run_start, elapsed)
            if persist:
                result = {
                    "started_at": started_at,
                    "success": task.completed, "error": error,
                    "status": task.run_status, "daily_rewards_complete": task.daily_rewards_complete,
                    "stage_errors": task.stage_errors,
                    "elapsed_seconds": elapsed,
                    "components": dict(task.timings, template_matching=task.templates.stats),
                    "stages": task.stage_timings,
                    "actions": task.action_audit, "navigation": task.navigation_audit,
                    "options": task.run_options, "info": task.info,
                }
                folder = ROOT / "docs"
                filename = "timing-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".json"
                data = json.dumps(result, ensure_ascii=False, indent=2)
                (folder / filename).write_text(data, encoding="utf-8")
                (folder / "timing-latest.json").write_text(data, encoding="utf-8")
                task.info["耗时记录"] = str(folder / filename)
    return run


class InstanceOwner:
    """Windows mutex is released by the OS even after an abnormal exit."""
    NAME = r"Local\HorizonWalkerDailyAssistant"

    def __enter__(self):
        import win32api
        import win32event
        import winerror
        self.handle = win32event.CreateMutex(None, False, self.NAME)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            win32api.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError("每日助手已经在运行，请先使用现有窗口或关闭旧实例。")
        return self

    def __exit__(self, *_):
        import win32api
        if self.handle:
            win32api.CloseHandle(self.handle)
