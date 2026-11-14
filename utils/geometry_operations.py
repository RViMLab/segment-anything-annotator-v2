"""Native-resolution checks for deliberately geometry-changing operations."""

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw


class GeometrySafetyError(ValueError):
    pass


def polygon_mask(points, size):
    mask = np.zeros(size, dtype=np.uint8)
    if len(points) >= 3:
        cv2.fillPoly(mask, [np.asarray(points, dtype=np.float64).astype(np.int32)], 1)
    return mask


def mask_topology(mask):
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_TREE,
                                          cv2.CHAIN_APPROX_SIMPLE)
    holes = 0
    if hierarchy is not None:
        for index in range(len(contours)):
            depth, parent = 0, hierarchy[0, index, 3]
            while parent != -1:
                depth += 1
                parent = hierarchy[0, parent, 3]
            holes += depth % 2
    smallest = int(stats[1:, cv2.CC_STAT_AREA].min()) if count > 1 else 0
    return count - 1, holes, smallest


@dataclass(frozen=True)
class GeometryReport:
    added: int
    removed: int
    before_regions: int
    after_regions: int
    before_holes: int
    after_holes: int
    smallest_region: int

    def describe(self):
        return (
            f"Pixels added: {self.added}; removed: {self.removed}.\n"
            f"Connected regions: {self.before_regions} → {self.after_regions}.\n"
            f"Holes: {self.before_holes} → {self.after_holes}.\n"
            f"Smallest resulting region: {self.smallest_region} pixels."
        )


def describe_change(before, after):
    before_regions, before_holes, _ = mask_topology(before)
    after_regions, after_holes, smallest = mask_topology(after)
    return GeometryReport(
        int(np.count_nonzero((after > 0) & (before == 0))),
        int(np.count_nonzero((before > 0) & (after == 0))),
        before_regions, after_regions, before_holes, after_holes, smallest,
    )


def exact_mask_polygons(mask):
    """Return ordinary filled polygons only when they reproduce every pixel.

    Split holes into hole-free parts, without assigning hole semantics to IDs
    or adding a JSON extension. Parts keep their caller's label and metadata.
    """
    mask = (np.asarray(mask) > 0).astype(np.uint8)
    budget = [512]

    def decompose(part, offset_x=0, offset_y=0, depth=0):
        budget[0] -= 1
        if budget[0] < 0 or depth > 32:
            raise GeometrySafetyError("Too many polygon parts are needed to preserve this mask safely.")
        x, y, width, height = cv2.boundingRect(part)
        if not width or not height:
            return []
        part = part[y:y + height, x:x + width].copy()
        offset_x, offset_y = offset_x + x, offset_y + y
        contours, hierarchy = cv2.findContours(part, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        holes = [contour for contour, relation in zip(contours, hierarchy[0]) if relation[3] != -1]
        if not holes:
            if any(len(contour) < 3 for contour in contours):
                raise GeometrySafetyError("A small or thin region cannot be represented as a filled polygon.")
            return [(contour.reshape(-1, 2) + [offset_x, offset_y]).tolist() for contour in contours]
        hx, hy, hw, hh = cv2.boundingRect(holes[0])
        cut_x, cut_y = hx + hw // 2, hy + hh // 2
        # Cutting through a hole opens it at the boundary of each half. Try
        # the less crowded seam first, then the other axis if it creates a
        # degenerate piece. Limits bound complex masks instead of hanging.
        cuts = []
        if 0 < cut_x < width:
            cuts.append((int(part[:, cut_x - 1:cut_x + 1].sum()), "x", cut_x))
        if 0 < cut_y < height:
            cuts.append((int(part[cut_y - 1:cut_y + 1, :].sum()), "y", cut_y))
        failure = None
        for _, axis, cut in sorted(cuts):
            try:
                if axis == "x":
                    return (decompose(part[:, :cut], offset_x, offset_y, depth + 1)
                            + decompose(part[:, cut:], offset_x + cut, offset_y, depth + 1))
                return (decompose(part[:cut, :], offset_x, offset_y, depth + 1)
                        + decompose(part[cut:, :], offset_x, offset_y + cut, depth + 1))
            except GeometrySafetyError as error:
                failure = error
        raise failure or GeometrySafetyError("Cannot split this hole into safe filled polygon parts.")

    points = decompose(mask)
    reproduced = np.zeros_like(mask, dtype=np.uint8)
    compatible = Image.new("L", (mask.shape[1], mask.shape[0]))
    draw = ImageDraw.Draw(compatible)
    for polygon in points:
        reproduced |= polygon_mask(polygon, mask.shape)
        draw.polygon([tuple(point) for point in polygon], fill=1)
    if not np.array_equal(reproduced > 0, mask > 0):
        raise GeometrySafetyError("Polygon conversion would change native-resolution pixels.")
    if not np.array_equal(np.asarray(compatible) > 0, mask > 0):
        raise GeometrySafetyError("Polygon conversion would change pixels in the compatible mask export.")
    return points
