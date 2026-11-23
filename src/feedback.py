"""Explicit, local-only feedback bundles; never scan unrelated run folders."""
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile


def has_failures(report):
    return bool(report.get("stage_errors"))


def read_report(root):
    try:
        report = json.loads((root / "docs/timing-latest.json").read_text(encoding="utf-8"))
        return report if isinstance(report, dict) else {}
    except (OSError, ValueError):
        return {}


def screenshots(report, root):
    """Only accept existing images explicitly referenced by this run's errors."""
    folder = (root / "screenshots").resolve()
    found = []
    for error in report.get("stage_errors", []):
        for key in ("screenshot", "recovery_screenshot"):
            value = error.get(key)
            if not value:
                continue
            path = Path(value)
            path = (path if path.is_absolute() else root / path).resolve()
            if (path.is_relative_to(folder) and path.is_file()
                    and path.suffix.lower() in {".png", ".jpg", ".jpeg"} and path not in found):
                found.append(path)
    return found


def sanitize(value, root):
    if isinstance(value, dict):
        return {key: sanitize(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, root) for item in value]
    if not isinstance(value, str):
        return value
    # Preserve useful filenames and line numbers while removing machine-specific paths.
    for prefix in {str(root.resolve()), root.resolve().as_posix()}:
        value = re.sub(re.escape(prefix), "<project>", value, flags=re.IGNORECASE)
    value = re.sub(r'[A-Za-z]:[\\/][^\r\n"\'<>|]*', "<local-path>", value)
    value = re.sub(r'\\\\[^\s"\'<>|]+', "<network-path>", value)
    return value


def export_bundle(report, selected, root, version, destination):
    allowed = set(screenshots(report, root))
    selected = [Path(path).resolve() for path in selected]
    if any(path not in allowed for path in selected):
        raise ValueError("所选截图不属于这次运行，未生成反馈包。")
    # Settings and arbitrary framework info are deliberately not copied.
    fields = ("started_at", "status", "success", "error", "daily_rewards_complete",
              "elapsed_seconds", "stages", "stage_errors", "actions", "navigation", "components")
    clean = sanitize({key: report[key] for key in fields if key in report}, root)
    clean["application_version"] = version
    clean["exported_at"] = datetime.now().isoformat()
    # References to omitted screenshots must not imply that they were included.
    for failure in clean.get("stage_errors", []):
        failure.pop("screenshot", None)
        failure.pop("recovery_screenshot", None)
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("run.json", json.dumps(clean, ensure_ascii=False, indent=2))
        lines = ["地平线行者每日助手反馈包", f"版本：{version}",
                 f"运行开始：{report.get('started_at', '')}", f"状态：{report.get('status', '')}",
                 "仅包含本轮运行记录及用户选择的截图；未自动上传。",
                 "分享前请检查截图中的昵称、账号等个人信息。"]
        lines.extend(f"{error.get('stage', '')}: {error.get('error', '')}"
                     for error in report.get("stage_errors", []))
        lines.append(f"已选截图：{len(selected)} 张")
        for index, path in enumerate(dict.fromkeys(selected), 1):
            name = f"screenshots/{index:02d}{path.suffix.lower()}"
            archive.writestr(name, path.read_bytes())
            lines.append(name)
        archive.writestr("summary.txt", sanitize("\n".join(lines), root))
    # Exclusive creation avoids overwriting an earlier feedback package.
    with Path(destination).open("xb") as target:
        target.write(buffer.getvalue())
    return Path(destination)
