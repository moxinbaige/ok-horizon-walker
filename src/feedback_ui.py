"""Review screenshots before exporting a local feedback ZIP."""
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                              QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from src.feedback import export_bundle, screenshots


class FeedbackDialog(QDialog):
    def __init__(self, report, root, version, parent=None):
        super().__init__(parent)
        self.report, self.root, self.version = report, root, version
        self.setWindowTitle("生成本次运行反馈包")
        self.resize(760, 650)
        layout = QVBoxLayout(self)
        text = QLabel(f"版本：{version}　运行开始：{report.get('started_at', '')}\n"
                      "将打包本轮运行记录、错误日志和勾选的截图，不会自动上传。\n"
                      "请预览截图，确认昵称、账号等信息是否适合分享；不需要的截图可取消勾选。")
        text.setWordWrap(True)
        layout.addWidget(text)
        errors = QLabel("\n".join(str(error.get("error", "")) for error in report.get("stage_errors", [])))
        errors.setWordWrap(True)
        layout.addWidget(errors)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setMaximumHeight(160)
        container = QWidget()
        choices = QVBoxLayout(container)
        self.choices = []
        for path in screenshots(report, root):
            check = QCheckBox(path.name)
            check.setChecked(True)
            choices.addWidget(check)
            preview = QPushButton("预览这张截图")
            preview.clicked.connect(lambda checked=False, image=path: self.preview(image))
            choices.addWidget(preview)
            self.choices.append((check, path))
        if not self.choices:
            choices.addWidget(QLabel("没有找到本轮可用截图，仍可导出运行记录。"))
        area.setWidget(container)
        layout.addWidget(area)
        self.image = QLabel("选择“预览这张截图”查看图片")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(220)
        layout.addWidget(self.image, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("生成反馈包")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def preview(self, path):
        pixmap = QPixmap(str(path))
        self.image.setPixmap(pixmap.scaled(700, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def save(self):
        default = self.root / "docs" / ("feedback-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".zip")
        filename, _ = QFileDialog.getSaveFileName(self, "保存反馈包", str(default), "ZIP 压缩包 (*.zip)")
        if not filename:
            return
        try:
            output = export_bundle(self.report, [path for check, path in self.choices if check.isChecked()],
                                   self.root, self.version, filename)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "反馈包未生成", str(error))
            return
        message = QMessageBox(self)
        message.setWindowTitle("反馈包已保存")
        message.setText(f"{output}\n请检查内容后，再自行发送给反馈群。")
        reveal = message.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
        message.addButton("完成", QMessageBox.ButtonRole.AcceptRole)
        message.exec()
        if message.clickedButton() == reveal:
            os.startfile(str(output.parent))
        self.accept()
