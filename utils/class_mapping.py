"""Portable, explicit dataset class definitions; never inferred from row order."""

import json

from utils.annotation_io import atomic_write_annotation


def mapping_from_rows(rows):
    mapping = {}
    for number, (group, label) in enumerate(rows, 1):
        if isinstance(group, bool) or not str(group).isascii() or not str(group).isdigit():
            raise ValueError(f"Row {number}: group ID must be a nonnegative integer.")
        group = int(group)
        if group in mapping:
            raise ValueError(f"Group ID {group} appears more than once.")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Group ID {group}: enter a class name.")
        mapping[group] = label.strip()
    if not mapping:
        raise ValueError("Add at least one group ID and class name.")
    return dict(sorted(mapping.items()))


def load_mapping(filename):
    with open(filename, encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or not isinstance(data.get("classes"), list)):
        raise ValueError("Expected a version 1 class mapping with a classes list.")
    rows = []
    for record in data["classes"]:
        if not isinstance(record, dict) or "group_id" not in record or "label" not in record:
            raise ValueError("Each class needs group_id and label fields.")
        rows.append((record["group_id"], record["label"]))
    return mapping_from_rows(rows)


def save_mapping(filename, mapping):
    mapping = mapping_from_rows(mapping.items())
    data = {"version": 1, "classes": [
        {"group_id": group, "label": label} for group, label in mapping.items()
    ]}
    atomic_write_annotation(filename, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
