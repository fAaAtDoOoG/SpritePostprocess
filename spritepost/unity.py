"""Optional Unity integration: static metadata checks and explicit PNG deployment.

This module never edits .meta files and does not claim to inspect Unity's actual
imported objects. Coordinates in exported manifests use a top-left origin;
Unity SpriteRects use a bottom-left origin.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

from PIL import Image


def _section(text: str, name: str) -> str | None:
    lines = text.splitlines()
    pattern = re.compile(r"^( *)" + re.escape(name) + r":(?:\s*(.*))?$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        if (match.group(2) or "").strip() in ("[]", "{}"):
            return ""
        indentation = len(match.group(1))
        end = index + 1
        while end < len(lines):
            following = lines[end]
            if following.strip():
                following_indent = len(following) - len(following.lstrip())
                if following_indent < indentation:
                    break
                if following_indent == indentation and not following.lstrip().startswith("- "):
                    break
            end += 1
        return "\n".join(lines[index + 1:end])
    return None


def _scalar(text: str, name: str) -> str | None:
    match = re.search(r"^[ \t]*(?:- )?" + re.escape(name) + r":[ \t]*([^\n\r]*)\r?$", text, re.M)
    return match.group(1).strip().strip('"') if match else None


def _records(section: str) -> list[str]:
    lines = section.splitlines()
    candidates = [(index, len(line) - len(line.lstrip()))
                  for index, line in enumerate(lines) if line.lstrip().startswith("- ")]
    if not candidates:
        return []
    minimum_indent = min(indent for _, indent in candidates)
    starts = [index for index, indent in candidates if indent == minimum_indent]
    ends = starts[1:] + [len(lines)]
    return ["\n".join(lines[start:end]) for start, end in zip(starts, ends)]


def _vector(value: str | None, names: tuple[str, ...]) -> list[float] | None:
    if value is None:
        return None
    result = []
    for name in names:
        match = re.search(r"(?:\{|,)\s*" + name + r"\s*:\s*([^,}]+)", value)
        if not match:
            return None
        try:
            number = float(match.group(1))
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        result.append(number)
    return result


def _sprite_records(text: str, kind: str) -> tuple[list[dict], list[str]]:
    warnings = []
    if kind == "png":
        parent = _section(text, "spriteSheet")
        section = _section(parent, "sprites") if parent is not None else None
    else:
        importer = _section(text, "asepriteImporterSettings")
        mode = _scalar(importer or "", "fileImportMode")
        if mode == "0":
            section = _section(text, "spriteSheetImportData")
        elif mode == "1":
            section = _section(text, "animatedSpriteImportData")
            warnings.append("Active Aseprite importer uses AnimatedSprite; actual packed geometry needs Unity validation.")
        else:
            return [], ["Unsupported or missing Aseprite fileImportMode; active sprite section cannot be verified."]
    if section is None:
        return [], warnings + ["Sprite rectangle metadata is absent or uses an unsupported serialization layout."]
    sprites = []
    for record in _records(section):
        rectangle = _section(record, "rect")
        coordinates = []
        for key in ("x", "y", "width", "height"):
            value = _scalar(rectangle or "", key)
            try:
                coordinates.append(float(value))
            except (TypeError, ValueError):
                coordinates = []
                break
        sprites.append({
            "name": _scalar(record, "name"),
            "rect": coordinates or None,
            "pivot": _vector(_scalar(record, "pivot"), ("x", "y")),
            "sprite_id": _scalar(record, "spriteID"),
            "internal_id": _scalar(record, "internalID"),
        })
    return sprites, warnings


def _geometry_errors(sprites: list[dict], sheet_size=None, expected_size=None, pivot=None,
                     check_overlap=True) -> list[str]:
    errors = []
    valid = []
    for index, sprite in enumerate(sprites):
        rectangle = sprite["rect"]
        if (rectangle is None or len(rectangle) != 4
                or any(not math.isfinite(item) or item != int(item) for item in rectangle)
                or rectangle[0] < 0 or rectangle[1] < 0 or min(rectangle[2:]) <= 0):
            errors.append(f"Frame {index} has an invalid or non-integer rectangle.")
            continue
        x, y, width, height = rectangle
        if sheet_size and (x + width > sheet_size[0] or y + height > sheet_size[1]):
            errors.append(f"Frame {index} rectangle exceeds the PNG canvas.")
        if expected_size and list(rectangle[2:]) != list(expected_size):
            errors.append(f"Frame {index} is not the expected full canvas {list(expected_size)}.")
        valid.append(rectangle)
    if valid and len({tuple(item[2:]) for item in valid}) != 1:
        errors.append("Frame rectangle sizes are inconsistent (possible tight trimming).")
    for index, first in enumerate(valid if check_overlap else []):
        for second in valid[index + 1:]:
            if (max(first[0], second[0]) < min(first[0] + first[2], second[0] + second[2])
                    and max(first[1], second[1]) < min(first[1] + first[3], second[1] + second[3])):
                errors.append("Frame rectangles overlap.")
                break
        if "Frame rectangles overlap." in errors:
            break
    for field in ("name", "sprite_id", "internal_id"):
        values = [item[field] for item in sprites if item[field] not in (None, "")]
        if len(values) != len(set(values)):
            errors.append(f"Duplicate frame {field} values.")
    pivots = [item["pivot"] for item in sprites]
    if any(item is None for item in pivots):
        errors.append("Some frame pivots are absent or malformed.")
    elif pivots:
        target = pivot if pivot is not None else pivots[0]
        if any(any(abs(a - b) > 1e-6 for a, b in zip(item, target)) for item in pivots):
            errors.append("Frame pivots differ from one another or from the configured pivot.")
    return errors


def _expected_setting(text, name, expected, enabled, errors, warnings):
    if not enabled:
        return
    value = _scalar(text, name)
    if value is None:
        warnings.append(f"Cannot verify absent metadata setting: {name}.")
    elif value != str(expected):
        errors.append(f"{name} is {value}; expected {expected}.")


def _check_meta(path: Path, settings: dict) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    kind = "png" if path.name.lower().endswith(".png.meta") else "aseprite"
    source = path.with_suffix("")
    errors, warnings = [], []
    _expected_setting(text, "spriteMeshType", 0, settings.get("require_full_rect", True), errors, warnings)
    _expected_setting(text, "filterMode", 0, settings.get("require_point", True), errors, warnings)
    _expected_setting(text, "enableMipMap", 0, settings.get("require_no_mipmaps", True), errors, warnings)
    _expected_setting(text, "spriteMode", 2, True, errors, warnings)
    if settings.get("pixels_per_unit") is not None:
        value = _scalar(text, "spritePixelsToUnits")
        try:
            correct = math.isclose(float(value), float(settings["pixels_per_unit"]), abs_tol=1e-6)
        except (ValueError, TypeError):
            correct = False
        if not correct:
            errors.append("pixels_per_unit does not match the configured value.")
    if kind == "png":
        _expected_setting(text, "nPOTScale", 0, True, errors, warnings)
    platforms = _section(text, "platformSettings")
    active_platforms = []
    for platform in _records(platforms or ""):
        target = _scalar(platform, "buildTarget")
        if target == "DefaultTexturePlatform" or _scalar(platform, "overridden") == "1":
            active_platforms.append(platform)
            _expected_setting(platform, "textureCompression", 0,
                              settings.get("require_uncompressed", True), errors, warnings)
    if not active_platforms and settings.get("require_uncompressed", True):
        warnings.append("No active platform compression settings found; compression is unverified.")
    sprites, parse_warnings = _sprite_records(text, kind)
    warnings.extend(parse_warnings)
    sheet_size, canvas, expected_count = None, settings.get("size"), None
    if source.exists():
        if kind == "png":
            with Image.open(source) as image:
                image.verify()
            with Image.open(source) as image:
                sheet_size = list(image.size)
            for platform in active_platforms:
                limit = _scalar(platform, "maxTextureSize")
                if limit is not None and int(limit) < max(sheet_size):
                    errors.append(f"Active texture size limit {limit} can downscale the {sheet_size} PNG.")
        else:
            with source.open("rb") as stream:
                header = stream.read(16)
            if len(header) < 16 or struct.unpack_from("<H", header, 4)[0] != 0xA5E0:
                errors.append("Source is not a recognized Aseprite file.")
            else:
                expected_count, width, height = struct.unpack_from("<HHH", header, 6)
                if canvas and list(canvas) != [width, height]:
                    errors.append("Aseprite canvas does not match configured size.")
                canvas = [width, height]
    else:
        warnings.append("Source file is absent; pixel dimensions and frame count cannot be checked.")
    errors.extend(_geometry_errors(sprites, sheet_size, canvas, settings.get("pivot"),
                                   check_overlap=kind == "png"))
    if not sprites:
        warnings.append("No sprite records could be verified.")
    if expected_count is not None and sprites and expected_count != len(sprites):
        errors.append(f"Aseprite has {expected_count} frames but metadata has {len(sprites)} sprites.")
    if sprites and any(not sprite["name"] or not sprite["sprite_id"] for sprite in sprites):
        warnings.append("Some sprite names or SpriteIDs are missing; stable identity is unverified.")
    return {"path": str(path), "kind": kind, "frame_count": len(sprites),
            "status": "failed" if errors else "passed", "errors": errors, "warnings": warnings}


def check_unity(directory: Path, settings: dict | None = None) -> dict:
    """Read only PNG/Aseprite metadata under an explicitly chosen directory.

    Optional settings: size=[frame_width, frame_height], pixels_per_unit, pivot,
    require_full_rect, require_point, require_no_mipmaps, require_uncompressed.
    A passed result means no static violations were found, not an in-Editor test.
    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError(f"Unity check directory does not exist: {directory}")
    settings = settings or {}
    result = {"status": "passed", "evidence": "static_meta", "files": [], "errors": [],
              "warnings": ["Static metadata only; imported Unity geometry, references and playback were not tested."]}
    paths = sorted(path for path in directory.rglob("*") if path.is_file()
                   and path.name.lower().endswith((".png.meta", ".aseprite.meta")))
    for path in paths:
        try:
            report = _check_meta(path, settings)
        except (ValueError, OSError, struct.error) as exception:
            report = {"path": str(path), "status": "failed", "errors": [str(exception)], "warnings": []}
        result["files"].append(report)
        result["errors"].extend(f"{path}: {message}" for message in report["errors"])
        result["warnings"].extend(f"{path}: {message}" for message in report["warnings"])
    if not paths:
        result["warnings"].append("No PNG or Aseprite .meta files were found.")
    result["status"] = "failed" if result["errors"] else "passed"
    return result


def _manifest_rects(manifest: dict, sheet_size: tuple[int, int]) -> list[list[int]]:
    size = manifest.get("size")
    if (not isinstance(size, list) or len(size) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in size)):
        raise ValueError("Manifest size must be [positive frame width, positive frame height].")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Manifest must contain frame records.")
    rectangles = []
    for frame in frames:
        record = frame.get("rect", {})
        coordinates = [record.get(key) for key in ("x", "y", "w", "h")]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in coordinates):
            raise ValueError("Manifest frame rectangles must be integers x/y/w/h.")
        x, y, width, height = coordinates
        if ([width, height] != size or min(x, y) < 0
                or x + width > sheet_size[0] or y + height > sheet_size[1]):
            raise ValueError("Manifest frame rectangle is outside the image or differs from the frame canvas.")
        rectangles.append([x, sheet_size[1] - y - height, width, height])
    for index, first in enumerate(rectangles):
        for second in rectangles[index + 1:]:
            if (max(first[0], second[0]) < min(first[0] + first[2], second[0] + second[2])
                    and max(first[1], second[1]) < min(first[1] + first[3], second[1] + second[3])):
                raise ValueError("Manifest frame rectangles overlap.")
    return rectangles


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _replace_file(source: Path, destination: Path) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".spritepost-", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        shutil.copyfile(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def deploy_png(sheet: Path, destination: Path, manifest: dict, backup_dir: Path) -> dict:
    """Explicitly deploy a PNG while retaining existing Unity metadata byte-for-byte.

    Existing targets require matching dimensions, frame rectangle order and count.
    This is a pixel replacement only: it does not rewrite animation timings/clips.
    Backups must be outside the destination directory tree and every Assets tree.
    """
    sheet, destination, backup_dir = (Path(path).resolve() for path in (sheet, destination, backup_dir))
    if sheet.suffix.lower() != ".png" or destination.suffix.lower() != ".png":
        raise ValueError("Deployment accepts PNG source and destination files only.")
    if sheet == destination:
        raise ValueError("Source and destination must be different files.")
    if not sheet.is_file():
        raise ValueError(f"PNG source does not exist: {sheet}")
    if destination.exists() and not destination.is_file():
        raise ValueError("PNG destination is not a regular file.")
    if (_within(backup_dir, destination.parent)
            or any(part.lower() == "assets" for part in backup_dir.parts)):
        raise ValueError("Backup directory must be outside the target directory tree and outside Assets.")
    with Image.open(sheet) as image:
        if image.format != "PNG":
            raise ValueError("Source content is not PNG.")
        image.verify()
    with Image.open(sheet) as image:
        sheet_size = image.size
    rectangles = _manifest_rects(manifest, sheet_size)
    metadata = destination.with_name(destination.name + ".meta")
    existed = destination.exists()
    metadata_before = metadata.read_bytes() if metadata.exists() else None
    if existed and metadata_before is None:
        raise ValueError("Existing PNG has no .meta file; refusing to guess or replace its import contract.")
    if metadata_before is not None:
        text = metadata_before.decode("utf-8-sig")
        if _scalar(text, "spriteMode") != "2":
            raise ValueError("Existing metadata is not a Multiple Sprite importer.")
        sprites, warnings = _sprite_records(text, "png")
        if warnings or len(sprites) != len(rectangles):
            raise ValueError("Existing metadata frame count/layout is unsupported or differs from the manifest.")
        errors = _geometry_errors(sprites, sheet_size, manifest["size"])
        if errors:
            raise ValueError("Existing metadata is unsafe to replace: " + "; ".join(errors))
        if [sprite["rect"] for sprite in sprites] != rectangles:
            raise ValueError("Existing metadata frame rectangle order/layout differs from the manifest.")
        if any(not sprite["name"] or not sprite["sprite_id"] for sprite in sprites):
            raise ValueError("Existing frame identities are missing; refusing replacement.")
    if existed:
        with Image.open(destination) as image:
            if image.format != "PNG" or image.size != sheet_size:
                raise ValueError("Existing PNG dimensions/content differ from the new sheet.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="deploy-", dir=backup_dir))
    backup_png, backup_meta = session / destination.name, session / metadata.name
    if existed:
        shutil.copy2(destination, backup_png)
    if metadata_before is not None:
        shutil.copy2(metadata, backup_meta)
    destination.parent.mkdir(parents=True, exist_ok=True)
    changed = False
    try:
        # Fail if an editor or another task changed metadata during preparation.
        if metadata_before is not None and metadata.read_bytes() != metadata_before:
            raise RuntimeError("Unity metadata changed during deployment preparation; no replacement performed.")
        _replace_file(sheet, destination)
        changed = True
        with Image.open(destination) as image:
            image.verify()
        if metadata_before is not None and metadata.read_bytes() != metadata_before:
            raise RuntimeError("Unity metadata changed during deployment; restored PNG, metadata left untouched.")
    except Exception:
        if changed:
            if existed:
                _replace_file(backup_png, destination)
            else:
                destination.unlink(missing_ok=True)
        raise
    return {"status": "deployed", "destination": str(destination), "backup": str(session),
            "metadata_preserved": metadata_before is not None,
            "requires_unity_import": True, "existing_target": existed,
            "warnings": ["Only PNG pixels were deployed. Unity import, sprite references and playback were not tested.",
                         "Existing AnimationClip timings are unchanged; apply manifest durations in the engine if needed."]}
