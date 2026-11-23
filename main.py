import multiprocessing
import os
from pathlib import Path
import sys
import json


def run_app():
    os.chdir(Path(__file__).resolve().parent)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    temp = Path(".tmp").resolve()
    temp.mkdir(exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(temp)
    from ok import OK
    from src.config import make_config
    config = make_config()
    headless = any(arg in sys.argv for arg in ("--inspect", "--capture", "--compatibility", "--daily", "--tribute", "--extras", "--event"))
    if headless:
        config["gui"] = None
        config["use_gui"] = False
    else:
        config["my_app"] = ["src.ui", "DesktopUi"]
    app = OK(config)
    if headless:
        index = 6 if "--extras" in sys.argv else (5 if "--tribute" in sys.argv else (2 if "--daily" in sys.argv else (4 if "--compatibility" in sys.argv else (1 if "--inspect" in sys.argv else 3))))
        if "--event" in sys.argv:
            index = 7
        try:
            task = app.get_onetime_task(index)
            app.run_task(index)
            result = {"success": task.completed, "task": task.name, "info": task.info}
            result["status"] = getattr(task, "run_status", "completed" if task.completed else "stopped")
            result["daily_rewards_complete"] = getattr(task, "daily_rewards_complete", False)
            result["stage_errors"] = getattr(task, "stage_errors", [])
            interaction = app.task_executor.interaction
            result["click_audit"] = getattr(interaction, "audit", [])
            result["navigation_audit"] = task.navigation_audit
            result["action_audit"] = task.action_audit
            result["timings"] = task.timings
            result["stage_timings"] = task.stage_timings
            run_id = os.environ.get("HORIZON_DEBUG_RUN_ID", "")
            if run_id and all(char in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in run_id):
                result["run_id"] = run_id
                Path(f"docs/debug-{run_id}.result.json").write_text(
                    json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            Path("docs/last_run.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            if not task.completed:
                if result["status"] == "partial":
                    raise RuntimeError("部分步骤失败，已尝试后续可执行任务，请查看故障记录")
                raise RuntimeError("检查未通过，请查看本次日志和 screenshots 中的故障截图")
        finally:
            app.quit()
    else:
        app.start()


def main():
    from src.runtime import InstanceOwner
    try:
        with InstanceOwner():
            run_app()
    except Exception as exc:
        if any(arg.startswith("--") for arg in sys.argv[1:]):
            raise
        import traceback
        import ctypes
        log = Path(__file__).resolve().parent / "docs/desktop-startup.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        ctypes.windll.user32.MessageBoxW(None, str(exc)+"\n\n详细信息："+str(log), "每日助手启动失败", 0x10)
        raise


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
