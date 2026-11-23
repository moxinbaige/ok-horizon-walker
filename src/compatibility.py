"""Non-consuming comparison against the two upstream input implementations.

No SendInput, SetForegroundWindow, injection, or foreground fallback is used.
The only UI actions are opening the checklist and returning via its home icon.
"""
import ctypes
from datetime import datetime
import json
import time

import win32api
import win32con
import win32gui
from ok import GenshinInteraction

from src.vision import ROOT


def nte_reference_click(interaction, x, y):
    """Reproduce NTEInteraction.click's message order and restoration delay."""
    saved = win32api.GetCursorPos()
    try:
        interaction.try_activate()
        abs_x, abs_y = interaction.capture.get_abs_cords(x, y)
        win32api.SetCursorPos((int(abs_x), int(abs_y)))
        time.sleep(0.035)
        pos = win32api.MAKELONG(x, y)
        win32gui.PostMessage(interaction.hwnd_window.hwnd, win32con.WM_LBUTTONDOWN,
                             win32con.MK_LBUTTON, pos)
        time.sleep(0.01)
        win32gui.PostMessage(interaction.hwnd_window.hwnd, win32con.WM_LBUTTONUP, 0, pos)
        time.sleep(0.035)
    finally:
        win32api.SetCursorPos(saved)


def compare_backends(task):
    current = task.executor.interaction
    hwnd = current.hwnd_window.hwnd
    result = {
        "at": datetime.now().isoformat(), "success": False, "status": "running",
        "process_is_admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "window_class": win32gui.GetClassName(hwnd),
        "client_rect": list(win32gui.GetClientRect(hwnd)),
        "tests": [],
    }
    report = ROOT / "docs/compatibility_result.json"

    def save():
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    if not result["process_is_admin"]:
        result["status"] = "administrator_required"
        save()
        task.fail("请以管理员身份运行兼容性检查")
    if win32gui.IsIconic(hwnd):
        result["status"] = "minimized"
        save()
        task.fail("请恢复游戏窗口，不能最小化")
    reference = None
    try:
        task.observe()
        if task.is_daily():
            result["resumed_from_daily"] = True
            save()
            task.return_home(action=lambda x, y: nte_reference_click(current, x, y))
        if not task.is_home():
            task.fail("兼容性对照需要从带手机菜单的主界面开始")
        for name in ("nte_reference", "genshin_reference"):
            task.observe()
            if not task.is_home():
                task.fail("页面已变化，停止后续对照")
            target = task.templates.find(task.image, "phone_checklist")
            if target is None:
                task.fail("检查清单图标不确定")
            h, w = task.frame.shape[:2]
            x, y = round(target.x*w/1920), round(target.y*h/1080)
            case = {"backend": name, "frame_size": [w, h], "click": [x, y],
                    "template_confidence": target.score,
                    "background_before": win32gui.GetForegroundWindow() != hwnd,
                    "image_before": task.save_evidence(name+"-before")}
            result["tests"].append(case)
            save()
            if name == "nte_reference":
                click = lambda px, py: nte_reference_click(current, px, py)
            else:
                # The same framework backend selected by ok-gf2 for UnityWndClass.
                # Use its unmodified click() activation/input/restoration sequence.
                reference = GenshinInteraction(current.capture, current.hwnd_window)
                click = lambda px, py: reference.click(px, py, move_back=True)
            click(x, y)
            case["background_after_send"] = win32gui.GetForegroundWindow() != hwnd
            deadline = time.monotonic()+8
            while time.monotonic() < deadline:
                task.sleep(0.5)
                task.observe()
                if task.is_daily():
                    break
            case["daily_opened"] = task.is_daily()
            case["still_home"] = task.is_home()
            case["background_after_observe"] = win32gui.GetForegroundWindow() != hwnd
            case["image_after"] = task.save_evidence(name+"-after")
            save()
            if case["daily_opened"]:
                result["working_backend"] = name
                result["background_verified"] = all(case[k] for k in (
                    "background_before", "background_after_send", "background_after_observe"))
                result["score"] = task.score()
                result["chests"] = task.chests()
                # Re-identify the home icon after stable page detection, then
                # verify the destination; bounded retries only on the source.
                task.return_home(action=click)
                result["return_home_verified"] = True
                result["navigation_audit"] = task.navigation_audit
                result["success"] = result["background_verified"]
                result["status"] = "passed" if result["background_verified"] else "menu_opened_background_not_proven"
                task.completed = result["background_verified"]
                save()
                return result
            if not case["still_home"]:
                task.fail("参考输入后出现未知页面，停止对照")
        result["status"] = "both_reference_backends_did_not_open_daily"
        task.fail("两种参考后台输入均未打开检查清单；需要前台对照或其他输入途径")
    except Exception as error:
        result["error"] = str(error)
        result["navigation_audit"] = task.navigation_audit
        if result["status"] == "running":
            result["status"] = "failed"
        save()
        raise
    finally:
        if reference is not None:
            # Upstream on_destroy() raises the game; do not call it in this probe.
            if reference in current.hwnd_window.visible_monitors:
                current.hwnd_window.visible_monitors.remove(reference)
            ctypes.windll.user32.BlockInput(False)
