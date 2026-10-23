"""Serialize editable shape fields while retaining source annotation data."""

from copy import deepcopy


def shape_to_annotation(shape):
    source = getattr(shape, "_annotation_source", None)
    data = deepcopy(shape.other_data)
    points = [[point.x(), point.y()] for point in shape.points]
    if source is not None:
        # Qt edits doubles. Keep original JSON numbers for untouched coordinates
        # (including integers), rather than rewriting them through Qt floats.
        original_points = source["points"]
        if len(points) == len(original_points):
            points = [
                [old if current == float(old) else current
                 for current, old in zip(point, original)]
                for point, original in zip(points, original_points)
            ]
    fields = {
        "label": str(shape.label), "points": points,
        "group_id": shape.group_id, "shape_type": shape.shape_type,
        "flags": deepcopy(shape.flags),
    }
    if source is None:
        data.setdefault("description", "")
        data.update(fields)
    else:
        defaults = {"group_id": None, "shape_type": "polygon", "flags": {}}
        for name, value in fields.items():
            baseline = source.get(name, defaults.get(name))
            if name == "shape_type" and baseline is None:
                baseline = "polygon"
            if name in ("label", "points") or value != baseline:
                data[name] = value
    return data
