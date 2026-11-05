"""Create disposable synthetic images/annotations for the pending GUI checks."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image, ImageDraw


def create_dataset(destination):
    root = Path(destination).resolve()
    if root.exists():
        raise ValueError(f"Refusing to overwrite an existing folder: {root}")
    root.mkdir(parents=True)
    names = ("images", "original-annotations", "warning-two-annotations", "warning-many-annotations",
             "geometry-annotations", "save-confirmed", "class-review", "warning-review")
    for name in names:
        (root / name).mkdir()
    rectangles = [(90, 90, 510, 435), (210, 195, 330, 315), (450, 240, 690, 450)]
    for index in range(1, 7):
        stem = f"manual_{index:03d}"
        image = Image.new("RGB", (800, 600), "#222733")
        draw = ImageDraw.Draw(image)
        for box, colour in zip(rectangles, ("#567da0", "#8cb6d6", "#b19461")):
            draw.rectangle(box, fill=colour)
        image.save(root / "images" / f"{stem}.png")
        shapes = []
        for box, label, group in zip(rectangles, ("cat", "cat", "dog"), (3, 3, 4)):
            x1, y1, x2, y2 = box
            shapes.append({"label": label, "group_id": group, "shape_type": "polygon",
                           "flags": {}, "description": "",
                           "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]})
        document = {"version": "5.2.0", "imagePath": f"../images/{stem}.png", "imageData": None,
                    "imageWidth": 800, "imageHeight": 600, "flags": {}, "shapes": shapes,
                    "provenance": {"source": "synthetic manual test"}}
        for folder in ("original-annotations", "warning-many-annotations", "geometry-annotations"):
            (root / folder / f"{stem}.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
        if index <= 2:
            (root / "warning-two-annotations" / f"{stem}.json").write_text(
                json.dumps(deepcopy(document), indent=2), encoding="utf-8")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".manual-test-data")
    args = parser.parse_args()
    try:
        print(create_dataset(args.output))
    except ValueError as error:
        parser.error(str(error))
