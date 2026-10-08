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

from spritepost import __version__
from spritepost.i18n import diagnostic, progress, resolve_language, text


def init_config(args):
    from spritepost.config import DEFAULTS
    from spritepost.media import write_json
    source = Path(args.input).expanduser().resolve()
    destination = Path(args.output).expanduser().resolve()
    result_dir = Path(args.result_dir).expanduser().resolve()
    language = getattr(args, "lang", resolve_language())
    if destination.exists():
        raise FileExistsError(text("config_exists", language, path=destination))
    if destination == result_dir or destination.is_relative_to(result_dir):
        raise ValueError(text("config_inside_output", language))
    if not source.exists():
        raise FileNotFoundError(source)
    paths = [source] if source.is_file() else sorted(p for p in source.rglob("*")
                                                   if p.suffix.lower() in (".aseprite", ".ase"))
    if not paths and source.is_dir():
        paths = sorted(p for p in source.rglob("*.png") if p.with_suffix(".json").exists())
    if not paths:
        raise ValueError(text("no_inputs", language))
    config = copy.deepcopy(DEFAULTS)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem).strip("_.-") or "character"
    config.update(name=name, output=str(result_dir), aseprite=args.aseprite or "auto")
    if args.preset == "pixel-character":
        config["cleanup"] = {"profile": "strict"}
        config["layout"]["mode"] = "shared_fit"
    used = set()
    for path in paths:
        relative = path.relative_to(source) if source.is_dir() else Path(path.name)
        animation_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", "__".join(relative.with_suffix("").parts)).strip("_.-") or "animation"
        if animation_name.casefold() in used:
            raise ValueError(text("name_collision", language, name=animation_name))
        used.add(animation_name.casefold())
        spec = {"path": str(path)}
        if path.suffix.lower() == ".png":
            spec["metadata"] = str(path.with_suffix(".json"))
        config["animations"].append({"name": animation_name, "source": spec})
    write_json(destination, config)
    print(text("created", language, path=destination, count=len(paths), preset=args.preset), flush=True)
    print(text("review", language), flush=True)
    return 0


def build_parser(language):
    def tr(key):
        return text(key, language)

    class LocalizedParser(argparse.ArgumentParser):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._positionals.title = tr("positionals")
            self._optionals.title = tr("options")
            for action in self._actions:
                if isinstance(action, argparse._HelpAction):
                    action.help = tr("help")

        def format_usage(self):
            return super().format_usage().replace("usage:", tr("usage"), 1)

        def format_help(self):
            return super().format_help().replace("usage:", tr("usage"), 1)

        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"{tr('error')}: {diagnostic(ValueError(message), language)}\n")

    parser = LocalizedParser(prog="spritepost.py", description=tr("description"))
    parser.add_argument("--lang", choices=("en", "zh-CN"), default=language, help=tr("language"))
    parser.add_argument("--version", action="version", version=f"SpritePostprocess {__version__}", help=tr("version"))
    commands = parser.add_subparsers(dest="command", required=True, title=tr("commands"))

    def command(name):
        sub = commands.add_parser(name, help=tr(name), description=tr(name))
        sub.add_argument("--lang", choices=("en", "zh-CN"), default=argparse.SUPPRESS, help=tr("language"))
        return sub

    initialize = command("init")
    initialize.add_argument("--input", required=True, help=tr("input"))
    initialize.add_argument("--output", required=True, help=tr("config_output"))
    initialize.add_argument("--result-dir", required=True, help=tr("result_dir"))
    initialize.add_argument("--preset", choices=("neutral", "pixel-character"), default="neutral", help=tr("preset"))
    initialize.add_argument("--aseprite", help=tr("aseprite"))
    process_parser = command("process")
    process_parser.add_argument("config", help=tr("config"))
    verify_parser = command("verify")
    verify_parser.add_argument("output", help=tr("output"))
    verify_parser.add_argument("--aseprite", help=tr("aseprite"))
    inspect_parser = command("inspect")
    inspect_parser.add_argument("file", help=tr("file"))
    inspect_parser.add_argument("--aseprite", help=tr("aseprite"))
    inspect_parser.add_argument("--frame-size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"), help=tr("frame_size"))
    inspect_parser.add_argument("--metadata", help=tr("metadata"))
    inspect_parser.add_argument("--fps", type=float, help=tr("fps"))
    doctor = command("doctor")
    doctor.add_argument("--aseprite", help=tr("aseprite"))
    check = command("unity-check")
    check.add_argument("directory", help=tr("directory"))
    check.add_argument("--config", help=tr("config"))
    deploy = command("deploy")
    for key in ("sheet", "manifest", "destination", "backup_dir"):
        deploy.add_argument("--" + key.replace("_", "-"), required=True, help=tr(key))
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument("--lang", choices=("en", "zh-CN"), default=resolve_language())
    language = language_parser.parse_known_args(argv)[0].lang
    parser = build_parser(language)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return init_config(args)
        if args.command == "process":
            from spritepost.pipeline import process
            process(args.config, log=lambda message: print(progress(message, language), flush=True))
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
                aseprite = diagnostic(error, language)
            try:
                import tkinter
                gui = text("tk_available", language, version=tkinter.TkVersion)
            except ImportError:
                gui = text("tk_missing", language)
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
        print(f"{text('error', language)}: {diagnostic(error, language)}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
