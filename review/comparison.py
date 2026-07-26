"""Deterministic comparisons for original and reviewed annotations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class AnnotationComparison:
    original_json_sha256: str
    reviewed_json_sha256: Optional[str]
    annotation_changed: Optional[bool]
    geometry_changed: Optional[bool]
    raster_mask_changed: Optional[bool]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("shapes"), list):
        raise ValueError(f"Invalid annotation JSON: {path}")
    return data


def _point(point: Sequence[float]) -> Tuple[float, float]:
    return (round(float(point[0]), 8), round(float(point[1]), 8))


def _canonical_polygon(points):
    points = tuple(_point(point) for point in points)
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if not points:
        return points
    rotations = [points[index:] + points[:index] for index in range(len(points))]
    reversed_points = tuple(reversed(points))
    rotations.extend(
        reversed_points[index:] + reversed_points[:index]
        for index in range(len(reversed_points))
    )
    return min(rotations)


def _canonical_shape(shape):
    shape_type = shape.get("shape_type", "polygon")
    points = shape.get("points", [])
    if shape_type == "polygon":
        canonical_points = _canonical_polygon(points)
    elif shape_type == "rectangle" and len(points) >= 2:
        first, second = _point(points[0]), _point(points[1])
        canonical_points = (
            (min(first[0], second[0]), min(first[1], second[1])),
            (max(first[0], second[0]), max(first[1], second[1])),
        )
    elif shape_type in {"line", "linestrip"}:
        forward = tuple(_point(point) for point in points)
        backward = tuple(reversed(forward))
        canonical_points = min(forward, backward)
    else:
        canonical_points = tuple(_point(point) for point in points)
    return shape_type, canonical_points


def geometry_signature(annotation: dict):
    """Return an order-independent signature of shape geometry only."""
    return tuple(sorted(_canonical_shape(shape) for shape in annotation["shapes"]))


def _mask(annotation: dict, width: int, height: int) -> Image.Image:
    mask = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for shape in annotation["shapes"]:
        points = [tuple(map(float, point)) for point in shape.get("points", [])]
        shape_type = shape.get("shape_type", "polygon")
        if shape_type == "polygon" and len(points) >= 3:
            draw.polygon(points, fill=1)
        elif shape_type == "rectangle" and len(points) >= 2:
            draw.rectangle((points[0], points[1]), fill=1)
        elif shape_type == "circle" and len(points) >= 2:
            center, edge = points[0], points[1]
            radius = ((edge[0] - center[0]) ** 2 + (edge[1] - center[1]) ** 2) ** 0.5
            draw.ellipse(
                (
                    center[0] - radius,
                    center[1] - radius,
                    center[0] + radius,
                    center[1] + radius,
                ),
                fill=1,
            )
        elif shape_type in {"line", "linestrip"} and len(points) >= 2:
            draw.line(points, fill=1, width=1)
        elif shape_type == "point" and points:
            x, y = points[0]
            draw.point((x, y), fill=1)
    return mask


def _dimensions(original: dict, reviewed: dict) -> Tuple[int, int]:
    width = original.get("imageWidth") or reviewed.get("imageWidth")
    height = original.get("imageHeight") or reviewed.get("imageHeight")
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("Annotation imageWidth and imageHeight are required.")
    if width <= 0 or height <= 0:
        raise ValueError("Annotation dimensions must be positive.")
    return width, height


def compare_annotations(
    original_path: Path,
    reviewed_path: Optional[Path],
) -> AnnotationComparison:
    original_path = Path(original_path)
    original_hash = sha256_file(original_path)
    if reviewed_path is None or not Path(reviewed_path).is_file():
        return AnnotationComparison(original_hash, None, None, None, None)

    reviewed_path = Path(reviewed_path)
    reviewed_hash = sha256_file(reviewed_path)
    original = _load_json(original_path)
    reviewed = _load_json(reviewed_path)
    width, height = _dimensions(original, reviewed)
    return AnnotationComparison(
        original_json_sha256=original_hash,
        reviewed_json_sha256=reviewed_hash,
        annotation_changed=original_hash != reviewed_hash,
        geometry_changed=(
            geometry_signature(original) != geometry_signature(reviewed)
        ),
        raster_mask_changed=(
            _mask(original, width, height).tobytes()
            != _mask(reviewed, width, height).tobytes()
        ),
    )
