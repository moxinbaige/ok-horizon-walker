"""Build a local folder with a real Python runtime; never copy account state."""
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def copy_runtime_assets(destination):
    """Copy only assets consumed by the app, not private full-frame fixtures."""
    from src.config import make_config
    source = ROOT / "assets"
    metadata = json.loads((source / "templates.json").read_text(encoding="utf-8"))
    if any(re.fullmatch(r"[a-z0-9_]+", name) is None for name in metadata):
        raise ValueError("Invalid runtime template name")
    names = {"templates.json"} | {name+".png" for name in metadata}
    icon = ROOT / make_config()["gui_icon"]
    if icon.parent != source:
        raise ValueError("The desktop icon must be in assets/")
    names.add(icon.name)
    target = destination / "assets"
    target.mkdir()
    for name in sorted(names):
        shutil.copy2(source / name, target / name)
    return sorted(names)


def build():
    destination = ROOT / "build" / ("HorizonDaily-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    destination.mkdir(parents=True, exist_ok=False)
    compiler = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/reference:System.Windows.Forms.dll",
                    "/win32manifest:"+str(ROOT / "desktop/Launcher.manifest"),
                    "/win32icon:"+str(ROOT / "desktop/app_icon.ico"),
                    "/out:"+str(destination / "HorizonDaily.exe"), str(ROOT / "desktop/Launcher.cs")], check=True)
    shutil.copy2(destination / "HorizonDaily.exe", ROOT / "HorizonDaily.exe")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "src", destination / "src", ignore=ignore)
    runtime_assets = copy_runtime_assets(destination)
    for name in ("main.py", "README.md", "requirements.txt"):
        shutil.copy2(ROOT / name, destination / name)
    for name in ("docs", "screenshots", "configs", "logs"):
        (destination / name).mkdir()
    runtime = destination / "runtime"
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for pattern in ("python*.exe", "python*.dll", "python*.zip", "vcruntime*.dll", "LICENSE*"):
        for source in base.glob(pattern):
            shutil.copy2(source, runtime / source.name)
    for name in ("Lib", "DLLs"):
        shutil.copytree(base / name, runtime / name,
                        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"))
    shutil.copytree(Path(sys.prefix) / "Lib/site-packages", runtime / "Lib/site-packages", ignore=ignore)
    pth = runtime / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth.write_text(".\n..\nLib\nDLLs\nLib/site-packages\nimport site\n", encoding="utf-8")
    (destination / "OPEN_ME.txt").write_text(
        "双击 HorizonDaily.exe，确认管理员弹窗。\n请保留整个文件夹；无需安装Python。\n"
        "在任务页展开每日任务可配置开关。F9停止；游戏不要最小化。\n", encoding="utf-8")
    (destination / "docs/build-manifest.json").write_text(
        json.dumps({"runtime_assets": runtime_assets}, indent=2), encoding="utf-8")
    (ROOT / "docs/desktop-build.txt").write_text(str(destination), encoding="utf-8")
    print(destination, flush=True)


if __name__ == "__main__":
    build()
