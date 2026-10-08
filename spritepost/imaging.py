from __future__ import annotations

import cv2
import numpy as np


FILTERS = {"lanczos4": cv2.INTER_LANCZOS4, "nearest": cv2.INTER_NEAREST, "box": cv2.INTER_AREA}


def _premultiply(frame):
    value = frame.astype(np.float32) / 255
    value[..., :3] *= value[..., 3:4]
    return value


def _straight(value):
    alpha = np.clip(value[..., 3:4], 0, 1)
    rgb = np.zeros_like(value[..., :3])
    np.divide(value[..., :3], alpha, out=rgb, where=alpha > .5 / 255)
    out = np.rint(np.concatenate((np.clip(rgb, 0, 1), alpha), axis=2) * 255).astype(np.uint8)
    out[out[..., 3] == 0, :3] = 0
    return out


def resize(frame, size, algorithm="lanczos4"):
    if tuple(size) == (frame.shape[1], frame.shape[0]):
        out = frame.copy()
        out[out[..., 3] == 0, :3] = 0
        return out
    return _straight(cv2.resize(_premultiply(frame), tuple(size), interpolation=FILTERS[algorithm]))


def warp(frame, size, scale=1.0, offset=(0.0, 0.0), algorithm="lanczos4"):
    matrix = np.array([[scale, 0, offset[0]], [0, scale, offset[1]]], dtype=np.float32)
    # OpenCV has no area-integration affine warp. BOX is only used for final resizing.
    interpolation = cv2.INTER_LINEAR if algorithm == "box" else FILTERS[algorithm]
    return _straight(cv2.warpAffine(
        _premultiply(frame), matrix, tuple(size), flags=interpolation,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0),
    ))


def letterbox(frame, size, algorithm="lanczos4"):
    scale = min(size[0] / frame.shape[1], size[1] / frame.shape[0])
    if scale == 1 and tuple(size) == (frame.shape[1], frame.shape[0]):
        return resize(frame, size, algorithm)
    fitted = (max(1, min(size[0], round(frame.shape[1]*scale))),
              max(1, min(size[1], round(frame.shape[0]*scale))))
    # resize uses pixel-center sampling and true INTER_AREA when BOX is selected.
    # An affine warp has different half-pixel conventions and cannot do area filtering.
    scaled = resize(frame, fitted, algorithm)
    out = np.zeros((size[1], size[0], 4), np.uint8)
    x, y = (size[0]-fitted[0])//2, (size[1]-fitted[1])//2
    out[y:y+fitted[1], x:x+fitted[0]] = scaled
    return out


def bbox(frame, threshold=8):
    ys, xs = np.where(frame[..., 3] >= threshold)
    if not len(xs):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def union_bbox(frames, threshold=8):
    boxes = [b for f in frames if (b := bbox(f, threshold)) is not None]
    if not boxes:
        raise ValueError("Animation has no visible pixels")
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def frame_metrics(frames, threshold=8):
    boxes = [bbox(f, threshold) for f in frames]
    areas = [int(np.count_nonzero(f[..., 3] >= threshold)) for f in frames]
    edge = [i for i, f in enumerate(frames) if any(np.any(a >= threshold) for a in
            (f[0, :, 3], f[-1, :, 3], f[:, 0, 3], f[:, -1, 3]))]
    k = min(3, len(frames))
    start = float(np.median(areas[:k]))
    return {"bboxes": boxes, "areas": areas, "edge_frames": edge,
            "end_start_area_ratio": float(np.median(areas[-k:])) / start if start else None,
            "empty_frames": [i for i, b in enumerate(boxes) if b is None]}


def luminance(rgb):
    return rgb.astype(np.float32) @ np.array([.299, .587, .114], dtype=np.float32)


def saturation(rgb):
    values = rgb.astype(np.float32)
    return (values.max(axis=2) - values.min(axis=2)) / np.maximum(values.max(axis=2), 1)


def cleanup_options(settings):
    profile = settings.get("profile", "off")
    result = {
        "profile": profile, "edge_width": 2, "reference_radius": 4,
        "alpha_cutoff": 8, "dust_area": 4, "opaque_luminance": 178,
        "partial_luminance": 150, "opaque_saturation": .38,
        "partial_saturation": .48, "opaque_gap": 16, "partial_gap": 12,
        "passes": 12,
    }
    if profile == "conservative":
        result.update(edge_width=1, alpha_cutoff=2, dust_area=1,
                      opaque_luminance=225, partial_luminance=205,
                      opaque_saturation=.16, partial_saturation=.22,
                      opaque_gap=40, partial_gap=32, passes=3)
    result.update(settings)
    for key in ("edge_width", "reference_radius", "alpha_cutoff", "dust_area", "passes"):
        if isinstance(result[key], bool) or not isinstance(result[key], int) or not 0 <= result[key] <= 255:
            raise ValueError(f"cleanup.{key} must be an integer in 0..255")
    if result["passes"] < 1 or result["reference_radius"] < 1:
        raise ValueError("cleanup passes/reference_radius must be positive")
    for key in ("opaque_luminance", "partial_luminance", "opaque_gap", "partial_gap"):
        if not 0 <= result[key] <= 255:
            raise ValueError(f"cleanup.{key} must be in 0..255")
    for key in ("opaque_saturation", "partial_saturation"):
        if not 0 <= result[key] <= 1:
            raise ValueError(f"cleanup.{key} must be in 0..1")
    return result


def candidate_mask(frame, options):
    a = frame[..., 3]
    foreground = a > 0
    width = options["edge_width"]
    edge = foreground & (cv2.dilate((~foreground).astype(np.uint8),
                                    np.ones((2 * width + 1, 2 * width + 1), np.uint8),
                                    borderType=cv2.BORDER_CONSTANT, borderValue=1) > 0)
    lum, sat = luminance(frame[..., :3]), saturation(frame[..., :3])
    return edge & (((lum >= options["opaque_luminance"]) & (sat <= options["opaque_saturation"])) |
                   ((a < 255) & (lum >= options["partial_luminance"]) & (sat <= options["partial_saturation"])))


def nearest_reference(frame, y, x, excluded, radius):
    samples = []
    for distance in range(1, radius + 1):
        for yy in range(max(0, y-distance), min(frame.shape[0], y+distance+1)):
            for xx in range(max(0, x-distance), min(frame.shape[1], x+distance+1)):
                if max(abs(yy-y), abs(xx-x)) != distance or frame[yy, xx, 3] < 96 or excluded[yy, xx]:
                    continue
                samples.append(((yy-y)**2 + (xx-x)**2, frame[yy, xx, :3]))
        if len(samples) >= 5:
            break
    if not samples:
        return None
    samples.sort(key=lambda v: v[0])
    return np.median(np.stack([s[1] for s in samples[:9]]).astype(np.float32), axis=0)


def _replacements(frame, options):
    candidates = candidate_mask(frame, options)
    lum = luminance(frame[..., :3])
    result = []
    for y, x in zip(*np.where(candidates)):
        reference = nearest_reference(frame, int(y), int(x), candidates, options["reference_radius"])
        if reference is None:
            continue
        key = "partial_gap" if frame[y, x, 3] < 255 else "opaque_gap"
        if lum[y, x] >= float(reference @ np.array([.299, .587, .114])) + options[key]:
            result.append((y, x, reference))
    return result


def clean_frame(frame, settings):
    options = cleanup_options(settings)
    out = frame.copy()
    before = out.copy()
    dust = 0
    recolored = 0
    if options["profile"] != "off":
        out[out[..., 3] < options["alpha_cutoff"]] = 0
        count, labels, stats, _ = cv2.connectedComponentsWithStats((out[..., 3] > 0).astype(np.uint8), connectivity=8)
        lum, sat = luminance(out[..., :3]), saturation(out[..., :3])
        for component in range(1, count):
            if stats[component, cv2.CC_STAT_AREA] > options["dust_area"]:
                continue
            mask = labels == component
            if np.mean((lum[mask] >= options["partial_luminance"]) &
                       (sat[mask] <= options["partial_saturation"])) >= .5 or out[..., 3][mask].max(initial=0) < 48:
                dust += int(mask.sum())
                out[mask] = 0
        for _ in range(options["passes"]):
            replacements = _replacements(out, options)
            if not replacements:
                break
            for y, x, reference in replacements:
                out[y, x, :3] = np.rint(np.clip(reference, 0, 255)).astype(np.uint8)
            recolored += len(replacements)
    out[out[..., 3] == 0, :3] = 0
    residual = len(_replacements(out, options)) if options["profile"] != "off" else None
    return out, {"changed_pixels": int(np.any(out != before, axis=2).sum()),
                 "dust_pixels_removed": dust, "edge_recolor_operations": recolored,
                 "detector_residual": residual}


def clean_frames(frames, settings):
    pairs = [clean_frame(frame, settings) for frame in frames]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def sequence_indices(count, frame_map=None, reverse=False, pingpong="none"):
    indices = list(range(count)) if frame_map is None else list(frame_map)
    if not indices or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < count for i in indices):
        raise ValueError(f"frame_map must contain valid zero-based indices in 0..{count-1}")
    if reverse:
        indices.reverse()
    if pingpong == "repeat_ends":
        indices += indices[::-1]
    elif pingpong == "no_repeat_ends":
        indices += indices[-2:0:-1]
    return indices


def correct_zoom(frames, settings, algorithm):
    if not settings:
        return frames, [1.0] * len(frames)
    box = union_bbox(frames)
    anchor = ((box[0] + box[2]) / 2, box[3])
    start, end = settings.get("start_scale", 1), settings.get("end_scale", 1)
    output, scales = [], []
    for i, frame in enumerate(frames):
        t = i / max(1, len(frames)-1)
        if settings.get("easing", "smoothstep") == "smoothstep":
            t = t*t*(3-2*t)
        scale = start + (end-start)*t
        scales.append(scale)
        offset = (anchor[0]*(1-scale), anchor[1]*(1-scale))
        ensure_bounds(frame, (frame.shape[1], frame.shape[0]), scale, offset,
                      f"zoom frame {i}")
        output.append(warp(frame, (frame.shape[1], frame.shape[0]), scale,
                           offset, algorithm))
    return output, scales


def ensure_bounds(frame, size, scale, offset, label):
    box = bbox(frame, 8)
    if box is None:
        return
    x0, y0, x1, y1 = box
    if (x0*scale+offset[0] < -1e-6 or y0*scale+offset[1] < -1e-6 or
            x1*scale+offset[0] > size[0]+1e-6 or y1*scale+offset[1] > size[1]+1e-6):
        raise ValueError(f"{label}: transform would crop visible pixels. Reduce zoom/scale_multiplier or provide more source padding.")
