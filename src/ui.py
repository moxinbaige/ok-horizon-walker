"""A small desktop overview; task configuration uses the framework's own cards."""
import json
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QMessageBox
from qfluentwidgets import BodyLabel, FluentIcon, PrimaryPushButton, PushButton, TitleLabel
from ok import og
from ok.util.GlobalConfig import NOTIFICATION_OPTION_NAME, SYSTEM_NOTIFICATION_ENABLED
from ok.ui.qt.widget.CustomTab import CustomTab

from src.config import GITHUB_REPOSITORY, make_config
from src.feedback import has_failures, read_report
from src.feedback_ui import FeedbackDialog
from src.tasks import DailyTask
from src.settings import ACTIVITY_SCORE_NOTE
from src.updates import ReleaseCheck
from src.stage_recovery import result_label
from src.vision import ROOT


STAGES = {"sign_in": "签到", "resources": "贡品与资源", "shop": "每日商店",
          "wishes": "金币愿望", "raids": "讨伐", "post_raids": "复原与邮件",
          "recovery": "复原作战", "mail": "邮件", "event": "活动每日",
          "event_sign_in": "活动签到", "event_sweeps": "活动扫荡", "event_rewards": "活动领奖",
          "daily_rewards": "每日奖励"}


class DesktopUi:
    def __init__(self, exit_event):
        notification = og.global_config.config_options[NOTIFICATION_OPTION_NAME]
        notification.config_type = {
            key: {"hidden": True} for key in notification.default_config
            if key != SYSTEM_NOTIFICATION_ENABLED
        }
        notification.description = "通知会显示在助手内。可选择是否同时显示 Windows 系统通知。"

    def on_show_main_window(self, window):
        tab = window.onetime_tab
        for card in tab.card_widgets:
            if isinstance(card.task, DailyTask):
                card.config_widget_by_key["安全导航重试次数"].title.setText("安全导航尝试次数")
                activity = card.config_widget_by_key["活动每日"]
                note = QLabel(ACTIVITY_SCORE_NOTE, activity)
                note.setWordWrap(True)
                note.setStyleSheet("color: #d13438;")
                activity.title_layout.addWidget(note)
                card.update_config()
                card.setExpand(True)
                break
        # The framework refreshes the task info before this callback.
        tab.timer.timeout.connect(lambda: self.show_final_daily_time(tab))

        about = window.about_tab
        if about.update_card is not None:
            # The portable launcher checks GitHub Releases directly.
            about.update_card.parentWidget().parentWidget().hide()
            about.update_card = None
        release_check = ReleaseCheck(window.config["version"], GITHUB_REPOSITORY)
        release_check.new_version_available.connect(window._set_about_update_available)
        card = about.add_card("应用更新", release_check)
        about.vBoxLayout.insertWidget(1, card)

    @staticmethod
    def show_final_daily_time(tab):
        task = tab.last_task
        if not isinstance(task, DailyTask) or task.running or task.enabled:
            return
        timing = getattr(task, "finished_run_timing", None)
        if timing is None or timing[0] != task.start_time:
            return
        hours, remainder = divmod(int(timing[1]), 3600)
        minutes, seconds = divmod(remainder, 60)
        title = f"{task.info['运行结果']}: {tab.tr(task.name)} {tab.tr('Time Elapsed')}: {hours}h {minutes}m {seconds}s"
        tab.task_info_container.titleLabel.setText(title)


class OverviewTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.add_widget(TitleLabel("地平线行者每日助手"))
        self.add_widget(BodyLabel("在左侧任务页的“每日任务”中可保存任务开关和运行速度。\n"
                                  "游戏可以被遮挡，请保持窗口展开。F9 可停止运行。"))
        self.status = BodyLabel("等待开始")
        self.status.setWordWrap(True)
        self.add_card("运行状态", self.status)
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "开始每日任务")
        self.start_button.clicked.connect(self.start_daily)
        self.add_widget(self.start_button)
        self.stop_button = PushButton(FluentIcon.CANCEL, "停止当前任务")
        self.stop_button.clicked.connect(self.stop_current)
        self.add_widget(self.stop_button)
        for title, folder in (("打开运行记录", "docs"), ("打开错误截图", "screenshots")):
            button = PushButton(FluentIcon.FOLDER, title)
            button.clicked.connect(lambda checked=False, name=folder: os.startfile(str(ROOT / name)))
            self.add_widget(button)
        self.summary = BodyLabel("完成一轮后，这里会显示总耗时和各步骤耗时。")
        self.summary.setWordWrap(True)
        self.add_card("最近一次运行", self.summary)
        self._report_mtime = None
        self._feedback_report = read_report(ROOT)
        self._prompted_run = self._feedback_report.get("started_at")
        self.feedback_button = PushButton(FluentIcon.FOLDER, "生成最近一次运行反馈包")
        self.feedback_button.clicked.connect(self.generate_feedback)
        self.feedback_button.setEnabled(False)
        self.add_widget(self.feedback_button)
        self.vBoxLayout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(750)

    @property
    def name(self):
        return "运行概览"

    @property
    def icon(self):
        return FluentIcon.HOME

    @property
    def add_after_default_tabs(self):
        return False

    def start_daily(self):
        if self.executor and not any(t.enabled or t.running for t in self.executor.onetime_tasks):
            og.app.start_controller.start(self.get_task(DailyTask))

    def stop_current(self):
        if self.executor:
            for task in self.executor.onetime_tasks:
                if task.enabled or task.running:
                    task.disable()
                    task.unpause()

    def generate_feedback(self):
        if self.executor and any(t.enabled or t.running for t in self.executor.onetime_tasks):
            return
        if has_failures(self._feedback_report):
            FeedbackDialog(self._feedback_report, ROOT, make_config()["version"], self.window()).exec()

    def check_feedback(self, active):
        failed = has_failures(self._feedback_report)
        self.feedback_button.setEnabled(active is None and failed)
        run = self._feedback_report.get("started_at")
        if active is not None or not failed or not run or run == self._prompted_run:
            return
        # Mark before showing a modal dialog: its nested event loop runs this timer too.
        self._prompted_run = run
        answer = QMessageBox.question(self.window(), "本次运行遇到问题",
                                      "是否生成反馈包？可先预览并选择截图，反馈包只保存在本机。",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.generate_feedback()

    def refresh(self):
        if not self.executor:
            return
        active = next((t for t in self.executor.onetime_tasks if t.enabled or t.running), None)
        self.start_button.setEnabled(active is None)
        self.stop_button.setEnabled(active is not None)
        if active:
            stage = active.info.get("当前步骤", "正在准备游戏窗口")
            self.status.setText(active.name+" · "+STAGES.get(stage, stage))
        else:
            task = self.get_task(DailyTask)
            self.status.setText(task.info.get("停止原因") or task.info.get("运行结果") or task.info.get("Log") or "等待开始")
        report = ROOT / "docs/timing-latest.json"
        if not report.exists() or report.stat().st_mtime_ns == self._report_mtime:
            self.check_feedback(active)
            return
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._report_mtime = report.stat().st_mtime_ns
        self._feedback_report = data
        elapsed = data["elapsed_seconds"]
        lines = [result_label(data)+f" · {int(elapsed)//60}分{int(elapsed)%60}秒"]
        lines.extend(f"{STAGES.get(s['stage'], s['stage'])}：{s['seconds']:.1f}秒"
                     for s in data["stages"] if s["stage"] != "post_raids")
        if data.get("error"):
            lines.append(data["error"])
        for failure in data.get("stage_errors", []):
            stage = STAGES.get(failure["stage"], failure["stage"])
            lines.append(stage+"："+failure["error"])
            if failure.get("home_confirmed"):
                lines.append("已返回首页并继续执行后续任务")
            elif failure.get("recovery_error"):
                lines.append("恢复未完成："+failure["recovery_error"])
        self.summary.setText("\n".join(lines))
        self.check_feedback(active)
