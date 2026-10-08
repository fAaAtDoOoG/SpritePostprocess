from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


@dataclass
class Animation:
    frames: list[np.ndarray]
    durations: list[int]
    source: str


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_aseprite(setting="auto"):
    requested = setting if setting != "auto" else os.environ.get("SPRITEPOST_ASEPRITE")
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(requested)
        if found:
            return found
        raise FileNotFoundError(f"Aseprite executable not found: {requested}")
    candidates = [shutil.which("aseprite"), shutil.which("Aseprite.exe")]
    for root in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        if root:
            candidates += [str(Path(root) / "Steam/steamapps/common/Aseprite/Aseprite.exe"),
                           str(Path(root) / "Aseprite/Aseprite.exe")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("Aseprite not found. Set aseprite in config or SPRITEPOST_ASEPRITE. PNG-only processing can disable export.aseprite.")


def run_aseprite(executable, arguments):
    result = subprocess.run([executable, "-b", *map(str, arguments)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=600,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError(f"Aseprite failed ({result.returncode}):\n{result.stderr}\n{result.stdout}")


def export_aseprite(path, directory, executable):
    directory.mkdir(parents=True, exist_ok=True)
    sheet, data = directory / "sheet.png", directory / "sheet.json"
    run_aseprite(executable, [path, "--sheet", sheet, "--data", data, "--format", "json-array",
                              "--sheet-type", "horizontal"])
    return load_animation({"path": str(sheet), "metadata": str(data), "type": "sheet"}, directory, executable)


def _durations(spec, count, from_metadata=None):
    if "durations_ms" in spec:
        values = spec["durations_ms"]
        values = [values] * count if isinstance(values, int) else values
    elif from_metadata is not None:
        values = from_metadata
    elif "fps" in spec:
        # Rounded cumulative time avoids drifting 62/63ms animation timing.
        fps = spec["fps"]
        values = [round((i+1)*1000/fps)-round(i*1000/fps) for i in range(count)]
    else:
        raise ValueError("PNG input needs metadata durations, durations_ms or fps; timing is not guessed")
    if len(values) != count or any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                                    int(v) != v or not 1 <= v <= 65535 for v in values):
        raise ValueError("Frame durations must match frame count and be integer milliseconds in 1..65535")
    return list(map(int, values))


def _natural(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(path))]


def load_animation(spec, cache, executable=None):
    path = Path(spec["path"])
    kind = spec.get("type", "auto")
    if kind == "auto":
        kind = "sequence" if path.is_dir() else "aseprite" if path.suffix.lower() in (".ase", ".aseprite") else "sheet"
    if kind == "aseprite":
        loaded = export_aseprite(path, cache, executable or find_aseprite())
        durations = _durations(spec, len(loaded.frames), loaded.durations)
        return Animation(loaded.frames, durations, str(path))
    if kind == "sequence":
        files = sorted(path.glob(spec.get("glob", "*.png")), key=_natural)
        if not files:
            raise ValueError(f"No PNG frames found in {path}")
        frames = [np.asarray(Image.open(f).convert("RGBA")).copy() for f in files]
        if len({f.shape for f in frames}) != 1:
            raise ValueError("Sequence frame dimensions differ")
        return Animation(frames, _durations(spec, len(frames)), str(path))
    sheet = np.asarray(Image.open(path).convert("RGBA")).copy()
    metadata = spec.get("metadata")
    if metadata:
        document = json.loads(Path(metadata).read_text(encoding="utf-8-sig"))
        records = document["frames"]
        records = list(records.values()) if isinstance(records, dict) else records
        frames, times = [], []
        for record in records:
            if record.get("rotated", False):
                raise ValueError("Rotated atlas frames are unsupported; export an unrotated sheet")
            rect = record.get("frame", record.get("rect"))
            x, y, w, h = (int(rect[k]) for k in ("x", "y", "w", "h"))
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > sheet.shape[1] or y+h > sheet.shape[0]:
                raise ValueError("Frame rectangle is outside sprite sheet")
            crop = sheet[y:y+h, x:x+w].copy()
            size = record.get("sourceSize", {"w": w, "h": h})
            placement = record.get("spriteSourceSize", {"x": 0, "y": 0, "w": w, "h": h})
            frame = np.zeros((size["h"], size["w"], 4), np.uint8)
            px, py = placement["x"], placement["y"]
            if px < 0 or py < 0 or px+w > size["w"] or py+h > size["h"]:
                raise ValueError("Trimmed frame placement is outside its source canvas")
            frame[py:py+h, px:px+w] = crop
            frames.append(frame)
            times.append(record.get("duration", record.get("duration_ms")))
        if not frames or len({f.shape for f in frames}) != 1:
            raise ValueError("Metadata must describe nonempty, consistent frame canvases")
        return Animation(frames, _durations(spec, len(frames), times), str(path))
    size = spec.get("frame_size")
    if size is None:
        if kind != "image":
            raise ValueError(f"PNG sheet {path} needs frame_size or metadata; use type=image for a single frame")
        size = [sheet.shape[1], sheet.shape[0]]
    w, h = size
    if sheet.shape[1] % w or sheet.shape[0] % h:
        raise ValueError("Sheet dimensions are not multiples of frame_size")
    frames = [sheet[y:y+h, x:x+w].copy() for y in range(0, sheet.shape[0], h)
              for x in range(0, sheet.shape[1], w)]
    return Animation(frames, _durations(spec, len(frames)), str(path))


def save_sheet(frames, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.concatenate(frames, axis=1)).save(path)


def create_aseprite(sheet, output, size, durations, name, executable):
    if size[0] * len(durations) > 65535:
        raise ValueError("Aseprite PNG sheet width exceeds 65535; use fewer frames or a smaller size")
    output.parent.mkdir(parents=True, exist_ok=True)
    params = {"input": sheet, "output": output, "width": size[0], "height": size[1],
              "durations": ",".join(map(str, durations)), "name": name}
    args = []
    for key, value in params.items():
        args += ["--script-param", f"{key}={value}"]
    run_aseprite(executable, args + ["--script", Path(__file__).parent / "assets/import_sheet.lua"])


def check_aseprite_canvas(path, executable):
    run_aseprite(executable, ["--script-param", f"input={path}", "--script",
                              Path(__file__).parent / "assets/check_canvas.lua"])


def preview_frames(frames, name, scale, count=None):
    count = count or len(frames)
    w, h = frames[0].shape[1], frames[0].shape[0]
    checker = np.empty((h, w, 4), np.uint8)
    y, x = np.indices((h, w))
    light = ((x // max(1, w//8) + y // max(1, h//8)) % 2) == 0
    checker[...] = [45, 45, 51, 255]
    checker[light] = [77, 77, 84, 255]
    result = []
    for index in range(count):
        bg = Image.fromarray(checker.copy())
        bg.alpha_composite(Image.fromarray(frames[index % len(frames)]))
        canvas = Image.new("RGB", (w*scale, h*scale+36), (26, 26, 30))
        canvas.paste(bg.resize((w*scale, h*scale), Image.Resampling.NEAREST).convert("RGB"))
        draw = ImageDraw.Draw(canvas)
        draw.text((3, h*scale+2), name, fill=(225, 220, 204))
        draw.text((3, h*scale+18), f"{index+1}/{count} (source {index % len(frames)})", fill=(225, 220, 204))
        result.append(canvas)
    return result


def save_previews(frames, durations, path, name, scale=4, count=None):
    images = preview_frames(frames, name, scale, count)
    times = [durations[i % len(durations)] for i in range(len(images))]
    path.parent.mkdir(parents=True, exist_ok=True)
    # APNG is authoritative for exact millisecond timing; GIF can only express 10ms ticks.
    apng = path.with_suffix(".png")
    images[0].save(apng, save_all=True, append_images=images[1:], duration=times, loop=0,
                   disposal=0, blend=0)
    elapsed = 0
    gif_times = []
    for duration in times:
        next_elapsed = elapsed + duration
        gif_times.append(max(10, (round(next_elapsed/10)-round(elapsed/10))*10))
        elapsed = next_elapsed
    images[0].save(path.with_suffix(".gif"), save_all=True, append_images=images[1:],
                   duration=gif_times, loop=0, disposal=2, optimize=False)
    return {"apng": str(apng), "gif": str(path.with_suffix('.gif')), "frames": len(images)}


def save_overview(animations, path, scale=3, count=48):
    """A presentation-only contact sheet; delivered animation timelines are untouched."""
    import math
    names = list(animations)
    first_frames, first_durations = animations[names[0]]
    tiles = {name: preview_frames(frames, name, scale, count) for name, (frames, _) in animations.items()}
    cw, ch = tiles[names[0]][0].size
    cols = min(4, len(names))
    images = []
    clocks = {name: np.cumsum(durations) for name, (_, durations) in animations.items()}
    time_ms = 0
    times = []
    for tick in range(count):
        canvas = Image.new("RGB", (cw*cols, ch*math.ceil(len(names)/cols)), (26, 26, 30))
        for j, name in enumerate(names):
            clock = clocks[name]
            index = int(np.searchsorted(clock, time_ms % int(clock[-1]), side="right"))
            # Rebuild label with the actual frame index, rather than changing delivery timing.
            image = tiles[name][index % count] if index < count else preview_frames(animations[name][0], name, scale)[index]
            canvas.paste(image, ((j % cols)*cw, (j//cols)*ch))
        ImageDraw.Draw(canvas).text((1, 1), f"preview tick {tick+1}/{count}", fill=(255, 210, 120))
        images.append(canvas)
        duration = first_durations[tick % len(first_durations)]
        times.append(duration)
        time_ms += duration
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(path.with_suffix(".png"), save_all=True, append_images=images[1:], duration=times, loop=0)
    images[0].save(path.with_suffix(".gif"), save_all=True, append_images=images[1:], duration=times,
                   loop=0, disposal=2, optimize=False)
