from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from spritepost.unity import check_unity, deploy_png


def sprite(index=0, x=0, y=0, width=8, height=8, pivot="{x: 0.5, y: 0.5}"):
    return f"""    - name: Frame_{index}
      rect:
        serializedVersion: 2
        x: {x}
        y: {y}
        width: {width}
        height: {height}
      pivot: {pivot}
      spriteID: id{index}
      internalID: {index + 10}
"""


def png_meta(records=None):
    return """fileFormatVersion: 2
guid: existing-guid
TextureImporter:
  mipmaps:
    enableMipMap: 0
  textureSettings:
    filterMode: 0
  nPOTScale: 0
  spriteMode: 2
  spriteMeshType: 0
  spritePixelsToUnits: 32
  platformSettings:
  - buildTarget: DefaultTexturePlatform
    maxTextureSize: 8192
    textureCompression: 0
    overridden: 0
  - buildTarget: Standalone
    maxTextureSize: 2048
    textureCompression: 1
    overridden: 0
  spriteSheet:
    sprites:
""" + (records if records is not None else sprite() + sprite(1, 8)) + "    outline: []\n"


class UnityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.assets = self.root / "project" / "Assets"
        self.assets.mkdir(parents=True)
        self.destination = self.assets / "walk.png"
        self.meta = self.destination.with_name("walk.png.meta")
        self.source = self.root / "new.png"
        self.backup = self.root / "backups"
        Image.new("RGBA", (16, 8), (10, 20, 30, 255)).save(self.source)
        Image.new("RGBA", (16, 8), (30, 20, 10, 255)).save(self.destination)
        self.meta.write_text(png_meta(), encoding="utf-8")
        self.manifest = {"size": [8, 8], "frames": [
            {"rect": {"x": 0, "y": 0, "w": 8, "h": 8}, "duration_ms": 62},
            {"rect": {"x": 8, "y": 0, "w": 8, "h": 8}, "duration_ms": 63},
        ]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_checker_is_static_and_ignores_inactive_platform(self):
        report = check_unity(self.assets, {"size": [8, 8], "pixels_per_unit": 32})
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["evidence"], "static_meta")
        self.assertEqual(report["files"][0]["frame_count"], 2)
        self.assertTrue(report["warnings"])

    def test_active_compression_and_size_limit_fail(self):
        text = png_meta().replace("maxTextureSize: 2048", "maxTextureSize: 8")
        text = text.replace("textureCompression: 1\n    overridden: 0", "textureCompression: 1\n    overridden: 1")
        self.meta.write_text(text)
        report = check_unity(self.assets)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("textureCompression" in error for error in report["errors"]))
        self.assertTrue(any("downscale" in error for error in report["errors"]))

    def test_checker_detects_geometry_pivot_duplicate_ids(self):
        self.meta.write_text(png_meta(sprite() + sprite(0, 4, width=7, pivot="{x: 0, y: 0}")))
        report = check_unity(self.assets)
        errors = " ".join(report["errors"])
        for expected in ("overlap", "inconsistent", "Duplicate", "pivots"):
            self.assertIn(expected, errors)

    def test_checker_uses_active_aseprite_section(self):
        self.meta.unlink()
        path = self.assets / "walk.aseprite"
        header = bytearray(128)
        struct.pack_into("<IHHHH", header, 0, 128, 0xA5E0, 2, 8, 8)
        path.write_bytes(header)
        text = """ScriptedImporter:
  textureImporterSettings:
    enableMipMap: 0
    filterMode: 0
    spriteMode: 2
    spriteMeshType: 0
  previousAsepriteImporterSettings:
    fileImportMode: 1
  asepriteImporterSettings:
    fileImportMode: 0
  animatedSpriteImportData:
""" + sprite(width=3, height=4) + "  spriteSheetImportData:\n" + sprite() + sprite(1, 8)
        path.with_name(path.name + ".meta").write_text(text)
        report = check_unity(self.assets)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["files"][0]["frame_count"], 2)

    def test_checker_reports_unsupported_without_false_runtime_claim(self):
        self.meta.write_text("TextureImporter:\n  strangeSprites: []\n")
        report = check_unity(self.assets)
        self.assertEqual(report["files"][0]["frame_count"], 0)
        self.assertGreater(len(report["warnings"]), 2)
        self.assertEqual(report["evidence"], "static_meta")

    def test_aseprite_can_share_packed_rect_for_identical_frames(self):
        self.meta.unlink()
        path = self.assets / "walk.aseprite.meta"
        path.write_text("ScriptedImporter:\n  asepriteImporterSettings:\n    fileImportMode: 0\n"
                        "  spriteSheetImportData:\n" + sprite() + sprite(1))
        report = check_unity(self.assets)
        self.assertEqual(report["status"], "passed", report)

    def test_deploy_preserves_metadata_and_backups(self):
        original = self.destination.read_bytes()
        original_meta = self.meta.read_bytes()
        result = deploy_png(self.source, self.destination, self.manifest, self.backup)
        self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.meta.read_bytes(), original_meta)
        self.assertEqual((Path(result["backup"]) / "walk.png").read_bytes(), original)
        self.assertEqual((Path(result["backup"]) / "walk.png.meta").read_bytes(), original_meta)
        self.assertTrue(result["metadata_preserved"])

    def test_deploy_rejects_layout_change_before_write(self):
        original = self.destination.read_bytes()
        self.manifest["frames"].reverse()
        with self.assertRaisesRegex(ValueError, "order/layout"):
            deploy_png(self.source, self.destination, self.manifest, self.backup)
        self.assertEqual(original, self.destination.read_bytes())
        self.assertFalse(self.backup.exists())

    def test_deploy_rejects_missing_meta_and_unsafe_paths(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            deploy_png(self.source, self.destination, self.manifest, self.assets / "backup")
        with self.assertRaisesRegex(ValueError, "different"):
            deploy_png(self.source, self.source, self.manifest, self.backup)
        self.meta.unlink()
        with self.assertRaisesRegex(ValueError, "no .meta"):
            deploy_png(self.source, self.destination, self.manifest, self.backup)

    def test_deploy_new_target_does_not_create_meta(self):
        new = self.root / "other-project" / "Assets" / "walk.png"
        result = deploy_png(self.source, new, self.manifest, self.backup)
        self.assertFalse(new.with_name("walk.png.meta").exists())
        self.assertFalse(result["metadata_preserved"])
        self.assertTrue(result["requires_unity_import"])

    def test_deploy_restores_png_if_post_write_validation_fails(self):
        from spritepost import unity
        original = self.destination.read_bytes()
        actual_replace = unity._replace_file

        def corrupt_once(source, destination):
            if source == self.source:
                destination.write_bytes(b"broken")
            else:
                actual_replace(source, destination)

        with mock.patch("spritepost.unity._replace_file", side_effect=corrupt_once):
            with self.assertRaises(OSError):
                deploy_png(self.source, self.destination, self.manifest, self.backup)
        self.assertEqual(self.destination.read_bytes(), original)

    def test_manifest_top_left_rects_match_unity_bottom_left(self):
        Image.new("RGBA", (8, 16)).save(self.source)
        Image.new("RGBA", (8, 16)).save(self.destination)
        self.meta.write_text(png_meta(sprite(0, 0, 8) + sprite(1, 0, 0)))
        self.manifest["frames"][1]["rect"] = {"x": 0, "y": 8, "w": 8, "h": 8}
        result = deploy_png(self.source, self.destination, self.manifest, self.backup)
        self.assertEqual(result["status"], "deployed")


if __name__ == "__main__":
    unittest.main()
