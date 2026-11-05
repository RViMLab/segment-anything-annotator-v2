"""Native-resolution checks for deliberately geometry-changing operations."""

from dataclasses import dataclass

import cv2
import numpy as np


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

    Existing JSON polygons are independently filled, with no hole convention.
    Reject holes and degenerate contours rather than silently filling/dropping
    them. Never filter components by area.
    """
    if mask_topology(mask)[1]:
        raise GeometrySafetyError("The result contains holes that this polygon format cannot preserve.")
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    points = [contour.reshape(-1, 2).tolist() for contour in contours]
    if any(len(polygon) < 3 for polygon in points):
        raise GeometrySafetyError("A small or thin region cannot be represented as a filled polygon.")
    reproduced = np.zeros_like(mask, dtype=np.uint8)
    for polygon in points:
        reproduced |= polygon_mask(polygon, mask.shape)
    if not np.array_equal(reproduced > 0, mask > 0):
        raise GeometrySafetyError("Polygon conversion would change native-resolution pixels.")
    return points
