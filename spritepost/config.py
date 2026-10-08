from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path


DEFAULTS = {
    "version": 1,
    "name": "character",
    "aseprite": "auto",
    "output": "output",
    "work_size": [512, 512],
    "sizes": [[512, 512], [64, 64], [32, 32]],
    "resample": "lanczos4",
    "cleanup": {"profile": "off"},
    "layout": {
        "mode": "preserve", "occupancy": 0.9, "anchor": [0.5, 0.95],
        "alpha_threshold": 8, "allow_upscale": True,
    },
    "export": {
        "aseprite": True, "png_frames": False,
        "previews": True, "preview_sizes": [[64, 64], [32, 32]],
        "preview_scale": 4, "preview_frames": 48, "zip": True,
    },
    "unity": {"pixels_per_unit": 32, "pivot": [0.5, 0.5],
              "require_full_rect": True, "require_point": True,
              "require_no_mipmaps": True, "require_uncompressed": True},
    "animations": [],
}

CLEANUP_KEYS = {
    "profile", "edge_width", "reference_radius", "alpha_cutoff", "dust_area",
    "opaque_luminance", "partial_luminance", "opaque_saturation",
    "partial_saturation", "opaque_gap", "partial_gap", "passes",
}
ANIMATION_KEYS = {
    "name", "source", "edited", "frame_map", "matching", "reverse", "pingpong",
    "group", "zoom", "mirror_of", "axis", "scale_multiplier", "loop",
}
SOURCE_KEYS = {"path", "type", "frame_size", "metadata", "durations_ms", "fps", "glob"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def unknown_keys(value: dict, allowed, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = value.keys() - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {label} setting(s): {', '.join(sorted(unknown))}")


def number(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")


def dimensions(value, label):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be [width, height]")
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 8192:
            raise ValueError(f"{label} dimensions must be integers in 1..8192")


def resolve_path(value, base: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def source_spec(value, base: Path) -> dict:
    result = {"path": value} if isinstance(value, str) else copy.deepcopy(value)
    unknown_keys(result, SOURCE_KEYS, "source")
    if not result.get("path"):
        raise ValueError("source.path is required")
    result["path"] = str(resolve_path(result["path"], base))
    if result.get("metadata"):
        result["metadata"] = str(resolve_path(result["metadata"], base))
    if "frame_size" in result:
        dimensions(result["frame_size"], "source.frame_size")
    if "fps" in result:
        number(result["fps"], "source.fps", 0.1, 1000)
    if result.get("type", "auto") not in ("auto", "aseprite", "sheet", "sequence", "image"):
        raise ValueError("source.type must be auto, aseprite, sheet, sequence or image")
    return result


def load_config(path: str | Path) -> dict:
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return validate_config(raw, path.parent)


def validate_config(raw: dict, base: Path) -> dict:
    unknown_keys(raw, DEFAULTS, "root")
    config = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key in ("layout", "export", "unity"):
            unknown_keys(value, DEFAULTS[key], key)
            config[key].update(value)
        else:
            config[key] = copy.deepcopy(value)
    if config["version"] != 1:
        raise ValueError("Unsupported config version (expected 1)")
    for section, keys in (("layout", ("allow_upscale",)),
                          ("export", ("aseprite", "png_frames", "previews", "zip")),
                          ("unity", ("require_full_rect", "require_point", "require_no_mipmaps", "require_uncompressed"))):
        for key in keys:
            if not isinstance(config[section][key], bool):
                raise ValueError(f"{section}.{key} must be true or false")
    for label, value in (("name", config["name"]),):
        if not isinstance(value, str) or not SAFE_NAME.fullmatch(value) or value.endswith("."):
            raise ValueError(f"{label} must be a safe filename: letters, numbers, _ . -")
    config["output"] = str(resolve_path(config["output"], base))
    if config["aseprite"] != "auto":
        config["aseprite"] = str(resolve_path(config["aseprite"], base))
    dimensions(config["work_size"], "work_size")
    if not config["sizes"]:
        raise ValueError("sizes must not be empty")
    for size in config["sizes"]:
        dimensions(size, "sizes")
    if len({tuple(s) for s in config["sizes"]}) != len(config["sizes"]):
        raise ValueError("Duplicate output sizes")
    if config["resample"] not in ("lanczos4", "nearest", "box"):
        raise ValueError("resample must be lanczos4, nearest or box")
    unknown_keys(config["cleanup"], CLEANUP_KEYS, "cleanup")
    if config["cleanup"].get("profile", "off") not in ("off", "conservative", "strict"):
        raise ValueError("cleanup.profile must be off, conservative or strict")
    layout = config["layout"]
    if layout["mode"] not in ("preserve", "shared_fit"):
        raise ValueError("layout.mode must be preserve or shared_fit")
    number(layout["occupancy"], "layout.occupancy", 0.01, 1.0)
    number(layout["alpha_threshold"], "layout.alpha_threshold", 1, 255)
    for key in ("anchor",):
        if len(layout[key]) != 2:
            raise ValueError(f"layout.{key} must contain two values")
        for v in layout[key]:
            number(v, f"layout.{key}", 0, 1)
    if not 0 < layout["anchor"][0] < 1 or layout["anchor"][1] <= 0:
        raise ValueError("Bottom-center anchor needs 0 < x < 1 and y > 0")
    exports = config["export"]
    number(exports["preview_scale"], "export.preview_scale", 1, 16)
    number(exports["preview_frames"], "export.preview_frames", 1, 10000)
    if int(exports["preview_scale"]) != exports["preview_scale"] or int(exports["preview_frames"]) != exports["preview_frames"]:
        raise ValueError("Preview scale and frame count must be integers")
    for size in exports["preview_sizes"]:
        dimensions(size, "export.preview_sizes")
    number(config["unity"]["pixels_per_unit"], "unity.pixels_per_unit", 0.01, 100000)
    if len(config["unity"]["pivot"]) != 2:
        raise ValueError("unity.pivot must have two values")
    for value in config["unity"]["pivot"]:
        number(value, "unity.pivot", 0, 1)
    names = set()
    if not config["animations"]:
        raise ValueError("animations must not be empty")
    for entry in config["animations"]:
        unknown_keys(entry, ANIMATION_KEYS, "animation")
        name = entry.get("name", "")
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or name.endswith("."):
            raise ValueError(f"Invalid animation name: {name!r}")
        if name.casefold() in names:
            raise ValueError(f"Duplicate animation name: {name}")
        names.add(name.casefold())
        if ("source" in entry) == ("mirror_of" in entry):
            raise ValueError(f"{name}: specify exactly one of source or mirror_of")
        if "source" in entry:
            entry["source"] = source_spec(entry["source"], base)
        for key in ("reverse", "loop"):
            if key in entry and not isinstance(entry[key], bool):
                raise ValueError(f"{name}: {key} must be true or false")
        if not isinstance(entry.get("group", "default"), str):
            raise ValueError(f"{name}: group must be a string")
        if "edited" in entry:
            entry["edited"] = source_spec(entry["edited"], base)
        if "mirror_of" in entry and entry.keys() - {"name", "mirror_of", "axis", "loop"}:
            raise ValueError(f"{name}: mirrors inherit source settings; only axis/loop may be overridden")
        if entry.get("axis", "horizontal") not in ("horizontal", "vertical"):
            raise ValueError(f"{name}: invalid mirror axis")
        if entry.get("pingpong", "none") not in ("none", "repeat_ends", "no_repeat_ends"):
            raise ValueError(f"{name}: invalid pingpong mode")
        if "frame_map" in entry and (not isinstance(entry["frame_map"], list) or not entry["frame_map"]):
            raise ValueError(f"{name}: frame_map must be a nonempty list of zero-based indices")
        if "matching" in entry:
            unknown_keys(entry["matching"], {"allow_mirror", "max_error", "min_margin", "compare_size"}, "matching")
            for key, default in (("max_error", .12), ("min_margin", .002)):
                number(entry["matching"].get(key, default), "matching." + key, 0, 1)
            number(entry["matching"].get("compare_size", 64), "matching.compare_size", 8, 512)
        if "zoom" in entry:
            unknown_keys(entry["zoom"], {"start_scale", "end_scale", "easing"}, "zoom")
            for key in ("start_scale", "end_scale"):
                number(entry["zoom"].get(key, 1), "zoom." + key, .1, 4)
            if entry["zoom"].get("easing", "smoothstep") not in ("smoothstep", "linear"):
                raise ValueError("zoom.easing must be smoothstep or linear")
        number(entry.get("scale_multiplier", 1), "scale_multiplier", .1, 10)
    known = {a["name"] for a in config["animations"]}
    for entry in config["animations"]:
        if "mirror_of" in entry and entry["mirror_of"] not in known:
            raise ValueError(f"Unknown mirror source {entry['mirror_of']}")
        for label in ("source", "edited"):
            if label not in entry:
                continue
            source = Path(entry[label]["path"])
            output = Path(config["output"])
            if source == output or source.is_relative_to(output) or (source.is_dir() and output.is_relative_to(source)):
                raise ValueError("Output must be separate from input folders/files")
    parents = {a["name"]: a.get("mirror_of") for a in config["animations"]}
    for name in parents:
        seen = set()
        current = name
        while current is not None:
            if current in seen:
                raise ValueError(f"Mirror reference cycle involving {current}")
            seen.add(current)
            current = parents[current]
    return config
