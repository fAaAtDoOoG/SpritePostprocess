#!/usr/bin/env python3
"""Portable CLI entry point. No project is mutated unless deploy is invoked explicitly."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def init_config(args):
    from spritepost.config import DEFAULTS
    from spritepost.media import write_json
    source = Path(args.input).expanduser().resolve()
    destination = Path(args.output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Config already exists: {destination}")
    if not source.exists():
        raise FileNotFoundError(source)
    paths = [source] if source.is_file() else sorted(p for p in source.rglob("*")
                                                   if p.suffix.lower() in (".aseprite", ".ase"))
    if not paths and source.is_dir():
        paths = sorted(p for p in source.rglob("*.png") if p.with_suffix(".json").exists())
    if not paths:
        raise ValueError("No Aseprite assets or PNG+JSON sheets found. For loose PNG sequences use an explicit source with type=sequence and fps/durations_ms.")
    config = copy.deepcopy(DEFAULTS)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem).strip("_.-") or "character"
    config.update(name=name, output=str(Path(args.result_dir).resolve()), aseprite=args.aseprite or "auto")
    if args.preset == "pixel-character":
        config["cleanup"] = {"profile": "strict"}
        config["layout"]["mode"] = "shared_fit"
    used = set()
    for path in paths:
        relative = path.relative_to(source) if source.is_dir() else Path(path.name)
        animation_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", "__".join(relative.with_suffix("").parts)).strip("_.-") or "animation"
        if animation_name.casefold() in used:
            raise ValueError(f"File names collide after sanitization: {animation_name}; create config explicitly")
        used.add(animation_name.casefold())
        spec = {"path": str(path)}
        if path.suffix.lower() == ".png":
            spec["metadata"] = str(path.with_suffix(".json"))
        config["animations"].append({"name": animation_name, "source": spec})
    write_json(destination, config)
    print(f"Created {destination} ({len(paths)} animations, preset={args.preset})", flush=True)
    print("Review cleanup, group, mirrors and source resolution before processing. Input frame count/timing are read from file contents, not filenames.", flush=True)
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="SpritePostprocess: project-independent animation post-processing")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="Create an editable job config; never modifies inputs")
    initialize.add_argument("--input", required=True)
    initialize.add_argument("--output", required=True, help="New config file")
    initialize.add_argument("--result-dir", required=True, help="New result directory")
    initialize.add_argument("--preset", choices=("neutral", "pixel-character"), default="neutral")
    initialize.add_argument("--aseprite")
    process_parser = commands.add_parser("process", help="Execute a job into a new directory")
    process_parser.add_argument("config")
    verify_parser = commands.add_parser("verify", help="Reopen and verify previously exported files")
    verify_parser.add_argument("output")
    verify_parser.add_argument("--aseprite")
    inspect_parser = commands.add_parser("inspect", help="Inspect actual frame count/durations and occupancy")
    inspect_parser.add_argument("file")
    inspect_parser.add_argument("--aseprite")
    inspect_parser.add_argument("--frame-size", type=int, nargs=2)
    inspect_parser.add_argument("--metadata")
    inspect_parser.add_argument("--fps", type=float)
    doctor = commands.add_parser("doctor", help="Read-only dependency diagnostics")
    doctor.add_argument("--aseprite")
    check = commands.add_parser("unity-check", help="Read-only static Unity import audit (not runtime acceptance)")
    check.add_argument("directory")
    check.add_argument("--config")
    deploy = commands.add_parser("deploy", help="Explicit safe PNG replacement; preserve meta and back up original")
    deploy.add_argument("--sheet", required=True)
    deploy.add_argument("--manifest", required=True)
    deploy.add_argument("--destination", required=True)
    deploy.add_argument("--backup-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return init_config(args)
        if args.command == "process":
            from spritepost.pipeline import process
            process(args.config, log=lambda message: print(message, flush=True))
            return 0
        if args.command == "verify":
            from spritepost.pipeline import verify
            result = verify(args.output, args.aseprite)
        elif args.command == "inspect":
            from spritepost.imaging import frame_metrics
            from spritepost.media import find_aseprite, load_animation
            spec = {"path": str(Path(args.file).resolve())}
            if args.frame_size:
                spec["frame_size"] = args.frame_size
            if args.metadata:
                spec["metadata"] = args.metadata
            if args.fps:
                spec["fps"] = args.fps
            executable = find_aseprite(args.aseprite or "auto") if Path(args.file).suffix.lower() in (".ase", ".aseprite") else None
            with tempfile.TemporaryDirectory(prefix="spritepost_inspect_") as cache:
                source = load_animation(spec, Path(cache), executable)
                result = {"source": source.source, "size": [source.frames[0].shape[1], source.frames[0].shape[0]],
                          "frames": len(source.frames), "durations_ms": source.durations,
                          "total_duration_ms": sum(source.durations), "metrics": frame_metrics(source.frames)}
        elif args.command == "doctor":
            import cv2
            import numpy
            import PIL
            from spritepost.media import find_aseprite
            try:
                aseprite = find_aseprite(args.aseprite or "auto")
            except FileNotFoundError as error:
                aseprite = str(error)
            try:
                import tkinter
                gui = f"Tk {tkinter.TkVersion} (import only, display not opened)"
            except ImportError:
                gui = "unavailable; CLI still usable"
            result = {"python": sys.executable, "python_version": sys.version, "opencv": cv2.__version__,
                      "numpy": numpy.__version__, "pillow": PIL.__version__, "aseprite": aseprite, "gui": gui}
        elif args.command == "unity-check":
            from spritepost.unity import check_unity
            settings = None
            if args.config:
                from spritepost.config import load_config
                settings = load_config(args.config)["unity"]
            result = check_unity(Path(args.directory), settings)
        elif args.command == "deploy":
            from spritepost.unity import deploy_png
            result = deploy_png(Path(args.sheet), Path(args.destination),
                                json.loads(Path(args.manifest).read_text(encoding="utf-8-sig")), Path(args.backup_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") == "failed" else 0
    except (ValueError, OSError, RuntimeError, KeyError, ImportError) as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
