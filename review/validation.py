from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image

from .models import (
    ReviewConfig,
    ReviewPair,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ANNOTATION_EXTENSION = ".json"


def _issue(
    report: ValidationReport,
    severity: ValidationSeverity,
    code: str,
    message: str,
    path: Optional[Path] = None,
) -> None:
    report.issues.append(
        ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            path=path,
        )
    )


def _relative_key(path: Path, root: Path) -> str:
    return path.relative_to(root).with_suffix("").as_posix().casefold()


def _collect_files(
    root: Path,
    extensions: Iterable[str],
) -> Tuple[Dict[str, Path], Dict[str, List[Path]]]:
    allowed = {extension.casefold() for extension in extensions}
    grouped: Dict[str, List[Path]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.casefold() in allowed:
            grouped.setdefault(_relative_key(path, root), []).append(path)
    unique = {
        key: paths[0]
        for key, paths in grouped.items()
        if len(paths) == 1
    }
    duplicates = {
        key: paths
        for key, paths in grouped.items()
        if len(paths) > 1
    }
    return unique, duplicates


def _is_nested(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(child), str(parent))) == str(parent)
    except ValueError:
        return False


def _validate_directory(
    report: ValidationReport,
    path: Path,
    label: str,
    code_prefix: str,
) -> bool:
    if not path.exists():
        _issue(
            report,
            ValidationSeverity.ERROR,
            f"{code_prefix}_missing",
            f"{label} does not exist.",
            path,
        )
        return False
    if not path.is_dir():
        _issue(
            report,
            ValidationSeverity.ERROR,
            f"{code_prefix}_not_directory",
            f"{label} is not a directory.",
            path,
        )
        return False
    if not os.access(path, os.R_OK):
        _issue(
            report,
            ValidationSeverity.ERROR,
            f"{code_prefix}_not_readable",
            f"{label} is not readable.",
            path,
        )
        return False
    return True


def _load_annotation(
    report: ValidationReport,
    annotation_path: Path,
) -> Optional[dict]:
    try:
        with annotation_path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _issue(
            report,
            ValidationSeverity.ERROR,
            "invalid_json",
            f"Annotation JSON could not be read: {error}",
            annotation_path,
        )
        return None

    if not isinstance(data, dict):
        _issue(
            report,
            ValidationSeverity.ERROR,
            "invalid_annotation_root",
            "Annotation JSON root must be an object.",
            annotation_path,
        )
        return None

    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        _issue(
            report,
            ValidationSeverity.ERROR,
            "missing_shapes",
            "Annotation JSON must contain a 'shapes' list.",
            annotation_path,
        )
        return None

    for index, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            _issue(
                report,
                ValidationSeverity.ERROR,
                "invalid_shape",
                f"Shape {index} must be an object.",
                annotation_path,
            )
            continue
        points = shape.get("points")
        if not isinstance(points, list):
            _issue(
                report,
                ValidationSeverity.ERROR,
                "invalid_shape_points",
                f"Shape {index} must contain a points list.",
                annotation_path,
            )
            continue
        for point_index, point in enumerate(points):
            valid_point = (
                isinstance(point, (list, tuple))
                and len(point) == 2
                and all(
                    isinstance(coordinate, (int, float))
                    and not isinstance(coordinate, bool)
                    for coordinate in point
                )
            )
            if not valid_point:
                _issue(
                    report,
                    ValidationSeverity.ERROR,
                    "invalid_point",
                    f"Shape {index}, point {point_index} is not an x/y pair.",
                    annotation_path,
                )
                break
    return data


def _image_dimensions(
    report: ValidationReport,
    image_path: Path,
) -> Tuple[Optional[int], Optional[int]]:
    try:
        with Image.open(image_path) as image:
            width, height = image.size
        return width, height
    except (OSError, ValueError) as error:
        _issue(
            report,
            ValidationSeverity.ERROR,
            "unreadable_image",
            f"Image could not be read: {error}",
            image_path,
        )
        return None, None


def _validate_dimensions(
    report: ValidationReport,
    annotation: dict,
    annotation_path: Path,
    image_width: Optional[int],
    image_height: Optional[int],
) -> None:
    if image_width is None or image_height is None:
        return
    json_width = annotation.get("imageWidth")
    json_height = annotation.get("imageHeight")
    if json_width is None or json_height is None:
        _issue(
            report,
            ValidationSeverity.WARNING,
            "annotation_dimensions_missing",
            "Annotation does not record imageWidth and imageHeight.",
            annotation_path,
        )
        return
    if json_width != image_width or json_height != image_height:
        _issue(
            report,
            ValidationSeverity.ERROR,
            "dimension_mismatch",
            (
                f"Annotation dimensions {json_width}x{json_height} do not match "
                f"the image dimensions {image_width}x{image_height}."
            ),
            annotation_path,
        )


def validate_review_config(config: ReviewConfig) -> ValidationReport:
    config = config.normalized()
    report = ValidationReport(config=config)

    if not config.reviewer_id:
        _issue(
            report,
            ValidationSeverity.ERROR,
            "reviewer_id_missing",
            "Reviewer ID is required.",
        )

    images_valid = _validate_directory(
        report,
        config.image_directory,
        "Image directory",
        "image_directory",
    )
    annotations_valid = _validate_directory(
        report,
        config.annotation_directory,
        "Annotation directory",
        "annotation_directory",
    )
    output_valid = _validate_directory(
        report,
        config.output_directory,
        "Review output directory",
        "output_directory",
    )

    if annotations_valid and output_valid:
        if config.output_directory == config.annotation_directory:
            _issue(
                report,
                ValidationSeverity.ERROR,
                "output_matches_annotations",
                "Review output must not be the original annotation directory.",
                config.output_directory,
            )
        elif _is_nested(config.output_directory, config.annotation_directory):
            _issue(
                report,
                ValidationSeverity.ERROR,
                "output_inside_annotations",
                "Review output must not be inside the original annotation directory.",
                config.output_directory,
            )

    if output_valid and not os.access(config.output_directory, os.W_OK):
        _issue(
            report,
            ValidationSeverity.ERROR,
            "output_not_writable",
            "Review output directory is not writable.",
            config.output_directory,
        )

    if not images_valid or not annotations_valid:
        return report

    images, duplicate_images = _collect_files(
        config.image_directory,
        IMAGE_EXTENSIONS,
    )
    annotations, duplicate_annotations = _collect_files(
        config.annotation_directory,
        {ANNOTATION_EXTENSION},
    )
    report.image_count = len(images) + sum(
        len(paths) for paths in duplicate_images.values()
    )
    report.annotation_count = len(annotations) + sum(
        len(paths) for paths in duplicate_annotations.values()
    )

    for key, paths in duplicate_images.items():
        _issue(
            report,
            ValidationSeverity.ERROR,
            "duplicate_image_key",
            f"Multiple images map to the review key '{key}': {paths}",
        )
    for key, paths in duplicate_annotations.items():
        _issue(
            report,
            ValidationSeverity.ERROR,
            "duplicate_annotation_key",
            f"Multiple annotations map to the review key '{key}': {paths}",
        )

    image_keys = set(images)
    annotation_keys = set(annotations)
    for key in sorted(image_keys - annotation_keys):
        _issue(
            report,
            ValidationSeverity.WARNING,
            "annotation_missing",
            f"No annotation found for image key '{key}'.",
            images[key],
        )
    for key in sorted(annotation_keys - image_keys):
        _issue(
            report,
            ValidationSeverity.WARNING,
            "orphan_annotation",
            f"No image found for annotation key '{key}'.",
            annotations[key],
        )

    for key in sorted(image_keys & annotation_keys):
        image_path = images[key]
        annotation_path = annotations[key]
        annotation = _load_annotation(report, annotation_path)
        image_width, image_height = _image_dimensions(report, image_path)
        if annotation is not None:
            _validate_dimensions(
                report,
                annotation,
                annotation_path,
                image_width,
                image_height,
            )
        if annotation is not None and image_width is not None:
            report.pairs.append(
                ReviewPair(
                    relative_key=key,
                    image_path=image_path,
                    annotation_path=annotation_path,
                    image_width=image_width,
                    image_height=image_height,
                )
            )

    if not report.pairs:
        _issue(
            report,
            ValidationSeverity.ERROR,
            "no_review_pairs",
            "No valid image/annotation pairs were found.",
        )
    return report
