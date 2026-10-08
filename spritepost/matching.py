from __future__ import annotations

import numpy as np

from .imaging import bbox, letterbox


def _feature(frame, size):
    # Ignore original canvas placement, but preserve the silhouette aspect ratio.
    box = bbox(frame, 8)
    if box is None:
        return np.zeros((size, size, 4), dtype=np.float32)
    x0, y0, x1, y1 = box
    fitted = letterbox(frame[y0:y1, x0:x1], (size, size), "lanczos4").astype(np.float32)/255
    fitted[..., :3] *= fitted[..., 3:4]
    return fitted


def match_frames(edited, original, settings=None):
    settings = settings or {}
    size = int(settings.get("compare_size", 64))
    max_error = settings.get("max_error", .12)
    min_margin = settings.get("min_margin", .002)
    candidates = []
    for i, frame in enumerate(original):
        candidates.append((i, False, _feature(frame, size), frame))
        if settings.get("allow_mirror", False):
            candidates.append((i, True, _feature(frame[:, ::-1], size), frame[:, ::-1]))
    mapping, reports = [], []
    for output_index, frame in enumerate(edited):
        query = _feature(frame, size)
        scores = []
        for source, mirrored, candidate, original_pixels in candidates:
            union = (query[..., 3] > .03) | (candidate[..., 3] > .03)
            score = float(np.abs(query-candidate)[union].mean()) if union.any() else 0
            scores.append((score, source, mirrored, candidate, original_pixels))
        scores.sort(key=lambda s: s[:3])
        best = scores[0]
        # Exact duplicate originals are equivalent, not arbitrary ambiguous choices.
        # Cropped features may coincide for frames that bob/translate on the canvas.
        # Only actual full-canvas original pixels qualify as interchangeable.
        alternatives = [s for s in scores[1:] if not np.array_equal(s[4], best[4])]
        margin = alternatives[0][0] - best[0] if alternatives else 1.0
        accepted = best[0] <= max_error and margin >= min_margin
        reports.append({"edited_index": output_index, "source_index": best[1], "mirrored": best[2],
                        "error": best[0], "margin": margin, "accepted": accepted,
                        "equivalent_candidates": [s[1] for s in scores if np.array_equal(s[4], best[4])]})
        mapping.append((best[1], best[2]))
    return mapping, reports
