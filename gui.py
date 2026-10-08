from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_config import (
    PREFERENCES_FILE,
    common_from_config,
    config_is_inside_output,
    load_language_preference,
    localized_validation_error,
    merge_common,
    save_language_preference,
    suggested_paths,
)
from ui_strings import STRINGS, option_labels, text


APP_DIR = Path(__file__).resolve().parent
CLI_PATH = APP_DIR / "spritepost.py"
PREFERENCES_PATH = APP_DIR / PREFERENCES_FILE
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class SpritePostprocessGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.language = load_language_preference(PREFERENCES_PATH)
        self.root.geometry("1160x860")
        self.root.minsize(920, 680)

        self.source_var = tk.StringVar()
        self.result_var = tk.StringVar()
        self.config_var = tk.StringVar()
        self.aseprite_var = tk.StringVar(value=os.environ.get("SPRITEPOST_ASEPRITE", "auto") or "auto")
        self.preset_display_var = tk.StringVar()
        self.language_display_var = tk.StringVar()
        self.work_size_var = tk.StringVar(value="512×512")
        self.sizes_var = tk.StringVar(value="512×512, 64×64, 32×32")
        self.cleanup_display_var = tk.StringVar()
        self.layout_display_var = tk.StringVar()
        self.occupancy_var = tk.StringVar(value="90")
        self.preview_frames_var = tk.StringVar(value="48")
        self.export_aseprite_var = tk.BooleanVar(value=True)
        self.export_png_var = tk.BooleanVar(value=False)
        self.export_previews_var = tk.BooleanVar(value=True)
        self.export_zip_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar()

        self.option_tokens = {"preset": "pixel-character", "cleanup": "strict", "layout": "shared_fit"}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.busy_buttons: list[ttk.Button] = []
        self.saved_editor_text = ""
        self.form_snapshot: dict[str, object] | None = None
        self._status_key = "ready"
        self._status_values: dict[str, object] = {}
        self._text_widgets: list[tuple[tk.Widget, str, str]] = []

        self._build_ui()
        self._set_language(self.language, persist=False)
        self.root.after(80, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _t(self, key: str, **values: object) -> str:
        return text(self.language, key, **values)

    def _register_text(self, widget: tk.Widget, key: str, option: str = "text") -> tk.Widget:
        self._text_widgets.append((widget, option, key))
        widget.configure(**{option: self._t(key)})
        return widget

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        header.columnconfigure(0, weight=1)
        language_label = ttk.Label(header)
        self._register_text(language_label, "language")
        language_label.grid(row=0, column=1, padx=(12, 6))
        self.language_combo = ttk.Combobox(
            header, textvariable=self.language_display_var, state="readonly", width=18
        )
        self.language_combo.grid(row=0, column=2)
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_selected)

        create_group = ttk.Labelframe(outer, padding=8)
        self._register_text(create_group, "new_config_group")
        create_group.grid(row=1, column=0, sticky=tk.EW, pady=(0, 8))
        create_group.columnconfigure(1, weight=1)
        self._source_row(create_group, 0)
        self._path_row(create_group, 1, "config_path", self.config_var, self._choose_config_path)
        preset_label = ttk.Label(create_group)
        self._register_text(preset_label, "preset")
        preset_label.grid(row=2, column=0, sticky=tk.W, pady=3)
        self.preset_combo = ttk.Combobox(
            create_group, textvariable=self.preset_display_var, state="readonly", width=48
        )
        self.preset_combo.grid(row=2, column=1, sticky=tk.W, padx=(10, 6), pady=3)
        self.preset_combo.bind("<<ComboboxSelected>>", lambda _event: self._capture_option("preset"))
        preset_help = ttk.Label(create_group, foreground="#666666")
        self._register_text(preset_help, "preset_help")
        preset_help.grid(row=3, column=1, sticky=tk.W, padx=(10, 6), pady=(0, 4))
        create_actions = ttk.Frame(create_group)
        create_actions.grid(row=0, column=4, rowspan=4, sticky=tk.NS)
        self._action_button(create_actions, 0, "create_config", self._init_config, vertical=True)
        self._action_button(create_actions, 1, "open_config", self._open_config, vertical=True)

        content = ttk.Panedwindow(outer, orient=tk.VERTICAL)
        content.grid(row=2, column=0, sticky=tk.NSEW)
        self.notebook = ttk.Notebook(content)
        log_frame = ttk.Labelframe(content, padding=6)
        self._register_text(log_frame, "log_title")
        content.add(self.notebook, weight=4)
        content.add(log_frame, weight=2)

        common_tab = ttk.Frame(self.notebook, padding=10)
        advanced_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(common_tab, text=self._t("common_tab"))
        self.notebook.add(advanced_tab, text=self._t("advanced_tab"))
        self.common_tab = common_tab
        self.advanced_tab = advanced_tab
        self._build_common_tab(common_tab)
        self._build_advanced_tab(advanced_tab)
        self.log = self._scrolled_text(log_frame, wrap=tk.WORD, readonly=True)

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
        for column in range(7):
            actions.columnconfigure(column, weight=1)
        self._action_button(actions, 0, "save_config", self._save_config)
        self._action_button(actions, 1, "save_run", self._save_and_run)
        self._action_button(actions, 2, "verify", self._run_verify)
        self._action_button(actions, 3, "doctor", self._run_doctor)
        self._plain_button(actions, 4, "open_output", self._open_result_dir)
        self._plain_button(actions, 5, "help", self._open_help)
        self._plain_button(actions, 6, "clear_log", self._clear_log)

        status = ttk.Frame(outer)
        status.grid(row=4, column=0, sticky=tk.EW, pady=(7, 0))
        status_label = ttk.Label(status)
        self._register_text(status_label, "status")
        status_label.pack(side=tk.LEFT)
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT)

    def _build_common_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(3, weight=1)
        self._path_row(parent, 0, "output_path", self.result_var, self._choose_result)
        output_help = ttk.Label(parent, foreground="#666666")
        self._register_text(output_help, "output_help")
        output_help.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=(10, 6))
        self._path_row(parent, 2, "aseprite_path", self.aseprite_var, self._choose_aseprite)
        self._entry_row(parent, 3, "work_size", self.work_size_var, 0)
        self._entry_row(parent, 3, "output_sizes", self.sizes_var, 2)
        sizes_help = ttk.Label(parent, foreground="#666666")
        self._register_text(sizes_help, "sizes_help")
        sizes_help.grid(row=4, column=3, sticky=tk.W, padx=(10, 6))

        cleanup_label = ttk.Label(parent)
        self._register_text(cleanup_label, "cleanup")
        cleanup_label.grid(row=5, column=0, sticky=tk.W, pady=(8, 3))
        self.cleanup_combo = ttk.Combobox(parent, textvariable=self.cleanup_display_var, state="readonly", width=36)
        self.cleanup_combo.grid(row=5, column=1, sticky=tk.W, padx=(10, 6), pady=(8, 3))
        self.cleanup_combo.bind("<<ComboboxSelected>>", lambda _event: self._capture_option("cleanup"))
        layout_label = ttk.Label(parent)
        self._register_text(layout_label, "layout")
        layout_label.grid(row=5, column=2, sticky=tk.W, pady=(8, 3))
        self.layout_combo = ttk.Combobox(parent, textvariable=self.layout_display_var, state="readonly", width=36)
        self.layout_combo.grid(row=5, column=3, sticky=tk.W, padx=(10, 6), pady=(8, 3))
        self.layout_combo.bind("<<ComboboxSelected>>", lambda _event: self._capture_option("layout"))
        self._entry_row(parent, 6, "occupancy", self.occupancy_var, 0)
        self._entry_row(parent, 6, "preview_frames", self.preview_frames_var, 2)

        export_group = ttk.Labelframe(parent, padding=8)
        self._register_text(export_group, "export_group")
        export_group.grid(row=7, column=0, columnspan=4, sticky=tk.EW, pady=(10, 6))
        checks = (
            ("export_aseprite", self.export_aseprite_var),
            ("export_png_frames", self.export_png_var),
            ("export_previews", self.export_previews_var),
            ("export_zip", self.export_zip_var),
        )
        for column, (key, variable) in enumerate(checks):
            check = ttk.Checkbutton(export_group, variable=variable)
            self._register_text(check, key)
            check.grid(row=0, column=column, padx=(0, 18), sticky=tk.W)

        apply_button = ttk.Button(parent, command=self._apply_common_to_editor)
        self._register_text(apply_button, "apply_common")
        apply_button.grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(8, 3))
        apply_help = ttk.Label(parent, foreground="#666666", wraplength=720)
        self._register_text(apply_help, "apply_help")
        apply_help.grid(row=9, column=0, columnspan=4, sticky=tk.W)

    def _build_advanced_tab(self, parent: ttk.Frame) -> None:
        title = ttk.Label(parent)
        self._register_text(title, "json_title")
        title.pack(anchor=tk.W)
        help_label = ttk.Label(parent, foreground="#666666")
        self._register_text(help_label, "json_help")
        help_label.pack(anchor=tk.W, pady=(0, 5))
        self.editor = self._scrolled_text(parent, wrap=tk.NONE)

    def _path_row(self, parent: ttk.Frame, row: int, key: str, variable: tk.StringVar, command: object) -> None:
        label = ttk.Label(parent)
        self._register_text(label, key)
        label.grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, padx=(10, 6), pady=3)
        button = ttk.Button(parent, command=command)
        self._register_text(button, "browse")
        button.grid(row=row, column=2, pady=3)

    def _source_row(self, parent: ttk.Frame, row: int) -> None:
        label = ttk.Label(parent)
        self._register_text(label, "source_path")
        label.grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(parent, textvariable=self.source_var).grid(
            row=row, column=1, sticky=tk.EW, padx=(10, 6), pady=3
        )
        folder_button = ttk.Button(parent, command=self._choose_source_folder)
        self._register_text(folder_button, "choose_folder")
        folder_button.grid(row=row, column=2, padx=(0, 4), pady=3)
        file_button = ttk.Button(parent, command=self._choose_source_file)
        self._register_text(file_button, "choose_file")
        file_button.grid(row=row, column=3, pady=3)

    def _entry_row(self, parent: ttk.Frame, row: int, key: str, variable: tk.StringVar, column: int) -> None:
        label = ttk.Label(parent)
        self._register_text(label, key)
        label.grid(row=row, column=column, sticky=tk.W, pady=3)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=column + 1, sticky=tk.EW, padx=(10, 16 if column == 0 else 6), pady=3
        )

    def _action_button(self, parent: ttk.Frame, position: int, key: str, command: object, vertical: bool = False) -> None:
        button = ttk.Button(parent, command=command)
        self._register_text(button, key)
        if vertical:
            button.grid(row=position, column=0, padx=(8, 0), pady=(0, 5), sticky=tk.EW)
        else:
            button.grid(row=0, column=position, padx=(0 if position == 0 else 3, 3), sticky=tk.EW)
        self.busy_buttons.append(button)

    def _plain_button(self, parent: ttk.Frame, position: int, key: str, command: object) -> None:
        button = ttk.Button(parent, command=command)
        self._register_text(button, key)
        button.grid(row=0, column=position, padx=3, sticky=tk.EW)

    @staticmethod
    def _scrolled_text(parent: tk.Widget, *, wrap: str, readonly: bool = False) -> tk.Text:
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True)
        result = tk.Text(container, wrap=wrap, undo=not readonly, font=("Consolas", 10))
        y_scroll = ttk.Scrollbar(container, orient=tk.VERTICAL, command=result.yview)
        x_scroll = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=result.xview)
        result.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        result.grid(row=0, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=0, column=1, sticky=tk.NS)
        x_scroll.grid(row=1, column=0, sticky=tk.EW)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        if readonly:
            result.configure(state=tk.DISABLED)
        return result

    def _set_language(self, language: str, *, persist: bool = True) -> None:
        if language not in STRINGS:
            language = "en"
        self.language = language
        self.root.title(self._t("app_title"))
        for widget, option, key in self._text_widgets:
            widget.configure(**{option: self._t(key)})
        self.notebook.tab(self.common_tab, text=self._t("common_tab"))
        self.notebook.tab(self.advanced_tab, text=self._t("advanced_tab"))
        self.language_combo.configure(values=[text(code, "language_name") for code in STRINGS])
        self.language_display_var.set(text(language, "language_name"))
        for group, combo, variable in (
            ("preset", self.preset_combo, self.preset_display_var),
            ("cleanup", self.cleanup_combo, self.cleanup_display_var),
            ("layout", self.layout_combo, self.layout_display_var),
        ):
            labels = option_labels(language, group)
            combo.configure(values=list(labels.values()))
            variable.set(labels[self.option_tokens[group]])
        self._render_status()
        if persist:
            try:
                save_language_preference(PREFERENCES_PATH, language)
            except OSError as error:
                self._append_log(self._t("language_saved_warning", message=error) + "\n")

    def _on_language_selected(self, _event: object = None) -> None:
        chosen = self.language_display_var.get()
        for code in STRINGS:
            if chosen == text(code, "language_name"):
                self._set_language(code)
                return

    def _capture_option(self, group: str) -> None:
        variable = {
            "preset": self.preset_display_var,
            "cleanup": self.cleanup_display_var,
            "layout": self.layout_display_var,
        }[group]
        reverse = {label: token for token, label in option_labels(self.language, group).items()}
        token = reverse.get(variable.get())
        if token:
            self.option_tokens[group] = token

    def _common_values(self) -> dict[str, object]:
        self._capture_option("cleanup")
        self._capture_option("layout")
        return {
            "output": self.result_var.get().strip(),
            "aseprite": self.aseprite_var.get().strip() or "auto",
            "work_size": self.work_size_var.get().strip(),
            "sizes": self.sizes_var.get().strip(),
            "cleanup": self.option_tokens["cleanup"],
            "layout": self.option_tokens["layout"],
            "occupancy_percent": self.occupancy_var.get().strip(),
            "preview_frames": self.preview_frames_var.get().strip(),
            "export_aseprite": self.export_aseprite_var.get(),
            "export_png_frames": self.export_png_var.get(),
            "export_previews": self.export_previews_var.get(),
            "export_zip": self.export_zip_var.get(),
        }

    def _form_is_dirty(self) -> bool:
        return self.form_snapshot is not None and self._common_values() != self.form_snapshot

    def _sync_common_fields(self, data: dict, config_dir: Path) -> None:
        values = common_from_config(data)
        output = Path(str(values["output"])).expanduser()
        if not output.is_absolute():
            output = config_dir / output
        self.result_var.set(str(output.resolve()))
        aseprite = str(values["aseprite"])
        if aseprite != "auto":
            aseprite_path = Path(aseprite).expanduser()
            if not aseprite_path.is_absolute():
                aseprite_path = config_dir / aseprite_path
            aseprite = str(aseprite_path.resolve())
        self.aseprite_var.set(aseprite)
        self.work_size_var.set(str(values["work_size"]))
        self.sizes_var.set(str(values["sizes"]))
        self.option_tokens["cleanup"] = str(values["cleanup"])
        self.option_tokens["layout"] = str(values["layout"])
        self.cleanup_display_var.set(option_labels(self.language, "cleanup")[self.option_tokens["cleanup"]])
        self.layout_display_var.set(option_labels(self.language, "layout")[self.option_tokens["layout"]])
        self.occupancy_var.set(str(values["occupancy_percent"]))
        self.preview_frames_var.set(str(values["preview_frames"]))
        self.export_aseprite_var.set(bool(values["export_aseprite"]))
        self.export_png_var.set(bool(values["export_png_frames"]))
        self.export_previews_var.set(bool(values["export_previews"]))
        self.export_zip_var.set(bool(values["export_zip"]))
        self.form_snapshot = self._common_values()

    def _editor_data(self) -> dict:
        raw = self.editor.get("1.0", tk.END).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(self._t("invalid_json", line=error.lineno, column=error.colno, message=error.msg)) from error
        if not isinstance(data, dict):
            raise ValueError(self._t("root_object"))
        return data

    def _apply_common_to_editor(self, *, show_error: bool = True) -> bool:
        try:
            data = merge_common(self._editor_data(), self._common_values())
        except (ValueError, KeyError) as error:
            if show_error:
                messagebox.showerror(
                    self._t("invalid_settings_title"),
                    localized_validation_error(error, self.language),
                )
            return False
        editor_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        self._set_editor(editor_text)
        self.form_snapshot = self._common_values()
        self._set_status("settings_applied")
        return True

    def _set_source_and_suggestions(self, chosen: str) -> None:
        self.source_var.set(chosen)
        output, config = suggested_paths(chosen)
        if not self.result_var.get().strip():
            self.result_var.set(str(output))
        if not self.config_var.get().strip():
            self.config_var.set(str(config))

    def _choose_source_folder(self) -> None:
        chosen = filedialog.askdirectory(title=self._t("select_source_folder"))
        if chosen:
            self._set_source_and_suggestions(chosen)

    def _choose_source_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title=self._t("select_source_file"),
            filetypes=((self._t("animation_files"), "*.aseprite *.ase *.png"), (self._t("all_files"), "*.*")),
        )
        if chosen:
            self._set_source_and_suggestions(chosen)

    def _choose_result(self) -> None:
        chosen = filedialog.askdirectory(title=self._t("select_output"), mustexist=False)
        if chosen:
            self.result_var.set(chosen)
            if not self.config_var.get().strip():
                result_path = Path(chosen)
                self.config_var.set(str(result_path.with_name(result_path.name + ".spritepost.json")))

    def _choose_config_path(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title=self._t("select_config_save"), defaultextension=".json",
            filetypes=((self._t("json_files"), "*.json"), (self._t("all_files"), "*.*")),
        )
        if chosen:
            self.config_var.set(chosen)

    def _choose_aseprite(self) -> None:
        chosen = filedialog.askopenfilename(
            title=self._t("select_aseprite"),
            filetypes=((self._t("executables"), "*.exe"), (self._t("all_files"), "*.*")),
        )
        if chosen:
            self.aseprite_var.set(chosen)

    def _init_config(self) -> None:
        self._capture_option("preset")
        source = self.source_var.get().strip()
        result = self.result_var.get().strip()
        config = self.config_var.get().strip()
        if not source or not result:
            messagebox.showerror(self._t("missing_paths_title"), self._t("missing_paths"))
            return
        source_path = Path(source).expanduser().resolve()
        result_path = Path(result).expanduser().resolve()
        config_path = Path(config).expanduser().resolve() if config else result_path.with_name(result_path.name + ".spritepost.json")
        if config_is_inside_output(config_path, result_path):
            messagebox.showerror(self._t("output_inside_title"), self._t("output_inside"))
            return
        self.source_var.set(str(source_path))
        self.result_var.set(str(result_path))
        self.config_var.set(str(config_path))
        output_path = config_path
        replacing_existing = config_path.exists()
        if replacing_existing:
            if not messagebox.askyesno(self._t("overwrite_title"), self._t("overwrite_config", path=config_path)):
                return
            output_path = config_path.with_name(f".{config_path.name}.{uuid.uuid4().hex}.tmp.json")
        arguments = [
            "init", "--input", str(source_path), "--output", str(output_path),
            "--result-dir", str(result_path), "--preset", self.option_tokens["preset"],
        ]
        aseprite = self.aseprite_var.get().strip()
        if aseprite and aseprite != "auto":
            arguments.extend(("--aseprite", aseprite))

        def finish_init(return_code: int) -> None:
            if replacing_existing:
                if return_code == 0:
                    try:
                        os.replace(output_path, config_path)
                    except OSError as error:
                        messagebox.showerror(self._t("replace_failed"), str(error))
                        return
                elif output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError:
                        pass
            if return_code == 0:
                self._load_config(config_path)

        self._start_command(arguments, on_finish=finish_init)

    def _open_config(self) -> None:
        initial = self.config_var.get().strip()
        chosen = filedialog.askopenfilename(
            title=self._t("select_config_open"), initialdir=str(Path(initial).parent) if initial else None,
            filetypes=((self._t("json_files"), "*.json"), (self._t("all_files"), "*.*")),
        )
        if chosen:
            self._load_config(Path(chosen))

    def _load_config(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(self._t("root_object"))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            messagebox.showerror(self._t("open_failed"), str(error))
            return
        try:
            from spritepost.config import validate_config

            validate_config(data, path.parent)
        except (ValueError, KeyError, TypeError) as error:
            messagebox.showerror(
                self._t("config_validation_title"),
                f"{self._t('config_validation')}\n\n{self._t('technical_detail')}{error}",
            )
            return
        self.config_var.set(str(path.resolve()))
        editor_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        self._set_editor(editor_text)
        self.saved_editor_text = editor_text
        self._sync_common_fields(data, path.parent)
        self._set_status("config_opened", name=path.name)

    def _ensure_common_applied(self) -> bool:
        if not self._form_is_dirty():
            return True
        if not messagebox.askyesno(self._t("apply_dirty_title"), self._t("apply_dirty")):
            return False
        return self._apply_common_to_editor()

    def _save_config(self) -> bool:
        if not self._ensure_common_applied():
            return False
        config = self.config_var.get().strip()
        if not config:
            messagebox.showerror(self._t("missing_config_title"), self._t("missing_config_location"))
            return False
        try:
            data = self._editor_data()
        except ValueError as error:
            messagebox.showerror(self._t("invalid_json_title"), str(error))
            return False
        path = Path(config).expanduser().resolve()
        try:
            from spritepost.config import validate_config

            validate_config(data, path.parent)
        except (ValueError, KeyError, TypeError) as error:
            messagebox.showerror(
                self._t("config_validation_title"),
                f"{self._t('config_validation')}\n\n{self._t('technical_detail')}{error}",
            )
            return False
        try:
            output = self._output_path_from_config(data, path.parent)
        except ValueError as error:
            messagebox.showerror(self._t("invalid_json_title"), str(error))
            return False
        if config_is_inside_output(path, output):
            messagebox.showerror(self._t("output_inside_title"), self._t("output_inside"))
            return False
        raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8", newline="\n")
        except OSError as error:
            messagebox.showerror(self._t("save_failed"), str(error))
            return False
        self.config_var.set(str(path))
        self._set_editor(raw)
        self.saved_editor_text = raw
        self._sync_common_fields(data, path.parent)
        self._set_status("config_saved", name=path.name)
        return True

    def _save_and_run(self) -> None:
        if self._save_config():
            self._run_process(saved=True)

    def _run_process(self, *, saved: bool = False) -> None:
        config = self.config_var.get().strip()
        if not config:
            messagebox.showerror(self._t("missing_config_title"), self._t("missing_config_open"))
            return
        config_path = Path(config).expanduser().resolve()
        if not saved:
            if self._form_is_dirty():
                if not self._save_config():
                    return
            current_text = self.editor.get("1.0", tk.END).rstrip() + "\n"
            if current_text != self.saved_editor_text:
                if not messagebox.askyesno(self._t("unsaved_json_title"), self._t("unsaved_json")):
                    return
                if not self._save_config():
                    return
        if not config_path.is_file():
            messagebox.showerror(self._t("missing_config_title"), self._t("config_not_found"))
            return
        try:
            disk_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            output_path = self._output_path_from_config(disk_config, config_path.parent)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            messagebox.showerror(self._t("invalid_json_title"), str(error))
            return
        if config_is_inside_output(config_path, output_path):
            messagebox.showerror(self._t("output_inside_title"), self._t("output_inside"))
            return
        self.result_var.set(str(output_path))
        self._start_command(["process", str(config_path)])

    def _run_verify(self) -> None:
        result = self.result_var.get().strip()
        if not result:
            messagebox.showerror(self._t("result_missing_title"), self._t("result_missing"))
            return
        result_path = Path(result).expanduser().resolve()
        self.result_var.set(str(result_path))
        arguments = ["verify", str(result_path)]
        aseprite = self.aseprite_var.get().strip()
        if aseprite and aseprite != "auto":
            arguments.extend(("--aseprite", aseprite))
        self._start_command(arguments)

    def _run_doctor(self) -> None:
        self._append_log("\n" + self._t("doctor_intro") + "\n")
        arguments = ["doctor"]
        aseprite = self.aseprite_var.get().strip()
        if aseprite and aseprite != "auto":
            arguments.extend(("--aseprite", aseprite))
        self._start_command(arguments, on_finish=self._doctor_finished)

    def _doctor_finished(self, return_code: int) -> None:
        if return_code != 0:
            self._append_log(self._t("dependency_hint") + "\n")

    def _start_command(self, arguments: list[str], on_finish: object | None = None) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(self._t("task_running_title"), self._t("task_running"))
            return
        if not CLI_PATH.is_file():
            messagebox.showerror(self._t("core_missing_title"), self._t("core_missing", path=CLI_PATH))
            return
        command = [sys.executable, "-u", str(CLI_PATH), "--lang", self.language, *arguments]
        self._append_log(f"\n> {self._display_command(command)}\n")
        self._set_busy(True)
        self._set_status("running")

        def run() -> None:
            try:
                self.process = subprocess.Popen(
                    command, cwd=APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=CREATE_NO_WINDOW,
                )
                assert self.process.stdout is not None
                for line in self.process.stdout:
                    self.events.put(("log", line))
                return_code = self.process.wait()
                self.events.put(("done", (return_code, on_finish)))
            except OSError as error:
                self.events.put(("error", str(error)))
            finally:
                self.process = None

        self.worker = threading.Thread(target=run, name="spritepost-cli", daemon=True)
        self.worker.start()

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "done":
                    return_code, on_finish = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self._set_status("complete" if return_code == 0 else "failed", code=return_code)
                    if callable(on_finish):
                        on_finish(return_code)
                elif event == "error":
                    self._set_busy(False)
                    self._set_status("launch_failed")
                    self._append_log(f"[{self._t('launch_failed')}] {payload}\n{self._t('dependency_hint')}\n")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for button in self.busy_buttons:
            button.configure(state=state)

    def _set_status(self, key: str, **values: object) -> None:
        self._status_key = key
        self._status_values = values
        self._render_status()

    def _render_status(self) -> None:
        self.status_var.set(self._t(self._status_key, **self._status_values))

    def _output_path_from_config(self, data: object, config_dir: Path) -> Path:
        if not isinstance(data, dict):
            raise ValueError(self._t("root_object"))
        output = data.get("output")
        if not isinstance(output, str) or not output.strip():
            raise ValueError(self._t("output_required"))
        path = Path(output).expanduser()
        return (path if path.is_absolute() else config_dir / path).resolve()

    def _set_editor(self, content: str) -> None:
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", content)

    def _append_log(self, content: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, content)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def _open_result_dir(self) -> None:
        result = self.result_var.get().strip()
        if not result:
            messagebox.showerror(self._t("result_missing_title"), self._t("result_missing"))
            return
        path = Path(result)
        if not path.is_dir():
            messagebox.showerror(self._t("directory_missing_title"), self._t("directory_missing", path=path))
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as error:
            messagebox.showerror(self._t("open_directory_failed"), str(error))

    def _open_help(self) -> None:
        candidates = (
            APP_DIR / ("README.zh-CN.md" if self.language == "zh-CN" else "README.md"),
            APP_DIR / ("README_zh-CN.md" if self.language == "zh-CN" else "README.en.md"),
            APP_DIR / "README.md",
        )
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            messagebox.showerror(self._t("help_missing_title"), self._t("help_missing"))
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as error:
            messagebox.showerror(self._t("help_failed"), str(error))

    @staticmethod
    def _display_command(command: list[str]) -> str:
        return subprocess.list2cmdline(command)

    def _on_close(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(self._t("close_running_title"), self._t("close_running")):
                return
            self.process.terminate()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    SpritePostprocessGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
