import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class CliPipelineTests(unittest.TestCase):
    def test_both_languages_produce_identical_frames_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "frames"
            source.mkdir()
            for i in range(2):
                pixels = np.zeros((48, 32, 4), dtype=np.uint8)
                pixels[8:40, 6+i:23+i] = [140, 65, 40, 255]
                Image.fromarray(pixels).save(source / f"{i:04d}.png")
            manifests, pixels = [], []
            for language in ("en", "zh-CN"):
                output = temporary / language
                config = temporary / f"{language}.json"
                config.write_text(json.dumps({
                    "name": "test_character", "output": str(output),
                    "work_size": [64, 96], "sizes": [[32, 48]],
                    "cleanup": {"profile": "off"}, "layout": {"mode": "preserve"},
                    "export": {"aseprite": False, "previews": False, "zip": False},
                    "animations": [
                        {"name": "idle_E", "source": {"path": str(source), "type": "sequence", "durations_ms": [62, 63]}},
                        {"name": "idle_W", "mirror_of": "idle_E"},
                    ],
                }), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(ROOT / "spritepost.py"), "process", str(config), "--lang", language],
                    capture_output=True, text=True, encoding="utf-8", timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("处理完成" if language == "zh-CN" else "Completed", result.stdout)
                self.assertEqual(json.loads((output / "verification.json").read_text())["status"], "passed")
                manifests.append(json.loads((output / "32x48px/sheets/idle_E.json").read_text()))
                pixels.append(np.asarray(Image.open(output / "32x48px/sheets/idle_E.png")))
            self.assertEqual(manifests[0], manifests[1])
            self.assertTrue(np.array_equal(pixels[0], pixels[1]))


if __name__ == "__main__":
    unittest.main()
