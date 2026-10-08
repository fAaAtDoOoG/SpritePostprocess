import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spritepost.i18n import TEXT, diagnostic, progress, resolve_language

spec = importlib.util.spec_from_file_location("spritepost_cli", Path(__file__).resolve().parents[1] / "spritepost.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class CliLanguageTests(unittest.TestCase):
    def help(self, args):
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture), self.assertRaises(SystemExit) as raised:
            cli.main(args)
        self.assertEqual(raised.exception.code, 0)
        return capture.getvalue()

    def test_english_and_chinese_help(self):
        self.assertIn("Process a saved config", self.help(["--lang", "en", "--help"]))
        self.assertIn("输出到新目录", self.help(["--lang", "zh-CN", "--help"]))

    def test_language_flag_also_works_after_subcommand(self):
        chinese = self.help(["process", "--lang", "zh-CN", "--help"])
        self.assertIn("已保存的任务配置", chinese)
        self.assertIn("config", chinese)

    def test_environment_language_and_explicit_override(self):
        with patch.dict(os.environ, {"SPRITEPOST_LANG": "zh-CN"}):
            self.assertEqual(resolve_language(), "zh-CN")
            self.assertIn("创建任务配置", self.help(["--help"]))
            self.assertIn("Create an editable", self.help(["--lang", "en", "--help"]))

    def test_catalog_has_both_nonempty_languages_with_equal_placeholders(self):
        import string
        parser = string.Formatter()
        for key, translations in TEXT.items():
            self.assertEqual(len(translations), 2, key)
            self.assertTrue(all(translations), key)
            fields = [{field for _, field, _, _ in parser.parse(t) if field} for t in translations]
            self.assertEqual(*fields, key)

    def test_progress_and_common_error_messages_are_translated(self):
        self.assertEqual(progress("Prepare idle_NE", "zh-CN"), "准备素材：idle_NE")
        self.assertIn("找不到 Aseprite", diagnostic(FileNotFoundError("Aseprite executable not found: /missing"), "zh-CN"))
        self.assertIn("缺少 Python 依赖", diagnostic(ImportError("numpy"), "zh-CN"))

    def test_missing_required_argument_has_chinese_guidance(self):
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture), self.assertRaises(SystemExit) as raised:
            cli.main(["--lang", "zh-CN", "process"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("缺少必需参数：config", capture.getvalue())

    def test_init_localizes_text_but_keeps_machine_config_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            (source / "walk.aseprite").touch()
            config = root / "job.json"
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                code = cli.main(["init", "--input", str(source), "--output", str(config),
                                 "--result-dir", str(root / "result"), "--lang", "zh-CN"])
            self.assertEqual(code, 0)
            self.assertIn("已创建", capture.getvalue())
            value = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(value["animations"][0]["name"], "walk")
            self.assertEqual(value["resample"], "lanczos4")

    def test_init_rejects_config_inside_output_before_creating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.aseprite"
            source.touch()
            result = root / "result"
            with contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(["init", "--input", str(source), "--output", str(result / "job.json"),
                                 "--result-dir", str(result), "--lang", "en"])
            self.assertEqual(code, 1)
            self.assertFalse(result.exists())


if __name__ == "__main__":
    unittest.main()
