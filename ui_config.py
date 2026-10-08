from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from ui_strings import SUPPORTED_LANGUAGES, detect_language, text


PREFERENCES_FILE = ".ui-preferences.json"
_SIZE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")


class UiConfigError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def localized_validation_error(error: Exception, language: str) -> str:
    if isinstance(error, UiConfigError):
        summary = text(language, f"form_error_{error.code}")
    else:
        summary = text(language, "form_error_general")
    detail = str(error).strip()
    return f"{summary}\n\n{text(language, 'technical_detail')}{detail}" if detail else summary


def parse_size(value: str, label: str = "size") -> list[int]:
    match = _SIZE.fullmatch(value)
    if not match:
        raise UiConfigError("size_format", f"{label} must be W×H, for example 512×512")
    result = [int(match.group(1)), int(match.group(2))]
    if any(item < 1 or item > 8192 for item in result):
        raise UiConfigError("size_range", f"{label} dimensions must be in 1..8192")
    return result


def parse_sizes(value: str) -> list[list[int]]:
    pieces = [piece.strip() for piece in value.split(",") if piece.strip()]
    if not pieces:
        raise UiConfigError("sizes_empty", "output sizes must not be empty")
    result = [parse_size(piece, "output size") for piece in pieces]
    if len({tuple(item) for item in result}) != len(result):
        raise UiConfigError("sizes_duplicate", "output sizes must not contain duplicates")
    return result


def format_size(value: object) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return ""
    return f"{value[0]}×{value[1]}"


def format_sizes(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return ", ".join(format_size(item) for item in value)


def common_from_config(data: dict) -> dict[str, object]:
    cleanup = data.get("cleanup") if isinstance(data.get("cleanup"), dict) else {}
    layout = data.get("layout") if isinstance(data.get("layout"), dict) else {}
    exports = data.get("export") if isinstance(data.get("export"), dict) else {}
    occupancy = layout.get("occupancy", 0.9)
    return {
        "output": str(data.get("output", "")),
        "aseprite": str(data.get("aseprite", "auto")),
        "work_size": format_size(data.get("work_size", [512, 512])),
        "sizes": format_sizes(data.get("sizes", [[512, 512], [64, 64], [32, 32]])),
        "cleanup": cleanup.get("profile", "off"),
        "layout": layout.get("mode", "preserve"),
        "occupancy_percent": f"{float(occupancy) * 100:g}",
        "preview_frames": str(exports.get("preview_frames", 48)),
        "export_aseprite": bool(exports.get("aseprite", True)),
        "export_png_frames": bool(exports.get("png_frames", False)),
        "export_previews": bool(exports.get("previews", True)),
        "export_zip": bool(exports.get("zip", True)),
    }


def merge_common(data: dict, values: dict[str, object]) -> dict:
    if not isinstance(data, dict):
        raise UiConfigError("root_object", "config root must be an object")
    result = copy.deepcopy(data)
    output = str(values["output"]).strip()
    if not output:
        raise UiConfigError("output_empty", "output directory must not be empty")
    aseprite = str(values["aseprite"]).strip() or "auto"
    cleanup = str(values["cleanup"])
    layout = str(values["layout"])
    if cleanup not in {"off", "conservative", "strict"}:
        raise UiConfigError("cleanup", "cleanup must be off, conservative or strict")
    if layout not in {"preserve", "shared_fit"}:
        raise UiConfigError("layout", "layout must be preserve or shared_fit")
    try:
        occupancy = float(str(values["occupancy_percent"]).strip()) / 100.0
    except ValueError as error:
        raise UiConfigError("occupancy_format", "occupancy must be a percentage") from error
    if not 0.01 <= occupancy <= 1.0:
        raise UiConfigError("occupancy_range", "occupancy must be between 1 and 100 percent")
    try:
        preview_frames = int(str(values["preview_frames"]).strip())
    except ValueError as error:
        raise UiConfigError("preview_format", "preview frames must be a whole number") from error
    if not 1 <= preview_frames <= 10000:
        raise UiConfigError("preview_range", "preview frames must be in 1..10000")

    result["output"] = output
    result["aseprite"] = aseprite
    result["work_size"] = parse_size(str(values["work_size"]), "working canvas")
    result["sizes"] = parse_sizes(str(values["sizes"]))
    cleanup_section = result.get("cleanup")
    if not isinstance(cleanup_section, dict):
        cleanup_section = {}
        result["cleanup"] = cleanup_section
    cleanup_section["profile"] = cleanup
    layout_section = result.get("layout")
    if not isinstance(layout_section, dict):
        layout_section = {}
        result["layout"] = layout_section
    layout_section["mode"] = layout
    layout_section["occupancy"] = occupancy
    export_section = result.get("export")
    if not isinstance(export_section, dict):
        export_section = {}
        result["export"] = export_section
    export_section["preview_frames"] = preview_frames
    for key in ("aseprite", "png_frames", "previews", "zip"):
        export_section[key] = bool(values[f"export_{key}"])
    return result


def suggested_paths(source: str | Path) -> tuple[Path, Path]:
    path = Path(source).expanduser().resolve()
    base = path.parent if path.is_file() else path.parent
    stem = path.stem if path.is_file() else path.name
    safe_stem = stem or "sprite"
    output = base / f"{safe_stem}_processed"
    config = base / f"{safe_stem}.spritepost.json"
    return output, config


def config_is_inside_output(config: str | Path, output: str | Path) -> bool:
    config_path = Path(config).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    return config_path == output_path or config_path.is_relative_to(output_path)


def load_language_preference(path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return detect_language()
    language = raw.get("language") if isinstance(raw, dict) else None
    return language if language in SUPPORTED_LANGUAGES else detect_language()


def save_language_preference(path: Path, language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    path.write_text(
        json.dumps({"language": language}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
