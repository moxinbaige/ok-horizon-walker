from datetime import datetime

from src.interaction import HorizonInteraction


# Set these after the official repository and sponsorship page are confirmed.
GITHUB_REPOSITORY = "moxinbaige/ok-horizon-walker"
SPONSOR_URL = ""


def make_config():
    links = {}
    if GITHUB_REPOSITORY:
        repository_url = f"https://github.com/{GITHUB_REPOSITORY}"
        links.update(github=repository_url, download=f"{repository_url}/releases/latest")
    if SPONSOR_URL:
        links["sponsor"] = SPONSOR_URL
    return {
        "version": "1.0.0",
        "gui_title": "地平线行者每日助手",
        "gui_icon": "assets/app_icon.png",
        "locale": "zh_CN",
        "gui": {"type": "qt"},
        "links": {"default": links},
        "about": "地平线行者每日助手是基于 ok-script 的第三方 Windows 工具。"
                 "正式版本可免费下载，自愿赞助用于支持开发和维护。"
                 '<br><a href="https://github.com/ok-oldking/ok-script">ok-script 项目</a>',
        "use_gui": True,
        "debug": False,
        "config_folder": "configs",
        # Each launch gets its own folder so framework cleanup cannot delete old evidence.
        "screenshots_folder": "screenshots/" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
        "windows": {
            "exe": "HorizonWalker.exe",
            "interaction": [HorizonInteraction],
            "capture_method": ["WGC", "BitBlt_RenderFull"],
            "require_bg": True,
            "start_exe": False,
            "check_hdr": False,
        },
        "ocr": {"default": {"lib": "onnxocr", "params": {
            "use_openvino": False, "use_npu": False}}},
        "supported_resolution": {"ratio": "16:9", "min_size": (1280, 720)},
        "window_size": {"width": 1000, "height": 720, "min_width": 800, "min_height": 600},
        "onetime_tasks": [
            ["src.tasks", "InspectTask"],
            ["src.tasks", "DailyTask"],
            ["src.tasks", "CaptureTask"],
            ["src.tasks", "CompatibilityTask"],
            ["src.tasks", "TributeTask"],
            ["src.tasks", "RecoveryMailTask"],
            ["src.tasks", "EventDailyTask"],
        ],
        "trigger_tasks": [],
        "custom_tabs": [["src.ui", "OverviewTab"]],
        "wait_until_check_delay": 0.4,
        "start_timeout": 60,
    }
