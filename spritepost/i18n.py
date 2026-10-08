"""Human-readable CLI text. Config keys and machine-readable reports stay stable."""
from __future__ import annotations

import locale
import os
import re


TEXT = {
    "description": ("SpritePostprocess: project-independent sprite animation post-processing",
                    "SpritePostprocess：跨项目的精灵动画后处理工具"),
    "language": ("Interface language (also accepts SPRITEPOST_LANG)", "界面语言（也可设置 SPRITEPOST_LANG）"),
    "help": ("Show this help message and exit", "显示帮助并退出"),
    "version": ("Show the tool version and exit", "显示工具版本并退出"),
    "usage": ("usage:", "用法："),
    "positionals": ("positional arguments", "位置参数"),
    "options": ("options", "选项"),
    "commands": ("commands", "命令"),
    "error": ("ERROR", "错误"),
    "init": ("Create an editable job config without modifying inputs", "创建任务配置，不修改原素材"),
    "process": ("Process a saved config into a new output directory", "根据已保存配置处理，输出到新目录"),
    "verify": ("Reopen outputs and verify frames, timing and pixels", "重新打开交付，检查帧数、时长和像素"),
    "inspect": ("Inspect actual frame count, durations and canvas occupancy", "读取真实帧数、时长和画布占比"),
    "doctor": ("Check Python dependencies and Aseprite without making changes", "只读检查 Python 依赖与 Aseprite"),
    "unity-check": ("Read-only Unity import metadata check", "只读检查 Unity 导入元数据"),
    "deploy": ("Replace one PNG explicitly; back up originals and keep Unity metadata", "明确替换单个 PNG：备份原文件并保留 Unity 元数据"),
    "input": ("Source asset file or folder", "素材文件或目录"),
    "config_output": ("New JSON config path, outside the result directory", "新 JSON 配置路径，须在结果目录之外"),
    "result_dir": ("New, not-yet-existing result directory", "尚不存在的结果目录"),
    "preset": ("neutral preserves placement; pixel-character fits and cleans edges", "neutral 保留位置；pixel-character 调整占比并清理白边"),
    "aseprite": ("Aseprite executable path (or set SPRITEPOST_ASEPRITE)", "Aseprite 程序路径（也可设置 SPRITEPOST_ASEPRITE）"),
    "config": ("Saved job configuration JSON", "已保存的任务配置 JSON"),
    "output": ("Previously generated result directory", "已经生成的结果目录"),
    "file": ("Aseprite asset or PNG sheet to inspect", "待检查的 Aseprite 或 PNG 图集"),
    "frame_size": ("PNG frame width and height", "PNG 单帧宽度和高度"),
    "metadata": ("PNG sheet metadata JSON", "PNG 图集的元数据 JSON"),
    "fps": ("Timing for a PNG source without durations", "无时长信息的 PNG 素材帧率"),
    "directory": ("Only this Unity asset directory is checked", "只检查这个 Unity 资产目录"),
    "sheet": ("Generated fixed-grid PNG sheet", "生成的固定网格 PNG 图集"),
    "manifest": ("Matching per-frame manifest JSON", "对应的逐帧 manifest JSON"),
    "destination": ("Explicit target PNG path", "明确指定目标 PNG 路径"),
    "backup_dir": ("Backup directory outside Assets and the target folder", "备份目录，不能放入 Assets 或目标目录"),
    "created": ("Created {path} ({count} animations, preset={preset})", "已创建 {path}（{count} 个动画，预设={preset}）"),
    "review": ("Review cleanup, groups and mirror settings before processing. Frame counts and timing come from file contents, not filenames.",
               "处理前请确认去白强度、尺寸分组和镜像设置。帧数与时长读取自文件内容，不依据文件名。"),
    "config_exists": ("Config already exists: {path}", "配置文件已存在：{path}"),
    "no_inputs": ("No Aseprite assets or PNG+JSON sheets found. For loose PNG sequences use an explicit type=sequence source and fps/durations_ms.",
                  "未发现 Aseprite 或 PNG+JSON 图集。逐帧 PNG 请在高级配置中设置 type=sequence，并指定 fps 或 durations_ms。"),
    "name_collision": ("File names collide after sanitization: {name}; specify animation names in the config", "文件名规范化后重名：{name}；请在配置中明确指定动画名称"),
    "config_inside_output": ("Keep the config outside the result directory; processing creates a new directory.", "请将配置保存在结果目录之外；处理时需要创建全新目录。"),
    "prepare": ("Prepare {name}", "准备素材：{name}"),
    "resize": ("Resize/clean {detail}", "缩放并清理：{detail}"),
    "export_ase": ("Export Aseprite {detail}", "导出 Aseprite：{detail}"),
    "verify_progress": ("Verify file counts, timing, dimensions, mirrors and Aseprite pixel round-trips", "检查帧数、时长、尺寸、镜像与 Aseprite 往返像素"),
    "completed": ("Completed: {path}", "处理完成：{path}"),
    "tk_available": ("Tk {version} (import only, display not opened)", "Tk {version}（已检测模块，未打开窗口）"),
    "tk_missing": ("Unavailable; CLI is still usable", "Tkinter 不可用，仍可使用命令行"),
    "missing_dependency": ("Missing Python dependency. Use the configured environment, or install requirements.txt into your chosen environment. Details: {detail}",
                           "缺少 Python 依赖。请使用配置的运行环境，或在选定环境中安装 requirements.txt。详情：{detail}"),
    "output_exists": ("Output already exists. Choose a NEW result folder; existing files are not overwritten. {path}", "结果目录已存在。请选择新目录，工具不会覆盖已有文件。{path}"),
    "raw_error": ("{detail}", "{detail}"),
}


def resolve_language(value=None):
    selected = value or os.environ.get("SPRITEPOST_LANG")
    if not selected:
        try:
            selected = locale.getlocale()[0]
        except (ValueError, TypeError):
            selected = None
    return "zh-CN" if str(selected or "en").lower().startswith("zh") else "en"


def text(key, language="en", **values):
    return TEXT[key][1 if resolve_language(language) == "zh-CN" else 0].format(**values)


def progress(message, language):
    for prefix, key, argument in (("Prepare ", "prepare", "name"),
                                  ("Resize/clean ", "resize", "detail"),
                                  ("Export Aseprite ", "export_ase", "detail"),
                                  ("Completed: ", "completed", "path")):
        if message.startswith(prefix):
            return text(key, language, **{argument: message[len(prefix):]})
    if message.startswith("Verify file counts,"):
        return text("verify_progress", language)
    return message


def diagnostic(error, language):
    value = str(error)
    if isinstance(error, ImportError):
        return text("missing_dependency", language, detail=value)
    if value.startswith("Output already exists;"):
        return text("output_exists", language, path=value.split("): ", 1)[-1])
    if resolve_language(language) != "zh-CN":
        return value
    replacements = (
        (r"^the following arguments are required: (.*)$", r"缺少必需参数：\1"),
        (r"^unrecognized arguments: (.*)$", r"无法识别的参数：\1"),
        (r"^argument (.*?): expected one argument$", r"参数 \1 需要一个值。"),
        (r"^argument (.*?): invalid choice: (.*?) \(choose from (.*?)\)$", r"参数 \1 的值 \2 无效；可选值：\3"),
        (r"^Unknown (.*?) setting\(s\): (.*)$", r"未知配置项（\1）：\2"),
        (r"^(.*?): ambiguous/unmatched edited frames (.*?); inspect (.*?) and provide an explicit frame_map\. No approximate animation was delivered\.$",
         r"\1：编辑帧 \2 无法可靠匹配。请检查 \3，并提供明确的 frame_map。未交付近似替代动画。"),
        (r"^Aseprite executable not found: (.*)$", r"找不到 Aseprite 程序：\1"),
        (r"^Aseprite not found\..*$", "找不到 Aseprite。请设置配置中的 aseprite 或环境变量 SPRITEPOST_ASEPRITE；纯 PNG 处理可关闭 export.aseprite。"),
        (r"^Output must be separate from input folders/files$", "结果目录必须与输入文件或目录分离。"),
        (r"^Unsupported config version \(expected 1\)$", "不支持的配置版本，当前要求 version: 1。"),
        (r"^animations must not be empty$", "animations 不能为空，请先选择素材并创建配置。"),
        (r"^Frame durations must match frame count and be integer milliseconds in 1\.\.65535$", "每帧时长必须与帧数一致，并为 1 到 65535 的整数毫秒。"),
        (r"^PNG input needs metadata durations, durations_ms or fps; timing is not guessed$", "PNG 输入必须提供元数据时长、durations_ms 或 fps；工具不会猜测时长。"),
        (r"^Mirror references contain a cycle$", "镜像引用形成循环，请检查 mirror_of。"),
        (r"^(.+): transform would crop visible pixels\..*$", r"\1：当前变换将裁掉可见像素。请降低 zoom/scale_multiplier 或增加源素材留白。"),
    )
    for pattern, replacement in replacements:
        if re.search(pattern, value):
            return re.sub(pattern, replacement, value)
    return value
