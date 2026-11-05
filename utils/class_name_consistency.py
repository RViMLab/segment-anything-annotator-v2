"""Read-only, cached checks of dataset-local class names and numeric IDs."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re


def numeric_group_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        return int(value.strip())
    return None


def names_by_group(shapes):
    groups = {}
    for shape in shapes:
        group = numeric_group_id(shape.get("group_id"))
        if group is not None and shape.get("points"):
            groups.setdefault(group, set()).add(str(shape.get("label", "")).strip())
    return groups


def image_examples(names):
    names = sorted(set(names))
    shown = ", ".join(names[:3])
    remaining = len(names) - 3
    if remaining > 0:
        shown += f" and {remaining} other image" + ("s" if remaining != 1 else "")
    return shown


@dataclass(frozen=True)
class NameConflict:
    group_id: int
    current_names: tuple
    other_names: tuple  # (name, distinct image filenames)


@dataclass(frozen=True)
class ConsistencyReport:
    conflicts: tuple = ()
    unreadable: tuple = ()
    cancelled: bool = False

    def message(self):
        lines = []
        for conflict in self.conflicts[:5]:
            names = ", ".join(json.dumps(name, ensure_ascii=False) for name in conflict.current_names)
            if len(conflict.current_names) > 1:
                lines.append(f"Group ID {conflict.group_id} has different names in this image: {names}.")
            else:
                lines.append(f"Group ID {conflict.group_id} is named {names} in this image.")
            for name, images in conflict.other_names:
                noun = "image" if len(images) == 1 else "images"
                lines.append(f"It is named {json.dumps(name, ensure_ascii=False)} in {noun} {image_examples(images)}.")
            lines.append("")
        if len(self.conflicts) > 5:
            lines.append(f"There are conflicts for {len(self.conflicts) - 5} other group IDs.")
        if self.unreadable:
            lines.append(f"Could not check {len(self.unreadable)} saved annotation(s): "
                         + image_examples(path for path, _ in self.unreadable) + ".")
        lines.append("Would you like to review the names?")
        return "\n".join(lines)


class ClassNameChecker:
    """Use from a single worker. Cache names, not embedded images or geometry."""

    def __init__(self):
        self.cache = {}

    def check(self, shapes, peers, cancelled=None):
        peers = tuple(peers)
        def paths(annotation):
            return annotation if isinstance(annotation, (tuple, list)) else (annotation,)

        active_paths = {Path(path) for _, annotation in peers for path in paths(annotation)}
        self.cache = {path: value for path, value in self.cache.items() if path in active_paths}
        current = names_by_group(shapes)
        if not current:
            return ConsistencyReport()
        # Same-image conflicts still matter even if the dataset has one image.
        others, unreadable = {}, []
        for image_name, annotation in peers:
            if cancelled is not None and cancelled.is_set():
                return ConsistencyReport(cancelled=True)
            path = Path(paths(annotation)[0])
            try:
                stat = None
                for candidate in paths(annotation):
                    path = Path(candidate)
                    try:
                        stat = path.stat()
                        break
                    except FileNotFoundError:
                        continue
                if stat is None:
                    continue  # A frame may not have been annotated yet.
                signature = (stat.st_mtime_ns, stat.st_size)
                cached = self.cache.get(path)
                if cached is None or cached[0] != signature:
                    with path.open(encoding="utf-8") as stream:
                        document = json.load(stream)
                    if not isinstance(document, dict) or not isinstance(document.get("shapes"), list):
                        raise ValueError("Missing annotation shapes list")
                    cached = (signature, names_by_group(document["shapes"]))
                    self.cache[path] = cached
                for group, names in cached[1].items():
                    if group in current:
                        for name in names:
                            others.setdefault(group, {}).setdefault(name, set()).add(image_name)
            except (OSError, ValueError, TypeError, AttributeError) as error:
                unreadable.append((str(path), str(error)))
        conflicts = []
        for group, names in sorted(current.items()):
            peer_names = others.get(group, {})
            if len(names | peer_names.keys()) > 1:
                different = tuple((name, tuple(sorted(images))) for name, images in sorted(peer_names.items())
                                  if names != {name})
                conflicts.append(NameConflict(group, tuple(sorted(names)), different))
        return ConsistencyReport(tuple(conflicts), tuple(unreadable))
