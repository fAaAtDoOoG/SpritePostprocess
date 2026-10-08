from __future__ import annotations

import copy
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import __version__
from .config import load_config
from .imaging import (clean_frames, cleanup_options, correct_zoom, ensure_bounds, frame_metrics,
                      letterbox, sequence_indices, union_bbox, warp)
from .matching import match_frames
from .media import (check_aseprite_canvas, create_aseprite, export_aseprite, find_aseprite, load_animation,
                    save_overview, save_previews, save_sheet, write_json)


def _needs_aseprite(config):
    return config["export"]["aseprite"] or any(
        Path(a[k]["path"]).suffix.lower() in (".ase", ".aseprite")
        for a in config["animations"] for k in ("source", "edited") if k in a)


def _prepare(entry, config, output, executable):
    name = entry["name"]
    source = load_animation(entry["source"], output / "work" / name / "source", executable)
    original_size = [source.frames[0].shape[1], source.frames[0].shape[0]]
    original_metrics = frame_metrics(source.frames)
    edited = None
    matches = None
    if "edited" in entry:
        edited = load_animation(entry["edited"], output / "work" / name / "edited", executable)
    if "frame_map" in entry:
        base_indices = sequence_indices(len(source.frames), entry["frame_map"])
        mapping = [(index, False) for index in base_indices]
        if edited and len(mapping) != len(edited.frames):
            raise ValueError(f"{name}: frame_map must have one entry per edited frame")
    elif edited:
        mapping, matches = match_frames(edited.frames, source.frames, entry.get("matching"))
        write_json(output / "matching" / f"{name}.json", matches)
        failed = [m["edited_index"] for m in matches if not m["accepted"]]
        if failed:
            raise ValueError(f"{name}: ambiguous/unmatched edited frames {failed}; inspect matching/{name}.json and provide an explicit frame_map. No approximate animation was delivered.")
    else:
        mapping = [(i, False) for i in range(len(source.frames))]
    selected = [np.ascontiguousarray(source.frames[i][:, ::-1] if mirrored else source.frames[i])
                for i, mirrored in mapping]
    times = edited.durations if edited else [source.durations[i] for i, _ in mapping]
    sequence = sequence_indices(len(selected), reverse=entry.get("reverse", False),
                                pingpong=entry.get("pingpong", "none"))
    frames = [selected[i].copy() for i in sequence]
    durations = [times[i] for i in sequence]
    lineage = [{"source": source.source, "source_index": mapping[i][0],
                "mirrored_horizontal": mapping[i][1], "edited_index": i if edited else None}
               for i in sequence]
    frames, source_cleanup = clean_frames(frames, config["cleanup"])
    frames = [letterbox(f, config["work_size"], config["resample"]) for f in frames]
    frames, zoom_scales = correct_zoom(frames, entry.get("zoom"), config["resample"])
    frames, working_cleanup = clean_frames(frames, config["cleanup"])
    if any(m["empty_frames"] for m in [frame_metrics(frames)]):
        raise ValueError(f"{name}: empty frame after cleanup; reduce cleanup strength or check input")
    report = {
        "source": source.source, "source_size": original_size,
        "source_frame_count": len(source.frames), "source_metrics": original_metrics,
        "source_at_least_work_resolution": all(a >= b for a, b in zip(original_size, config["work_size"])),
        "source_has_transparency": any(np.any(f[..., 3] < 255) for f in source.frames),
        "frame_count": len(frames), "durations_ms": durations, "lineage": lineage,
        "matching": matches, "source_cleanup": source_cleanup, "work_cleanup": working_cleanup,
        "zoom_scales": zoom_scales, "zoom_is_explicit": "zoom" in entry,
    }
    return {"frames": frames, "durations": durations, "lineage": lineage, "entry": entry,
            "group": entry.get("group", config["name"]), "report": report}


def _layout(prepared, config):
    layout = config["layout"]
    size = config["work_size"]
    groups = {}
    for name, item in prepared.items():
        box = union_bbox(item["frames"], layout["alpha_threshold"])
        item["box"] = box
        groups.setdefault(item["group"], []).append(name)
    scales = {}
    for group, names in groups.items():
        if layout["mode"] == "preserve":
            scales[group] = 1.0
            continue
        # One common scale for all animations in the group; never fit each frame separately.
        ax, ay = layout["anchor"]
        available_w = min(size[0]*layout["occupancy"], 2*min(ax, 1-ax)*size[0])
        available_h = min(size[1]*layout["occupancy"], ay*size[1])
        ratios = []
        for name in names:
            item = prepared[name]
            x0, y0, x1, y1 = item["box"]
            multiplier = item["entry"].get("scale_multiplier", 1)
            ratios += [available_w/((x1-x0)*multiplier), available_h/((y1-y0)*multiplier)]
        scale = min(ratios)
        scales[group] = scale if layout["allow_upscale"] else min(1, scale)
    for item in prepared.values():
        scale = scales[item["group"]] * item["entry"].get("scale_multiplier", 1)
        box = item["box"]
        if layout["mode"] == "preserve" and scale == 1:
            offset = (0.0, 0.0)
        elif layout["mode"] == "preserve":
            offset = (size[0]/2*(1-scale), size[1]/2*(1-scale))
        else:
            offset = (size[0]*layout["anchor"][0] - (box[0]+box[2])/2*scale,
                      size[1]*layout["anchor"][1] - box[3]*scale)
        for index, frame in enumerate(item["frames"]):
            ensure_bounds(frame, size, scale, offset, f"{item['entry']['name']} frame {index}")
        transformed = [warp(frame, size, scale, offset, config["resample"]) for frame in item["frames"]]
        item["frames"], cleanup = clean_frames(transformed, config["cleanup"])
        item["report"].update(shared_group=item["group"], shared_group_scale=scales[item["group"]],
                              actual_scale=scale, fixed_offset=list(offset),
                              layout_cleanup=cleanup, work_metrics=frame_metrics(item["frames"]))
    return scales


def _size_name(size):
    return f"{size[0]}px" if size[0] == size[1] else f"{size[0]}x{size[1]}px"


def _resolve_mirrors(entries, sized, prepared, config):
    pending = [e for e in entries if "mirror_of" in e]
    while pending:
        progress = False
        for entry in pending[:]:
            source, name = entry["mirror_of"], entry["name"]
            if source not in prepared:
                continue
            horizontal = entry.get("axis", "horizontal") == "horizontal"
            for animations in sized.values():
                animations[name] = [np.ascontiguousarray(frame[:, ::-1] if horizontal else frame[::-1])
                                    for frame in animations[source]]
            parent = prepared[source]
            lineage = copy.deepcopy(parent["lineage"])
            for frame in lineage:
                key = "mirrored_horizontal" if horizontal else "mirrored_vertical"
                frame[key] = not frame.get(key, False)
            prepared[name] = {"entry": entry, "durations": list(parent["durations"]), "lineage": lineage,
                              "report": {"mirror_of": source, "axis": entry.get("axis", "horizontal"),
                                         "frame_count": len(lineage), "durations_ms": parent["durations"],
                                         "lineage": lineage}, "group": parent["group"]}
            if "loop" not in entry:
                entry["loop"] = parent["entry"].get("loop", True)
            pending.remove(entry)
            progress = True
        if not progress:
            raise ValueError("Mirror references contain a cycle")


def process(config_path, log=print):
    config = load_config(config_path)
    cleanup_options(config["cleanup"])
    executable = find_aseprite(config["aseprite"]) if _needs_aseprite(config) else None
    output = Path(config["output"])
    if output.exists():
        raise FileExistsError(f"Output already exists; choose a new directory (sources/results are never overwritten): {output}")
    for entry in config["animations"]:
        for key in ("source", "edited"):
            if key in entry and not Path(entry[key]["path"]).exists():
                raise FileNotFoundError(entry[key]["path"])
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "config.resolved.json", config)
    report = {"tool_version": __version__, "status": "processing", "animations": {},
              "exports": [], "previews": [], "warnings": [], "config": "config.resolved.json"}
    try:
        prepared = {}
        for entry in config["animations"]:
            if "mirror_of" not in entry:
                log(f"Prepare {entry['name']}")
                item = _prepare(entry, config, output, executable)
                prepared[entry["name"]] = item
                if not item["report"]["source_at_least_work_resolution"]:
                    report["warnings"].append(f"{entry['name']}: input is smaller than work canvas; upscaling cannot recover missing detail.")
                if not item["report"]["source_has_transparency"]:
                    report["warnings"].append(f"{entry['name']}: no transparency found; edge cleanup is not a background segmentation model.")
        if not prepared:
            raise ValueError("At least one animation needs a real source")
        report["group_scales"] = _layout(prepared, config)
        sizes = {tuple(size) for size in config["sizes"]}
        if config["export"]["previews"]:
            sizes.update(tuple(size) for size in config["export"]["preview_sizes"])
        sized = {}
        for size in sorted(sizes, reverse=True):
            sized[size] = {}
            for name, item in prepared.items():
                log(f"Resize/clean {name} -> {size[0]}x{size[1]}")
                # Each target is generated directly from the working resolution, never from the 64px result.
                frames = [letterbox(f, size, config["resample"]) for f in item["frames"]]
                frames, cleanup = clean_frames(frames, config["cleanup"])
                if frame_metrics(frames)["empty_frames"]:
                    raise ValueError(f"{name}: empty output frame at {size}")
                sized[size][name] = frames
                item["report"].setdefault("sizes", {})[_size_name(size)] = {
                    "cleanup": cleanup, "metrics": frame_metrics(frames)}
                residual = sum(c["detector_residual"] or 0 for c in cleanup)
                if residual:
                    report["warnings"].append(f"{name} {_size_name(size)}: {residual} edge-color candidates remain after configured cleanup passes.")
                edge_frames = frame_metrics(frames)["edge_frames"]
                if edge_frames:
                    report["warnings"].append(f"{name} {_size_name(size)}: visible pixels touch canvas edge in frames {edge_frames}; inspect margins.")
        _resolve_mirrors(config["animations"], sized, prepared, config)
        for entry in config["animations"]:
            name = entry["name"]
            item = prepared[name]
            report["animations"][name] = item["report"]
            for size_list in config["sizes"]:
                size = tuple(size_list)
                frames = sized[size][name]
                folder = output / _size_name(size)
                sheet = folder / "sheets" / f"{name}.png"
                save_sheet(frames, sheet)
                manifest = {
                    "version": 1, "name": name, "size": list(size), "sheet": sheet.name,
                    "frame_count": len(frames), "loop": entry.get("loop", True),
                    "coordinate_origin": "top_left", "trimmed": False,
                    "unity": config["unity"],
                    "frames": [dict(index=i, filename=f"{name}_{i:04d}",
                                    rect={"x": i*size[0], "y": 0, "w": size[0], "h": size[1]},
                                    duration_ms=item["durations"][i], provenance=item["lineage"][i])
                               for i in range(len(frames))],
                }
                manifest_path = sheet.with_suffix(".json")
                write_json(manifest_path, manifest)
                record = {"name": name, "size": list(size), "sheet": str(sheet.relative_to(output)),
                          "manifest": str(manifest_path.relative_to(output)), "aseprite": None,
                          "png_frames": [], "mirror_of": entry.get("mirror_of"),
                          "mirror_axis": entry.get("axis", "horizontal")}
                if config["export"]["aseprite"]:
                    log(f"Export Aseprite {name} {_size_name(size)}")
                    ase = folder / "aseprite" / f"{name}.aseprite"
                    create_aseprite(sheet, ase, size, item["durations"], name, executable)
                    record["aseprite"] = str(ase.relative_to(output))
                if config["export"]["png_frames"]:
                    frames_dir = folder / "frames" / name
                    frames_dir.mkdir(parents=True, exist_ok=True)
                    for i, frame in enumerate(frames):
                        frame_path = frames_dir / f"{i:04d}.png"
                        Image.fromarray(frame).save(frame_path)
                        record["png_frames"].append(str(frame_path.relative_to(output)))
                # Sheets + manifests are also the validation/deployment contract, so keep them.
                report["exports"].append(record)
        if config["export"]["previews"]:
            for size_list in config["export"]["preview_sizes"]:
                size = tuple(size_list)
                folder = output / "previews" / _size_name(size)
                for name in prepared:
                    frames, durations = sized[size][name], prepared[name]["durations"]
                    for label, count in (("original", len(frames)), (f"{config['export']['preview_frames']}f", config["export"]["preview_frames"])):
                        result = save_previews(frames, durations, folder / f"{name}_{label}", name,
                                               config["export"]["preview_scale"], count)
                        result["apng"] = str(Path(result["apng"]).relative_to(output))
                        result["gif"] = str(Path(result["gif"]).relative_to(output))
                        result["durations_ms"] = [durations[i % len(durations)] for i in range(count)]
                        report["previews"].append(result)
                save_overview({name: (sized[size][name], prepared[name]["durations"]) for name in prepared},
                              folder / f"all_{config['export']['preview_frames']}f", min(4, config["export"]["preview_scale"]),
                              config["export"]["preview_frames"])
        report["status"] = "exported"
        write_json(output / "report.json", report)
        log("Verify file counts, timing, dimensions, mirrors and Aseprite pixel round-trips")
        verification = verify(output, executable)
        write_json(output / "verification.json", verification)
        if verification["status"] != "passed":
            raise RuntimeError("Output validation failed: " + "; ".join(verification["errors"]))
        report["status"] = "complete"
        write_json(output / "report.json", report)
        if config["export"]["zip"]:
            archive = output / f"{config['name']}_delivery.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                for path in sorted(output.rglob("*")):
                    if path.is_file() and path != archive and "work" not in path.relative_to(output).parts:
                        zipped.write(path, path.relative_to(output).as_posix())
        log(f"Completed: {output}")
        return report
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        write_json(output / "report.json", report)
        raise


def verify(output, executable=None):
    output = Path(output).resolve()
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    errors, checked = [], []
    if not report.get("exports"):
        return {"status": "failed", "errors": ["No exported animations"], "checked": []}
    config = json.loads((output / "config.resolved.json").read_text(encoding="utf-8"))
    expected_keys = {(a["name"], tuple(size)) for a in config["animations"] for size in config["sizes"]}
    actual_keys = [(r["name"], tuple(r["size"])) for r in report["exports"]]
    if set(actual_keys) != expected_keys or len(actual_keys) != len(expected_keys):
        errors.append("Export list does not match configured animation/size combinations")
    if any(r["aseprite"] for r in report["exports"]):
        executable = find_aseprite(executable or "auto")
    with tempfile.TemporaryDirectory(prefix="spritepost_verify_") as temporary:
        cache = Path(temporary)
        loaded = {}
        for i, record in enumerate(report["exports"]):
            try:
                data = json.loads((output / record["manifest"]).read_text(encoding="utf-8"))
                sheet = output / record["sheet"]
                reference = load_animation({"path": str(sheet), "metadata": str(output / record["manifest"])}, cache, executable)
                if len(reference.frames) != data["frame_count"] or any((f.shape[1], f.shape[0]) != tuple(record["size"]) for f in reference.frames):
                    raise ValueError("Frame count or dimensions mismatch")
                expected_rects = [{"x": j*record["size"][0], "y": 0, "w": record["size"][0], "h": record["size"][1]}
                                  for j in range(len(reference.frames))]
                if [f["rect"] for f in data["frames"]] != expected_rects:
                    raise ValueError("Manifest rectangles are not the expected complete, ordered full-canvas grid")
                if any(np.any(f[f[..., 3] == 0, :3] != 0) for f in reference.frames):
                    raise ValueError("Nonzero RGB in fully transparent pixels")
                expected = report["animations"][record["name"]]["durations_ms"]
                if reference.durations != expected:
                    raise ValueError("Durations differ from recorded source timeline")
                if record["aseprite"]:
                    check_aseprite_canvas(output / record["aseprite"], executable)
                    actual = export_aseprite(output / record["aseprite"], cache / str(i), executable)
                    if actual.durations != reference.durations or len(actual.frames) != len(reference.frames):
                        raise ValueError("Aseprite round-trip changed frame count or durations")
                    if any(not np.array_equal(a, b) for a, b in zip(actual.frames, reference.frames)):
                        raise ValueError("Aseprite round-trip pixels differ from delivered PNG")
                for j, frame_path in enumerate(record.get("png_frames", [])):
                    if not np.array_equal(np.asarray(Image.open(output / frame_path).convert("RGBA")), reference.frames[j]):
                        raise ValueError("PNG frame differs from sheet")
                loaded[(record["name"], tuple(record["size"]))] = reference
                checked.append({"name": record["name"], "size": record["size"], "frames": len(reference.frames),
                                "duration_ms": sum(reference.durations), "aseprite_roundtrip": bool(record["aseprite"]),
                                "full_canvas_cels": bool(record["aseprite"])})
            except Exception as error:
                errors.append(f"{record['name']} {record['size']}: {error}")
        for record in report["exports"]:
            if not record.get("mirror_of"):
                continue
            try:
                actual = loaded[(record["name"], tuple(record["size"]))]
                source = loaded[(record["mirror_of"], tuple(record["size"]))]
                if actual.durations != source.durations:
                    raise ValueError("Mirror durations mismatch")
                for a, b in zip(actual.frames, source.frames):
                    mirror = b[:, ::-1] if record["mirror_axis"] == "horizontal" else b[::-1]
                    if not np.array_equal(a, mirror):
                        raise ValueError("Mirror is not pixel-exact")
            except Exception as error:
                errors.append(f"Mirror {record['name']}: {error}")
        for preview in report.get("previews", []):
            try:
                with Image.open(output / preview["apng"]) as image:
                    if image.n_frames != preview["frames"]:
                        raise ValueError("APNG frame count mismatch")
                    times = []
                    for i in range(image.n_frames):
                        image.seek(i)
                        times.append(round(image.info["duration"]))
                    if times != preview["durations_ms"]:
                        raise ValueError("APNG durations mismatch")
                with Image.open(output / preview["gif"]) as image:
                    if image.n_frames != preview["frames"]:
                        raise ValueError("GIF frame count mismatch")
            except Exception as error:
                errors.append(f"Preview {preview['apng']}: {error}")
    return {"status": "passed" if not errors else "failed", "errors": errors, "checked": checked,
            "preview_count": len(report.get("previews", [])),
            "evidence": "file_integrity_and_aseprite_roundtrip; not visual or game-runtime acceptance"}
