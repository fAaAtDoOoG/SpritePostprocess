from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from spritepost.config import validate_config
from spritepost.imaging import (clean_frame, correct_zoom, letterbox, resize,
                                sequence_indices)
from spritepost.matching import match_frames


def canvas(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 4), dtype=np.uint8)


def block(width: int, height: int, rect, color=(180, 40, 30, 255)) -> np.ndarray:
    frame = canvas(width, height)
    x0, y0, x1, y1 = rect
    frame[y0:y1, x0:x1] = color
    return frame


def minimal_config(source: Path, output: Path) -> dict:
    return {
        "version": 1,
        "name": "test-character",
        "output": str(output),
        "export": {
            "aseprite": False,
            "png_frames": False,
            "previews": False,
            "preview_sizes": [[8, 8]],
            "preview_scale": 1,
            "preview_frames": 16,
            "zip": False,
        },
        "animations": [{
            "name": "idle.N",
            "source": {"path": str(source), "type": "sequence", "durations_ms": 80},
        }],
    }


class ImagingTests(unittest.TestCase):
    def test_premultiplied_resize_does_not_bleed_hidden_white_rgb(self):
        source = canvas(4, 2)
        source[:, 0] = (255, 255, 255, 0)
        source[:, 1] = (210, 20, 10, 255)

        result = resize(source, (2, 1), "lanczos4")

        visible = result[..., 3] > 0
        self.assertTrue(visible.any())
        self.assertLessEqual(int(result[..., 1][visible].max()), 20)
        self.assertLessEqual(int(result[..., 2][visible].max()), 10)
        self.assertTrue(np.all(result[result[..., 3] == 0, :3] == 0))

    def test_letterbox_preserves_rectangular_aspect_and_centers(self):
        source = np.full((4, 8, 4), (30, 90, 170, 255), dtype=np.uint8)

        result = letterbox(source, (12, 12), "nearest")

        alpha = result[..., 3]
        ys, xs = np.where(alpha > 0)
        self.assertEqual((int(xs.min()), int(xs.max()) + 1), (0, 12))
        self.assertEqual((int(ys.min()), int(ys.max()) + 1), (3, 9))
        self.assertTrue(np.all(alpha[:3] == 0))
        self.assertTrue(np.all(alpha[9:] == 0))

    def test_strict_cleanup_repairs_edge_contamination_but_keeps_interior_white(self):
        source = block(12, 12, (2, 2, 10, 10), (80, 35, 20, 255))
        source[2, 5] = (255, 255, 255, 255)
        source[5, 5] = (255, 255, 255, 255)

        result, report = clean_frame(source, {"profile": "strict"})

        self.assertGreater(report["changed_pixels"], 0)
        self.assertNotEqual(tuple(result[2, 5, :3]), (255, 255, 255))
        self.assertEqual(tuple(result[5, 5]), (255, 255, 255, 255))
        self.assertEqual(report["detector_residual"], 0)

    def test_cleanup_off_preserves_all_visible_pixels(self):
        source = block(6, 6, (1, 1, 5, 5), (245, 245, 245, 255))
        source[0, 0] = (255, 255, 255, 0)

        result, report = clean_frame(source, {"profile": "off"})

        visible = source[..., 3] > 0
        self.assertTrue(np.array_equal(result[visible], source[visible]))
        self.assertTrue(np.array_equal(result[..., 3], source[..., 3]))
        self.assertEqual(tuple(result[0, 0]), (0, 0, 0, 0))
        self.assertEqual(report["detector_residual"], None)

    def test_sequence_modes_have_documented_endpoint_behavior(self):
        self.assertEqual(sequence_indices(4, reverse=True), [3, 2, 1, 0])
        self.assertEqual(
            sequence_indices(8, pingpong="repeat_ends"),
            [0, 1, 2, 3, 4, 5, 6, 7, 7, 6, 5, 4, 3, 2, 1, 0],
        )
        self.assertEqual(
            sequence_indices(8, pingpong="no_repeat_ends"),
            [0, 1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2, 1],
        )

    def test_zoom_is_only_applied_when_explicitly_configured(self):
        frames = [block(16, 16, (4, 4, 12, 12)), block(16, 16, (3, 3, 13, 13))]

        unchanged, scales = correct_zoom(frames, None, "nearest")
        corrected, explicit_scales = correct_zoom(
            frames,
            {"start_scale": 1.0, "end_scale": 0.8, "easing": "linear"},
            "nearest",
        )

        self.assertEqual(scales, [1.0, 1.0])
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(unchanged, frames)))
        self.assertEqual(explicit_scales, [1.0, 0.8])
        self.assertFalse(np.array_equal(corrected[1], frames[1]))


class MatchingTests(unittest.TestCase):
    def test_matching_accepts_a_clean_reorder(self):
        original = [
            block(20, 20, (2, 3, 7, 17), (170, 30, 20, 255)),
            block(20, 20, (4, 2, 17, 8), (20, 160, 50, 255)),
            block(20, 20, (7, 5, 15, 18), (30, 60, 190, 255)),
        ]
        edited = [original[2].copy(), original[0].copy(), original[1].copy()]

        mapping, reports = match_frames(edited, original)

        self.assertEqual(mapping, [(2, False), (0, False), (1, False)])
        self.assertTrue(all(record["accepted"] for record in reports))

    def test_matching_rejects_a_near_tie_below_margin(self):
        first = block(24, 24, (4, 4, 20, 20), (120, 60, 20, 255))
        second = first.copy()
        first[10, 10, :3] = (121, 60, 20)
        second[10, 10, :3] = (119, 60, 20)
        query = block(24, 24, (4, 4, 20, 20), (120, 60, 20, 255))

        _, reports = match_frames(
            [query], [first, second],
            {"compare_size": 64, "max_error": 1.0, "min_margin": 0.01},
        )

        self.assertFalse(reports[0]["accepted"])
        self.assertLess(reports[0]["margin"], 0.01)

    def test_position_only_variants_are_not_treated_as_equivalent_frames(self):
        first = block(20, 20, (5, 5, 10, 10), (120, 60, 20, 255))
        shifted = block(20, 20, (11, 9, 16, 14), (120, 60, 20, 255))

        _, reports = match_frames([shifted.copy()], [first, shifted])

        self.assertFalse(reports[0]["accepted"])
        self.assertEqual(reports[0]["margin"], 0.0)
        self.assertEqual(reports[0]["equivalent_candidates"], [0])


class ConfigTests(unittest.TestCase):
    def test_relative_paths_are_resolved_from_config_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = minimal_config(Path("inputs"), Path("results"))

            resolved = validate_config(config, base)

            self.assertEqual(Path(resolved["animations"][0]["source"]["path"]), base / "inputs")
            self.assertEqual(Path(resolved["output"]), base / "results")

    def test_output_must_not_overlap_an_input_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "inputs"
            source.mkdir()
            config = minimal_config(source, source / "delivery")

            with self.assertRaisesRegex(ValueError, "Output must be separate"):
                validate_config(config, base)

    def test_unknown_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = minimal_config(base / "input", base / "output")
            config["mystery"] = True

            with self.assertRaisesRegex(ValueError, "Unknown root setting"):
                validate_config(config, base)

    def test_duplicate_animation_names_are_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = minimal_config(base / "input", base / "output")
            config["animations"].append({
                "name": "IDLE.n",
                "source": {"path": str(base / "second"), "type": "sequence", "fps": 12},
            })

            with self.assertRaisesRegex(ValueError, "Duplicate animation name"):
                validate_config(config, base)


if __name__ == "__main__":
    unittest.main()
