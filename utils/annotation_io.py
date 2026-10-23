"""Replace annotation files only after their new contents are fully written."""

import os
from pathlib import Path
import stat
import tempfile


def atomic_write_annotation(filename, contents, repair_readonly=False):
    """Write bytes without copying source permissions or truncating old data.

    Reviewed files made by older versions may have inherited the original's
    read-only bit. Permit repairing that bit for review output only.
    """
    destination = Path(filename)
    temporary = None
    previous_mode = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.name}.",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, destination)
        except PermissionError:
            if not repair_readonly or not destination.is_file():
                raise
            mode = destination.stat().st_mode
            if mode & stat.S_IWRITE:
                raise
            previous_mode = mode
            destination.chmod(mode | stat.S_IWRITE)
            os.replace(temporary, destination)
        temporary = None
    except Exception:
        if previous_mode is not None:
            destination.chmod(previous_mode)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
