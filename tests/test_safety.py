import unittest

import numpy as np

from spritepost.imaging import correct_zoom, letterbox, resize


class SafetyTests(unittest.TestCase):
    def test_explicit_zoom_cannot_silently_crop_visible_content(self):
        frame = np.zeros((32, 32, 4), dtype=np.uint8)
        frame[1:31, 1:31] = [80, 40, 30, 255]
        with self.assertRaisesRegex(ValueError, "would crop"):
            correct_zoom([frame, frame], {"start_scale": 1, "end_scale": 2}, "lanczos4")

    def test_same_aspect_letterbox_uses_resize_pixel_center_convention(self):
        frame = np.zeros((40, 60, 4), dtype=np.uint8)
        frame[8:32, 14:45] = [180, 80, 20, 255]
        frame[12:22, 22:28] = [30, 70, 190, 100]
        for algorithm in ("lanczos4", "box", "nearest"):
            with self.subTest(algorithm=algorithm):
                self.assertTrue(np.array_equal(letterbox(frame, (15, 10), algorithm),
                                               resize(frame, (15, 10), algorithm)))


if __name__ == "__main__":
    unittest.main()
