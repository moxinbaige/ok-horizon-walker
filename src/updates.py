"""Read public release metadata for the desktop About page."""
import json
import re

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, PrimaryPushButton, PushButton


def version_number(tag):
    match = re.fullmatch(r"v?([0-9]{1,9})\.([0-9]{1,9})\.([0-9]{1,9})", tag)
    if match is None:
        raise ValueError("Expected a stable version tag")
    return tuple(map(int, match.groups()))


class ReleaseCheck(QWidget):
    new_version_available = Signal(bool)

    def __init__(self, version, repository):
        super().__init__()
        self.version = version
        self.repository = repository if re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository) else ""
        self.release_url = QUrl(f"https://github.com/{self.repository}/releases/latest")
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.timed_out = False
        self.startup = QTimer(self)
        self.startup.setSingleShot(True)
        self.startup.timeout.connect(self.check)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.cancel_timed_out_request)

        self.status = BodyLabel(f"当前版本 {version}")
        self.status.setWordWrap(True)
        self.check_button = PushButton(FluentIcon.SYNC, "检查更新")
        self.check_button.clicked.connect(self.check)
        self.download_button = PrimaryPushButton(FluentIcon.DOWNLOAD, "前往下载")
        self.download_button.clicked.connect(lambda: QDesktopServices.openUrl(self.release_url))
        self.download_button.hide()
        layout = QHBoxLayout(self)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.check_button)
        layout.addWidget(self.download_button)
        if self.repository:
            self.startup.start(1500)
        else:
            self.check_button.setEnabled(False)
            self.status.setText(f"当前版本 {version}。正式发布源待配置。")

    def check(self):
        self.startup.stop()
        if not self.repository or self.reply is not None:
            return
        self.status.setText("正在检查更新…")
        self.check_button.setEnabled(False)
        self.timed_out = False
        request = QNetworkRequest(QUrl(f"https://api.github.com/repos/{self.repository}/releases/latest"))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"HorizonDaily")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self.reply = self.network.get(request)
        self.reply.finished.connect(self.finish)
        self.deadline.start(8000)

    def cancel_timed_out_request(self):
        if self.reply is not None:
            self.timed_out = True
            self.reply.abort()

    def finish(self):
        reply = self.reply
        self.reply = None
        self.deadline.stop()
        self.check_button.setEnabled(True)
        try:
            if self.timed_out:
                self.status.setText("检查更新超时。可以稍后重试。")
                return
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 404:
                message = "没有可查询的正式版本。"
            elif status in (403, 429):
                message = "GitHub 暂时拒绝请求。可以稍后重试。"
            elif reply.error() != QNetworkReply.NetworkError.NoError:
                message = "无法连接发布源。可以稍后重试。"
            else:
                try:
                    release = json.loads(bytes(reply.readAll()))
                    if release["draft"] is not False or release["prerelease"] is not False:
                        raise ValueError("Expected a stable release")
                    latest = version_number(release["tag_name"])
                    newer = latest > version_number(self.version)
                except (KeyError, TypeError, ValueError):
                    message = "无法识别正式发布版本。"
                else:
                    self.download_button.setVisible(newer)
                    self.new_version_available.emit(newer)
                    tag = release["tag_name"]
                    message = f"发现新版本 {tag}。" if newer else "当前已经是最新版本。"
            self.status.setText(f"当前版本 {self.version}。{message}")
        finally:
            reply.deleteLater()
