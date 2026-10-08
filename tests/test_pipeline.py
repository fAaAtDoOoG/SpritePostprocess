from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from spritepost.imaging import sequence_indices
from spritepost.media import (create_aseprite, export_aseprite, find_aseprite,
                              save_previews, save_sheet)
from spritepost.pipeline import process, verify


def frame(width, height, rect, color):
    result = np.zeros((height, width, 4), dtype=np.uint8)
    x0, y0, x1, y1 = rect
    result[y0:y1, x0:x1] = color
    return result


def save_sequence(path: Path, frames):
    path.mkdir(parents=True)
    for index, value in enumerate(frames):
        Image.fromarray(value).save(path / f"{index:04d}.png")


def read_manifest(output: Path, size: str, name: str):
    return json.loads((output / size / "sheets" / f"{name}.json").read_text(encoding="utf-8"))


def read_sheet_frames(output: Path, size: str, name: str):
    manifest = read_manifest(output, size, name)
    sheet = np.asarray(Image.open(output / size / "sheets" / f"{name}.png").convert("RGBA"))
    result = []
    for record in manifest["frames"]:
        rect = record["rect"]
        result.append(sheet[rect["y"]:rect["y"] + rect["h"], rect["x"]:rect["x"] + rect["w"]].copy())
    return result


class PipelineTests(unittest.TestCase):
    def test_48_frame_apng_preview_repeats_exact_source_durations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = [
                frame(9, 5, (1, 1, 4, 5), (170, 40, 20, 255)),
                frame(9, 5, (2, 0, 7, 4), (20, 160, 70, 255)),
                frame(9, 5, (0, 2, 8, 5), (40, 60, 190, 255)),
            ]
            durations = [31, 47, 83]

            result = save_previews(frames, durations, root / "preview_48f", "idle.N", scale=2, count=48)

            self.assertEqual(result["frames"], 48)
            actual = []
            with Image.open(result["apng"]) as image:
                self.assertEqual(image.n_frames, 48)
                for index in range(image.n_frames):
                    image.seek(index)
                    actual.append(round(image.info["duration"]))
            self.assertEqual(actual, [durations[index % 3] for index in range(48)])

    def test_png_only_end_to_end_preserves_timing_and_mirror_exactness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            frames = [
                frame(8, 4, (1, 1, 4, 4), (170, 40, 20, 255)),
                frame(8, 4, (2, 0, 7, 3), (20, 160, 70, 255)),
                frame(8, 4, (0, 2, 6, 4), (40, 60, 190, 255)),
            ]
            save_sequence(source, frames)
            output = root / "delivery"
            config_path = root / "job.json"
            config = {
                "version": 1,
                "name": "rectangular",
                "output": str(output),
                "work_size": [20, 12],
                "sizes": [[20, 12], [10, 6]],
                "cleanup": {"profile": "off"},
                "layout": {"mode": "preserve"},
                "export": {
                    "aseprite": False,
                    "png_frames": True,
                    "previews": False,
                    "preview_sizes": [[10, 6]],
                    "preview_scale": 1,
                    "preview_frames": 48,
                    "zip": False,
                },
                "animations": [
                    {
                        "name": "walk.E",
                        "source": {
                            "path": str(source),
                            "type": "sequence",
                            "durations_ms": [40, 70, 110],
                        },
                    },
                    {"name": "walk.W", "mirror_of": "walk.E"},
                ],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = process(config_path, log=lambda _: None)
            verification = verify(output)

            self.assertEqual(report["status"], "complete")
            self.assertEqual(verification["status"], "passed")
            self.assertEqual(report["animations"]["walk.E"]["durations_ms"], [40, 70, 110])
            self.assertEqual(report["animations"]["walk.W"]["durations_ms"], [40, 70, 110])
            for size_name, expected_size in (("20x12px", [20, 12]), ("10x6px", [10, 6])):
                east = read_sheet_frames(output, size_name, "walk.E")
                west = read_sheet_frames(output, size_name, "walk.W")
                manifest = read_manifest(output, size_name, "walk.E")
                self.assertEqual(manifest["size"], expected_size)
                self.assertEqual([f["duration_ms"] for f in manifest["frames"]], [40, 70, 110])
                self.assertTrue(all(np.array_equal(a, b[:, ::-1]) for a, b in zip(west, east)))

    def test_reverse_and_repeat_end_sequence_preserve_mapped_durations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            frames = [frame(12, 12, (i + 1, 2, i + 3, 10), (30 + i * 20, 50, 80, 255)) for i in range(8)]
            save_sequence(source, frames)
            durations = [31, 37, 41, 43, 47, 53, 59, 61]
            output = root / "delivery"
            config_path = root / "job.json"
            config = {
                "name": "sequence-test",
                "output": str(output),
                "work_size": [12, 12],
                "sizes": [[12, 12]],
                "resample": "nearest",
                "cleanup": {"profile": "off"},
                "layout": {"mode": "preserve"},
                "export": {
                    "aseprite": False,
                    "png_frames": False,
                    "previews": False,
                    "preview_sizes": [[12, 12]],
                    "preview_scale": 1,
                    "preview_frames": 16,
                    "zip": False,
                },
                "animations": [{
                    "name": "turn",
                    "source": {"path": str(source), "type": "sequence", "durations_ms": durations},
                    "reverse": True,
                    "pingpong": "repeat_ends",
                }],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = process(config_path, log=lambda _: None)

            reverse = list(reversed(durations))
            expected = reverse + list(reversed(reverse))
            self.assertEqual(len(report["animations"]["turn"]["durations_ms"]), 16)
            self.assertEqual(report["animations"]["turn"]["durations_ms"], expected)
            manifest = read_manifest(output, "12px", "turn")
            self.assertEqual([item["duration_ms"] for item in manifest["frames"]], expected)
            lineage = report["animations"]["turn"]["lineage"]
            self.assertEqual([item["source_index"] for item in lineage], [7, 6, 5, 4, 3, 2, 1, 0, 0, 1, 2, 3, 4, 5, 6, 7])

    def test_explicit_frame_map_uses_edited_timing_but_original_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            edited = root / "edited"
            source_frames = [
                frame(10, 8, (1, 1, 4, 7), (180, 30, 20, 255)),
                frame(10, 8, (3, 1, 7, 7), (20, 170, 50, 255)),
                frame(10, 8, (5, 1, 9, 7), (30, 60, 190, 255)),
            ]
            # Edited pixels intentionally differ. They provide the accepted timeline only;
            # the delivered art must come from the mapped high-resolution source frames.
            edited_frames = [
                frame(10, 8, (0, 0, 2, 2), (250, 220, 20, 255)),
                frame(10, 8, (8, 6, 10, 8), (250, 220, 20, 255)),
            ]
            save_sequence(source, source_frames)
            save_sequence(edited, edited_frames)
            output = root / "delivery"
            config_path = root / "job.json"
            config = {
                "name": "edited-timeline",
                "output": str(output),
                "work_size": [10, 8],
                "sizes": [[10, 8]],
                "resample": "nearest",
                "cleanup": {"profile": "off"},
                "layout": {"mode": "preserve"},
                "export": {
                    "aseprite": False,
                    "png_frames": False,
                    "previews": False,
                    "preview_sizes": [[10, 8]],
                    "preview_scale": 1,
                    "preview_frames": 48,
                    "zip": False,
                },
                "animations": [{
                    "name": "walk.custom",
                    "source": {"path": str(source), "type": "sequence", "durations_ms": [40, 50, 60]},
                    "edited": {"path": str(edited), "type": "sequence", "durations_ms": [117, 233]},
                    "frame_map": [2, 0],
                }],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = process(config_path, log=lambda _: None)
            delivered = read_sheet_frames(output, "10x8px", "walk.custom")

            self.assertEqual(report["animations"]["walk.custom"]["durations_ms"], [117, 233])
            self.assertEqual([item["source_index"] for item in report["animations"]["walk.custom"]["lineage"]], [2, 0])
            self.assertTrue(np.array_equal(delivered[0], source_frames[2]))
            self.assertTrue(np.array_equal(delivered[1], source_frames[0]))
            self.assertFalse(any(np.array_equal(item, edit) for item in delivered for edit in edited_frames))

    def test_resolution_report_compares_corresponding_canvas_axes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            # The shortest side equals the work canvas shortest side, but height
            # still requires a 2x upscale. A min-dimension comparison would lie.
            save_sequence(source, [frame(512, 256, (100, 40, 410, 220), (100, 50, 20, 255))])
            output = root / "delivery"
            config_path = root / "job.json"
            config = {
                "name": "resolution-truth",
                "output": str(output),
                "work_size": [256, 512],
                "sizes": [[64, 64]],
                "export": {
                    "aseprite": False,
                    "png_frames": False,
                    "previews": False,
                    "preview_sizes": [[64, 64]],
                    "preview_scale": 1,
                    "preview_frames": 1,
                    "zip": False,
                },
                "animations": [{
                    "name": "idle",
                    "source": {"path": str(source), "type": "sequence", "durations_ms": 100},
                }],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = process(config_path, log=lambda _: None)

            animation = report["animations"]["idle"]
            self.assertEqual(animation["source_size"], [512, 256])
            self.assertFalse(animation["source_at_least_work_resolution"])
            self.assertTrue(any("smaller than work canvas" in warning for warning in report["warnings"]))

    def test_low_confidence_automatic_matching_stops_before_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            edited = root / "edited"
            save_sequence(source, [
                frame(16, 16, (1, 1, 5, 15), (180, 30, 20, 255)),
                frame(16, 16, (8, 2, 15, 8), (20, 170, 50, 255)),
            ])
            save_sequence(edited, [frame(16, 16, (3, 3, 13, 13), (240, 220, 20, 255))])
            output = root / "delivery"
            config_path = root / "job.json"
            config = {
                "name": "reject-match",
                "output": str(output),
                "work_size": [16, 16],
                "sizes": [[16, 16]],
                "export": {
                    "aseprite": False,
                    "png_frames": False,
                    "previews": False,
                    "preview_sizes": [[16, 16]],
                    "preview_scale": 1,
                    "preview_frames": 1,
                    "zip": False,
                },
                "animations": [{
                    "name": "walk",
                    "source": {"path": str(source), "type": "sequence", "durations_ms": [60, 70]},
                    "edited": {"path": str(edited), "type": "sequence", "durations_ms": [90]},
                    "matching": {"max_error": 0.001, "min_margin": 0.002},
                }],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "ambiguous/unmatched edited frames"):
                process(config_path, log=lambda _: None)

            failure = json.loads((output / "report.json").read_text(encoding="utf-8"))
            matches = json.loads((output / "matching" / "walk.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["exports"], [])
            self.assertFalse(matches[0]["accepted"])
            self.assertFalse((output / "16px" / "sheets").exists())

    def test_shared_fit_uses_one_constant_scale_for_all_frames_and_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_a = root / "a"
            source_b = root / "b"
            save_sequence(source_a, [
                frame(32, 32, (8, 8, 20, 28), (160, 30, 20, 255)),
                frame(32, 32, (7, 7, 21, 28), (160, 30, 20, 255)),
            ])
            save_sequence(source_b, [
                frame(32, 32, (10, 10, 18, 27), (20, 80, 170, 255)),
                frame(32, 32, (8, 8, 20, 27), (20, 80, 170, 255)),
            ])
            output = root / "delivery"
            config_path = root / "job.json"
            config = {
                "name": "shared-scale",
                "output": str(output),
                "work_size": [32, 32],
                "sizes": [[16, 16]],
                "resample": "nearest",
                "cleanup": {"profile": "off"},
                "layout": {"mode": "shared_fit", "occupancy": 0.8, "anchor": [0.5, 0.95]},
                "export": {
                    "aseprite": False,
                    "png_frames": False,
                    "previews": False,
                    "preview_sizes": [[16, 16]],
                    "preview_scale": 1,
                    "preview_frames": 16,
                    "zip": False,
                },
                "animations": [
                    {"name": "idle.N", "group": "hero", "source": {"path": str(source_a), "type": "sequence", "durations_ms": [90, 110]}},
                    {"name": "walk.N", "group": "hero", "source": {"path": str(source_b), "type": "sequence", "durations_ms": [50, 70]}},
                ],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = process(config_path, log=lambda _: None)

            first = report["animations"]["idle.N"]
            second = report["animations"]["walk.N"]
            self.assertEqual(first["shared_group"], "hero")
            self.assertEqual(first["shared_group_scale"], second["shared_group_scale"])
            self.assertEqual(first["actual_scale"], second["actual_scale"])
            self.assertEqual(first["zoom_scales"], [1.0, 1.0])
            self.assertEqual(second["zoom_scales"], [1.0, 1.0])
            self.assertNotEqual(first["work_metrics"]["areas"][0], first["work_metrics"]["areas"][1])


class OptionalAsepriteTests(unittest.TestCase):
    def test_rectangular_full_canvas_roundtrip_and_repeat_endpoint_timing(self):
        try:
            executable = find_aseprite("auto")
        except FileNotFoundError as error:
            self.skipTest(str(error))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = [frame(7, 5, (i % 4, 1, i % 4 + 3, 5), (20 + i * 20, 80, 140, 255)) for i in range(8)]
            indices = sequence_indices(8, pingpong="repeat_ends")
            frames = [base[index] for index in indices]
            base_durations = [31, 37, 41, 43, 47, 53, 59, 61]
            durations = [base_durations[index] for index in indices]
            sheet = root / "sheet.png"
            result = root / "rectangular.aseprite"
            save_sheet(frames, sheet)

            create_aseprite(sheet, result, (7, 5), durations, "rectangular", executable)
            exported = export_aseprite(result, root / "roundtrip", executable)

            self.assertEqual(len(exported.frames), 16)
            self.assertEqual(exported.durations, durations)
            self.assertTrue(all(item.shape == (5, 7, 4) for item in exported.frames))
            self.assertTrue(all(np.array_equal(actual, expected) for actual, expected in zip(exported.frames, frames)))
            self.assertTrue(np.array_equal(exported.frames[7], exported.frames[8]))


if __name__ == "__main__":
    unittest.main()
