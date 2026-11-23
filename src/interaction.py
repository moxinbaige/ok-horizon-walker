"""Window messages with brief cursor positioning for background game input."""
import time

import win32api
import win32con
import win32gui
from ok import PostMessageInteraction


class UndispatchedClick(RuntimeError):
    """No button-down was sent; the caller may re-observe and revalidate."""


class HorizonInteraction(PostMessageInteraction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit = []

    def click(self, x=-1, y=-1, move_back=True, name=None, down_time=0.01,
              move=True, key="left"):
        if key != "left":
            raise ValueError("This routine only uses left clicks")
        hwnd = self.hwnd_window.hwnd
        if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
            raise RuntimeError("游戏已关闭或最小化，请恢复游戏窗口")
        if x < 0 or y < 0:
            raise ValueError("Explicit click coordinates are required")
        saved = win32api.GetCursorPos()
        before = win32gui.GetForegroundWindow() != hwnd
        sent = False
        expected_cursor = None
        cursor_at_down = None
        cursor_at_up = None
        displaced = False
        try:
            self.try_activate()  # WM_ACTIVATE; does not set foreground focus.
            # Position the cursor before dispatching the window click.
            pos = win32api.MAKELONG(int(x), int(y))
            if move:
                abs_x, abs_y = self.capture.get_abs_cords(x, y)
                expected_cursor = (int(abs_x), int(abs_y))
                win32api.SetCursorPos((int(abs_x), int(abs_y)))
                time.sleep(0.035)
            cursor_at_down = win32api.GetCursorPos()
            if expected_cursor is not None and any(
                    abs(actual-expected) > 2 for actual, expected in zip(cursor_at_down, expected_cursor)):
                displaced = True
                raise UndispatchedClick(f"鼠标位置校验未通过，目标 {expected_cursor}，实际 {cursor_at_down}，未发送点击")
            self.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, pos, hwnd=hwnd)
            try:
                time.sleep(down_time)
            finally:
                self.post(win32con.WM_LBUTTONUP, 0, pos, hwnd=hwnd)
                cursor_at_up = win32api.GetCursorPos()
                sent = True
            time.sleep(0.035)
        finally:
            if move_back and not displaced:
                win32api.SetCursorPos(saved)
            self.audit.append({"x": x, "y": y, "background_before": before,
                               "background_after": win32gui.GetForegroundWindow() != hwnd,
                               "messages_sent": sent, "expected_cursor": expected_cursor,
                               "cursor_at_down": cursor_at_down, "cursor_at_up": cursor_at_up})

    def post(self, message, wParam=0, lParam=0, hwnd=None):
        # The framework logs failures by default; this workflow must stop on them.
        win32gui.PostMessage(hwnd or self.hwnd, message, wParam, lParam)

    def swipe(self, x1, y1, x2, y2, duration=500, settle_time=0):
        # BaseTask.swipe converts its seconds argument to milliseconds.
        seconds = duration / 1000
        hwnd = self.hwnd_window.hwnd
        if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
            raise RuntimeError("请恢复游戏窗口")
        saved = win32api.GetCursorPos()
        self.try_activate()
        pos = win32api.MAKELONG(int(x1), int(y1))
        try:
            abs_x, abs_y = self.capture.get_abs_cords(x1, y1)
            win32api.SetCursorPos((int(abs_x), int(abs_y)))
            time.sleep(0.035)
            self.post(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, pos, hwnd=hwnd)
            steps = max(2, int(seconds * 60))
            for index in range(1, steps+1):
                part = index/steps
                x, y = round(x1+(x2-x1)*part), round(y1+(y2-y1)*part)
                abs_x, abs_y = self.capture.get_abs_cords(x, y)
                win32api.SetCursorPos((int(abs_x), int(abs_y)))
                pos = win32api.MAKELONG(x, y)
                self.post(win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, pos, hwnd=hwnd)
                time.sleep(seconds/steps)
        finally:
            self.post(win32con.WM_LBUTTONUP, 0, pos, hwnd=hwnd)
            time.sleep(0.035)
            win32api.SetCursorPos(saved)
        time.sleep(settle_time)
