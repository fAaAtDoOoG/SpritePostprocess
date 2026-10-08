from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui_config import (  # noqa: E402
    common_from_config,
    config_is_inside_output,
    load_language_preference,
    localized_validation_error,
    merge_common,
    parse_size,
    parse_sizes,
    save_language_preference,
    suggested_paths,
)
from ui_strings import OPTION_KEYS, STRINGS, detect_language, option_labels  # noqa: E402


class TranslationTests(unittest.TestCase):
    def test_catalogs_have_exact_key_parity(self) -> None:
        baseline = set(STRINGS["en"])
        self.assertEqual(baseline, set(STRINGS["zh-CN"]))
        self.assertTrue(all(STRINGS[language][key].strip() for language in STRINGS for key in baseline))

    def test_localized_options_preserve_machine_tokens(self) -> None:
        for group, tokens in OPTION_KEYS.items():
            for language in STRINGS:
                self.assertEqual(set(tokens), set(option_labels(language, group)))
        self.assertNotEqual(option_labels("en", "layout")["shared_fit"], option_labels("zh-CN", "layout")["shared_fit"])

    def test_locale_detection(self) -> None:
        self.assertEqual(detect_language("zh_CN"), "zh-CN")
        self.assertEqual(detect_language("zh-TW"), "zh-CN")
        self.assertEqual(detect_language("en_US"), "en")


class CommonConfigTests(unittest.TestCase):
    def test_size_parser_supports_rectangles_and_multiplication_sign(self) -> None:
        self.assertEqual(parse_size("768×512"), [768, 512])
        self.assertEqual(parse_sizes("512x512, 96×64, 32X48"), [[512, 512], [96, 64], [32, 48]])
        with self.assertRaisesRegex(ValueError, "duplicates"):
            parse_sizes("64x64, 64×64")

    def test_known_form_error_has_chinese_guidance_and_technical_detail(self) -> None:
        try:
            parse_size("not-a-size")
        except ValueError as error:
            message = localized_validation_error(error, "zh-CN")
        else:
            self.fail("invalid size did not raise")
        self.assertIn("宽×高", message)
        self.assertIn("技术细节", message)

    def test_common_merge_preserves_advanced_and_unknown_nested_fields(self) -> None:
        original = {
            "version": 1,
            "name": "hero",
            "output": "old",
            "aseprite": "auto",
            "work_size": [512, 512],
            "sizes": [[64, 64]],
            "cleanup": {"profile": "off", "edge_width": 9},
            "layout": {"mode": "preserve", "occupancy": 0.5, "anchor": [0.4, 0.9]},
            "export": {"aseprite": True, "png_frames": False, "previews": True, "zip": True, "preview_scale": 7},
            "animations": [
                {"name": "run.E", "source": "run.aseprite", "frame_map": [3, 1], "matching": {"allow_mirror": False}},
                {"name": "run.W", "mirror_of": "run.E"},
            ],
        }
        values = {
            "output": "new-output",
            "aseprite": "D:/Apps/Aseprite.exe",
            "work_size": "768×512",
            "sizes": "192×128, 96×64",
            "cleanup": "strict",
            "layout": "shared_fit",
            "occupancy_percent": "88",
            "preview_frames": "32",
            "export_aseprite": False,
            "export_png_frames": True,
            "export_previews": False,
            "export_zip": True,
        }
        merged = merge_common(original, values)
        self.assertEqual(merged["animations"], original["animations"])
        self.assertEqual(merged["cleanup"]["edge_width"], 9)
        self.assertEqual(merged["layout"]["anchor"], [0.4, 0.9])
        self.assertEqual(merged["export"]["preview_scale"], 7)
        self.assertEqual(merged["work_size"], [768, 512])
        self.assertEqual(merged["sizes"], [[192, 128], [96, 64]])
        self.assertEqual(merged["layout"]["occupancy"], 0.88)
        self.assertEqual(original["output"], "old", "merge must not mutate the JSON being edited")

    def test_extract_and_merge_roundtrip_common_fields(self) -> None:
        config = {
            "output": "delivery",
            "aseprite": "auto",
            "work_size": [256, 512],
            "sizes": [[64, 128], [32, 64]],
            "cleanup": {"profile": "conservative"},
            "layout": {"mode": "shared_fit", "occupancy": 0.875},
            "export": {"aseprite": True, "png_frames": True, "previews": False, "zip": False, "preview_frames": 24},
            "animations": [{"name": "idle", "source": "idle.aseprite"}],
        }
        values = common_from_config(config)
        merged = merge_common(config, values)
        self.assertEqual(merged, config)

    def test_suggested_config_is_sibling_not_inside_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "Hero"
            source.mkdir()
            output, config = suggested_paths(source)
            self.assertEqual(output.parent, config.parent)
            self.assertFalse(config_is_inside_output(config, output))
            self.assertTrue(config_is_inside_output(output / "job.json", output))


class PreferenceTests(unittest.TestCase):
    def test_preferences_persist_language_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".ui-preferences.json"
            save_language_preference(path, "zh-CN")
            self.assertEqual(load_language_preference(path), "zh-CN")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"language": "zh-CN"})


class GuiSmokeTests(unittest.TestCase):
    def test_language_switch_retains_form_and_unsaved_json(self) -> None:
        try:
            import tkinter as tk
            from gui import SpritePostprocessGui
        except ImportError as error:
            self.skipTest(f"Tkinter unavailable: {error}")
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        root.withdraw()
        try:
            app = SpritePostprocessGui(root)
            app.result_var.set("D:/jobs/new-output")
            app.work_size_var.set("700×500")
            app.editor.insert("1.0", '{"custom": "unsaved"}')
            before = app.editor.get("1.0", tk.END)
            app._set_language("zh-CN", persist=False)
            self.assertEqual(app.result_var.get(), "D:/jobs/new-output")
            self.assertEqual(app.work_size_var.get(), "700×500")
            self.assertEqual(app.editor.get("1.0", tk.END), before)
            self.assertEqual(app.option_tokens["cleanup"], "strict")
            app._set_language("en", persist=False)
            self.assertEqual(app.editor.get("1.0", tk.END), before)
        finally:
            root.destroy()

    def test_common_apply_merges_current_unsaved_advanced_json(self) -> None:
        try:
            import tkinter as tk
            from gui import SpritePostprocessGui
        except ImportError as error:
            self.skipTest(f"Tkinter unavailable: {error}")
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        root.withdraw()
        try:
            app = SpritePostprocessGui(root)
            original = {
                "output": "old",
                "work_size": [512, 512],
                "sizes": [[64, 64]],
                "animations": [{"name": "walk.E", "source": "walk.aseprite", "frame_map": [2, 0]}],
            }
            app._set_editor(json.dumps(original))
            app.result_var.set("new")
            app.form_snapshot = {"different": True}
            self.assertTrue(app._apply_common_to_editor())
            merged = json.loads(app.editor.get("1.0", tk.END))
            self.assertEqual(merged["output"], "new")
            self.assertEqual(merged["animations"], original["animations"])
        finally:
            root.destroy()

    def test_invalid_loaded_profile_keeps_existing_editor(self) -> None:
        try:
            import tkinter as tk
            from gui import SpritePostprocessGui
        except ImportError as error:
            self.skipTest(f"Tkinter unavailable: {error}")
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        root.withdraw()
        try:
            app = SpritePostprocessGui(root)
            existing = '{"current": "unsaved"}\n'
            app._set_editor(existing)
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "invalid.json"
                invalid = {
                    "version": 1,
                    "name": "invalid",
                    "output": "delivery",
                    "cleanup": {"profile": "destructive"},
                    "animations": [{"name": "idle", "source": "idle.png"}],
                }
                path.write_text(json.dumps(invalid), encoding="utf-8")
                with mock.patch("gui.messagebox.showerror") as showerror:
                    app._load_config(path)
                showerror.assert_called_once()
            self.assertEqual(app.editor.get("1.0", tk.END), existing + "\n")
            self.assertEqual(app.config_var.get(), "")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
