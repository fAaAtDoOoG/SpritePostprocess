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


APP_DIR = Path(__file__).resolve().parent
CLI_PATH = APP_DIR / "spritepost.py"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class SpritePostprocessGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Sprite 动画后处理")
        self.root.geometry("1120x820")
        self.root.minsize(880, 640)

        self.input_var = tk.StringVar()
        self.result_var = tk.StringVar()
        self.config_var = tk.StringVar()
        self.aseprite_var = tk.StringVar(value=os.environ.get("SPRITEPOST_ASEPRITE", ""))
        self.preset_var = tk.StringVar(value="pixel-character")
        self.status_var = tk.StringVar(value="就绪")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.busy_buttons: list[ttk.Button] = []
        self.saved_editor_text = ""

        self._build_ui()
        self.root.after(80, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(6, weight=1)

        self._path_row(outer, 0, "素材目录（创建配置）", self.input_var, self._choose_input)
        self._path_row(outer, 1, "结果目录（创建/验证）", self.result_var, self._choose_result)
        self._path_row(outer, 2, "配置文件", self.config_var, self._choose_config_path)
        self._path_row(outer, 3, "Aseprite（创建/验证）", self.aseprite_var, self._choose_aseprite)

        ttk.Label(outer, text="预设").grid(row=4, column=0, sticky=tk.W, pady=(6, 8))
        preset = ttk.Combobox(
            outer,
            textvariable=self.preset_var,
            values=("pixel-character", "neutral"),
            state="readonly",
            width=24,
        )
        preset.grid(row=4, column=1, sticky=tk.W, pady=(6, 8))

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(0, 10))
        for column in range(7):
            actions.columnconfigure(column, weight=1)

        self._action_button(actions, 0, "创建配置", self._init_config)
        self._action_button(actions, 1, "打开配置", self._open_config)
        self._action_button(actions, 2, "保存配置", self._save_config)
        self._action_button(actions, 3, "开始处理", self._run_process)
        self._action_button(actions, 4, "验证结果", self._run_verify)
        ttk.Button(actions, text="打开结果目录", command=self._open_result_dir).grid(
            row=0, column=5, padx=3, sticky=tk.EW
        )
        ttk.Button(actions, text="清空日志", command=self._clear_log).grid(
            row=0, column=6, padx=(3, 0), sticky=tk.EW
        )

        panes = ttk.Panedwindow(outer, orient=tk.VERTICAL)
        panes.grid(row=6, column=0, columnspan=3, sticky=tk.NSEW)

        editor_frame = ttk.Labelframe(
            panes, text="完整 JSON 配置（处理时以这里保存的内容为准）", padding=6
        )
        log_frame = ttk.Labelframe(panes, text="运行日志", padding=6)
        panes.add(editor_frame, weight=3)
        panes.add(log_frame, weight=2)

        self.editor = self._scrolled_text(editor_frame, wrap=tk.NONE)
        self.log = self._scrolled_text(log_frame, wrap=tk.WORD, readonly=True)

        status = ttk.Frame(outer)
        status.grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))
        ttk.Label(status, text="状态：").pack(side=tk.LEFT)
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT)

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: object,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky=tk.EW, padx=(10, 6), pady=3
        )
        ttk.Button(parent, text="浏览…", command=command).grid(row=row, column=2, pady=3)

    def _action_button(
        self, parent: ttk.Frame, column: int, text: str, command: object
    ) -> None:
        button = ttk.Button(parent, text=text, command=command)
        button.grid(row=0, column=column, padx=(0 if column == 0 else 3, 3), sticky=tk.EW)
        self.busy_buttons.append(button)

    @staticmethod
    def _scrolled_text(
        parent: ttk.Labelframe, *, wrap: str, readonly: bool = False
    ) -> tk.Text:
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(container, wrap=wrap, undo=not readonly, font=("Consolas", 10))
        y_scroll = ttk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
        x_scroll = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        text.grid(row=0, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=0, column=1, sticky=tk.NS)
        x_scroll.grid(row=1, column=0, sticky=tk.EW)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        if readonly:
            text.configure(state=tk.DISABLED)
        return text

    def _choose_input(self) -> None:
        chosen = filedialog.askdirectory(title="选择包含动画素材的目录")
        if chosen:
            self.input_var.set(chosen)

    def _choose_result(self) -> None:
        chosen = filedialog.askdirectory(title="选择结果输出目录", mustexist=False)
        if not chosen:
            return
        self.result_var.set(chosen)
        if not self.config_var.get().strip():
            result_path = Path(chosen)
            self.config_var.set(
                str(result_path.with_name(result_path.name + ".spritepost.json"))
            )

    def _choose_config_path(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="选择配置文件位置",
            defaultextension=".json",
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if chosen:
            self.config_var.set(chosen)

    def _choose_aseprite(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择 Aseprite 可执行文件",
            filetypes=(("可执行文件", "*.exe"), ("所有文件", "*.*")),
        )
        if chosen:
            self.aseprite_var.set(chosen)

    def _init_config(self) -> None:
        source = self.input_var.get().strip()
        result = self.result_var.get().strip()
        config = self.config_var.get().strip()
        if not source or not result:
            messagebox.showerror("缺少路径", "请先选择素材目录和结果目录。")
            return
        if not config:
            result_path = Path(result)
            config = str(result_path.with_name(result_path.name + ".spritepost.json"))
        source = str(Path(source).expanduser().resolve())
        result = str(Path(result).expanduser().resolve())
        config_path = Path(config).expanduser().resolve()
        self.input_var.set(source)
        self.result_var.set(result)
        self.config_var.set(str(config_path))
        output_path = config_path
        replacing_existing = config_path.exists()
        if replacing_existing:
            if not messagebox.askyesno(
                "确认覆盖", f"配置文件已经存在：\n{config_path}\n\n是否覆盖？"
            ):
                return
            output_path = config_path.with_name(
                f".{config_path.name}.{uuid.uuid4().hex}.tmp.json"
            )

        arguments = [
            "init",
            "--input",
            source,
            "--output",
            str(output_path),
            "--result-dir",
            result,
            "--preset",
            self.preset_var.get(),
        ]
        aseprite = self.aseprite_var.get().strip()
        if aseprite:
            arguments.extend(("--aseprite", aseprite))

        def finish_init(return_code: int) -> None:
            if replacing_existing:
                if return_code == 0:
                    try:
                        os.replace(output_path, config_path)
                    except OSError as error:
                        messagebox.showerror("替换配置失败", str(error))
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
            title="打开动画后处理配置",
            initialdir=str(Path(initial).parent) if initial else None,
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if chosen:
            self._load_config(Path(chosen))

    def _load_config(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as error:
            messagebox.showerror("无法打开配置", str(error))
            return
        self.config_var.set(str(path))
        editor_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        self._set_editor(editor_text)
        self.saved_editor_text = editor_text
        self._sync_fields_from_config(data, path.parent)
        self.status_var.set(f"已打开配置：{path.name}")

    def _sync_fields_from_config(self, data: object, config_dir: Path) -> None:
        if not isinstance(data, dict):
            return

        def first_string(*keys: str) -> str | None:
            for key in keys:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return None

        source = first_string("input", "input_dir", "source_dir")
        result = first_string("output", "result_dir", "output_dir")
        aseprite = first_string("aseprite", "aseprite_path")
        preset = first_string("preset")
        if source:
            self.input_var.set(source)
        if result:
            result_path = Path(result).expanduser()
            if not result_path.is_absolute():
                result_path = config_dir / result_path
            self.result_var.set(str(result_path.resolve()))
        if aseprite and aseprite != "auto":
            aseprite_path = Path(aseprite).expanduser()
            if not aseprite_path.is_absolute():
                aseprite_path = config_dir / aseprite_path
            self.aseprite_var.set(str(aseprite_path.resolve()))
        if preset in {"neutral", "pixel-character"}:
            self.preset_var.set(preset)

    def _save_config(self) -> bool:
        config = self.config_var.get().strip()
        if not config:
            messagebox.showerror("缺少配置文件", "请先选择配置文件位置。")
            return False
        raw = self.editor.get("1.0", tk.END).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            messagebox.showerror(
                "JSON 格式错误",
                f"第 {error.lineno} 行，第 {error.colno} 列：{error.msg}",
            )
            return False
        path = Path(config).expanduser().resolve()
        self.config_var.set(str(path))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw + "\n", encoding="utf-8", newline="\n")
        except OSError as error:
            messagebox.showerror("保存失败", str(error))
            return False
        self.saved_editor_text = raw + "\n"
        self._sync_fields_from_config(data, path.parent)
        self.status_var.set(f"配置已保存：{path.name}")
        return True

    def _run_process(self) -> None:
        config = self.config_var.get().strip()
        if not config:
            messagebox.showerror("缺少配置文件", "请先创建或打开配置文件。")
            return
        config = str(Path(config).expanduser().resolve())
        self.config_var.set(config)
        if not Path(config).is_file():
            messagebox.showerror("配置不存在", "请先创建配置文件。")
            return
        current_text = self.editor.get("1.0", tk.END).rstrip() + "\n"
        if current_text != self.saved_editor_text:
            choice = messagebox.askyesnocancel(
                "配置尚未保存",
                "JSON 编辑区包含未保存的修改。\n\n"
                "选择“是”保存后处理；选择“否”使用磁盘上的配置。",
            )
            if choice is None:
                return
            if choice and not self._save_config():
                return
        else:
            try:
                json.loads(current_text)
            except json.JSONDecodeError as error:
                messagebox.showerror(
                    "JSON 格式错误",
                    f"第 {error.lineno} 行，第 {error.colno} 列：{error.msg}",
                )
                return
        if not Path(config).is_file():
            return
        try:
            disk_config = json.loads(Path(config).read_text(encoding="utf-8-sig"))
            output_path = self._output_path_from_config(disk_config, Path(config).parent)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            messagebox.showerror("配置无效", str(error))
            return
        config_path = Path(config).resolve()
        if config_path == output_path or config_path.is_relative_to(output_path):
            messagebox.showerror(
                "配置位置无效",
                "配置文件不能放在结果目录内。处理会创建一个全新的结果目录；"
                "请把配置移到结果目录旁边。",
            )
            return
        self.result_var.set(str(output_path))
        self._start_command(["process", config])

    def _run_verify(self) -> None:
        result = self.result_var.get().strip()
        if not result:
            messagebox.showerror("缺少结果目录", "请先选择结果目录。")
            return
        result = str(Path(result).expanduser().resolve())
        self.result_var.set(result)
        arguments = ["verify", result]
        aseprite = self.aseprite_var.get().strip()
        if aseprite:
            arguments.extend(("--aseprite", aseprite))
        self._start_command(arguments)

    def _start_command(
        self, arguments: list[str], on_finish: object | None = None
    ) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("任务正在运行", "请等待当前任务结束。")
            return
        if not CLI_PATH.is_file():
            messagebox.showerror("缺少核心工具", f"找不到：\n{CLI_PATH}")
            return

        command = [sys.executable, "-u", str(CLI_PATH), *arguments]
        self._append_log(f"\n> {self._display_command(command)}\n")
        self._set_busy(True)
        self.status_var.set("运行中…")

        def run() -> None:
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=APP_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
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
                    if return_code == 0:
                        self.status_var.set("完成")
                    else:
                        self.status_var.set(f"失败（退出码 {return_code}）")
                    if callable(on_finish):
                        on_finish(return_code)
                elif event == "error":
                    self._set_busy(False)
                    self.status_var.set("启动失败")
                    self._append_log(f"[启动失败] {payload}\n")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for button in self.busy_buttons:
            button.configure(state=state)

    @staticmethod
    def _output_path_from_config(data: object, config_dir: Path) -> Path:
        if not isinstance(data, dict):
            raise ValueError("配置根节点必须是 JSON 对象。")
        output = data.get("output")
        if not isinstance(output, str) or not output.strip():
            raise ValueError('配置必须包含非空的 "output" 路径。')
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = config_dir / path
        return path.resolve()

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
            messagebox.showerror("缺少结果目录", "请先选择结果目录。")
            return
        path = Path(result)
        if not path.is_dir():
            messagebox.showerror("目录不存在", f"结果目录尚不存在：\n{path}")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as error:
            messagebox.showerror("无法打开目录", str(error))

    @staticmethod
    def _display_command(command: list[str]) -> str:
        return subprocess.list2cmdline(command)

    def _on_close(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("任务仍在运行", "关闭窗口会终止当前任务。是否继续？"):
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
