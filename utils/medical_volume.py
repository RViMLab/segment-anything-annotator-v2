"""Optional native-grid NIfTI reading, display slices, and labelled export."""

from hashlib import sha256
import gzip
import json
from math import prod
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw

from utils.class_name_consistency import numeric_group_id


class VolumeError(ValueError):
    pass


class NiftiVolume:
    """Never resample/reorient the source; displayed (x,y) maps to voxel (x,y,k)."""

    format_name = "NIfTI"

    @property
    def display_name(self):
        return self.path.name

    def __init__(self, filename):
        try:
            import nibabel as nib
        except ImportError as error:
            raise VolumeError("NIfTI support is optional. In your activated environment run:\n"
                              "python -m pip install -r requirements-volume.txt") from error
        self.nib = nib
        self.path = Path(filename).resolve()
        self.source_stat = self._signature()
        if not self.path.name.lower().endswith((".nii", ".nii.gz")):
            raise VolumeError("Choose a scalar 3D NIfTI file (.nii or .nii.gz).")
        self.image = nib.load(str(self.path))
        self.shape = tuple(self.image.shape)
        dtype = self.image.get_data_dtype()
        if (len(self.shape) != 3 or any(n < 1 for n in self.shape)
                or dtype.fields or not np.issubdtype(dtype, np.number) or np.issubdtype(dtype, np.complexfloating)):
            raise VolumeError("Only scalar 3D NIfTI volumes are supported; 4D, vector and complex data are not.")
        if prod(self.shape) > 256_000_000 or self.shape[2] > 10_000:
            raise VolumeError("This first volume implementation supports at most 256 million voxels and 10,000 slices.")
        if (not np.isfinite(self.image.affine).all()
                or abs(np.linalg.det(self.image.affine[:3, :3])) < 1e-15):
            raise VolumeError("The volume needs a finite, invertible spatial affine.")
        digest = sha256()
        with self.path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        self.source_hash = digest.hexdigest()
        stem = self.path.name[:-7] if self.path.name.lower().endswith(".nii.gz") else self.path.name[:-4]
        self.folder_name = f"{stem}_{self.source_hash[:12]}"
        self.axis_codes = tuple(nib.aff2axcodes(self.image.affine))
        self.cache = None
        self.source_cache = None
        if self.path.name.lower().endswith(".gz"):
            # Decompress once to a memory-mapped native file. Repeated proxy
            # slicing of gzip without indexed_gzip would repeatedly decompress
            # earlier slices and become very slow on ordinary clinical scans.
            self.source_cache = TemporaryDirectory(prefix="annotator-nifti-source-")
            unpacked = Path(self.source_cache.name) / "source.nii"
            limit = prod(self.shape) * dtype.itemsize + int(self.image.dataobj.offset) + 1024
            total = 0
            with gzip.open(self.path, "rb") as reader, unpacked.open("wb") as writer:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    total += len(block)
                    if total > limit:
                        raise VolumeError("Compressed NIfTI payload exceeds its declared image size.")
                    writer.write(block)
            self.image = nib.load(str(unpacked))
        low, high = np.inf, -np.inf
        # Read through the proxy one slice at a time, including NIfTI scaling.
        # This also catches truncated/corrupt data before replacing GUI state.
        for index in range(self.shape[2]):
            values = self.slice(index)
            finite = values[np.isfinite(values)]
            if finite.size:
                low, high = min(low, float(finite.min())), max(high, float(finite.max()))
        if not np.isfinite([low, high]).all():
            raise VolumeError("The volume contains no finite intensity values.")
        if high <= low:
            high = low + max(1.0, abs(low) * 1e-6)
        self.low, self.high = low, high
        self.check_source()

    def _signature(self):
        stat = self.path.stat()
        return stat.st_size, stat.st_mtime_ns

    def check_source(self):
        if self._signature() != self.source_stat:
            raise VolumeError("The source scan changed on disk. Reopen it before applying a window or exporting.")

    def slice(self, index):
        # The proxy is memory mapped, including the temporary decompressed copy.
        return np.asarray(self.image.dataobj[:, :, index], dtype=np.float64)

    def render(self, low=None, high=None):
        self.check_source()
        low = self.low if low is None else float(low)
        high = self.high if high is None else float(high)
        if not np.isfinite([low, high, high - low]).all() or high <= low:
            raise VolumeError("Window width must be positive and finite.")
        cache = TemporaryDirectory(prefix="annotator-nifti-")
        try:
            paths = []
            for index in range(self.shape[2]):
                values = np.nan_to_num(self.slice(index), nan=low, posinf=high, neginf=low)
                display = np.rint(np.clip((values - low) / (high - low), 0, 1) * 255).astype(np.uint8)
                if getattr(self, "display_inverted", False):
                    display = 255 - display
                path = Path(cache.name) / f"slice_{index:05}.png"
                Image.fromarray(display.T).save(path)
                paths.append(str(path))
            self.check_source()
            return cache, paths, low, high
        except Exception:
            cache.cleanup()
            raise

    def use_render(self, rendered):
        old = self.cache
        self.cache, self.paths, self.low, self.high = rendered
        if old is not None:
            old.cleanup()

    def close(self):
        if self.cache is not None:
            self.cache.cleanup()
            self.cache = None
        if self.source_cache is not None:
            self.source_cache.cleanup()
            self.source_cache = None

    def metadata(self, index):
        return {
            "version": 1, "source_file": self.path.name, "source_sha256": self.source_hash,
            "voxel_shape": list(self.shape), "affine": self.image.affine.tolist(),
            "slice_axis": 2, "slice_index": int(index),
            "pixel_to_voxel": "(x,y) -> (x,y,slice_index); native axis order, no resampling",
            "display_range": [self.low, self.high],
        }

    def validate_annotation(self, document, index):
        if not isinstance(document, dict):
            raise VolumeError(f"slice_{index:05}.json must contain an annotation document.")
        meta = document.get("medical_volume")
        expected = self.metadata(index)
        keys = ("version", "source_sha256", "voxel_shape", "affine", "slice_axis", "slice_index", "pixel_to_voxel")
        if not isinstance(meta, dict) or any(meta.get(k) != expected[k] for k in keys):
            raise VolumeError(f"slice_{index:05}.json does not match this volume's source and voxel mapping.")
        if (document.get("imageWidth"), document.get("imageHeight")) != self.shape[:2]:
            raise VolumeError(f"slice_{index:05}.json has incorrect native image dimensions.")
        if not isinstance(document.get("shapes"), list):
            raise VolumeError(f"slice_{index:05}.json has no valid shapes list.")

    def export_metadata(self):
        return self.metadata(0)

    def export(self, annotation_directory, destination):
        """Publish a new bundle only after mask AND provenance have been written."""
        self.check_source()
        annotations, destination = Path(annotation_directory), Path(destination)
        if not destination.is_dir():
            raise VolumeError("Choose an existing export parent folder.")
        mask = np.zeros(self.shape, dtype=np.uint32)
        classes, annotated, missing, provenance = {}, [], [], {}
        for index in range(self.shape[2]):
            path = annotations / f"slice_{index:05}.json"
            if not path.is_file():
                missing.append(index)
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            self.validate_annotation(document, index)
            annotated.append(index)
            if "volume_tracking" in document:
                provenance[str(index)] = document["volume_tracking"]
            for record in document["shapes"]:
                if not isinstance(record, dict):
                    raise VolumeError(f"{path.name}: invalid annotation record.")
                group = numeric_group_id(record.get("group_id"))
                points = np.asarray(record.get("points", []), dtype=float)
                if (record.get("shape_type", "polygon") not in (None, "polygon")
                        or group is None or not 0 <= group < 2**32 - 1
                        or points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 3
                        or not np.isfinite(points).all() or np.any(points < 0)
                        or np.any(points > np.asarray(self.shape[:2]))
                        or not isinstance(record.get("label"), str)):
                    raise VolumeError(f"{path.name}: export needs valid polygons with nonnegative integer class IDs.")
                region = Image.new("1", self.shape[:2])
                ImageDraw.Draw(region).polygon([tuple(p) for p in points], fill=1)
                mask[:, :, index][np.asarray(region).T] = group + 1
                classes.setdefault(group, set()).add(record["label"])
        if not annotated:
            raise VolumeError("Save at least one annotated (or deliberately empty) slice before exporting.")
        header = self.image.header.copy()
        header.set_data_dtype(np.uint32)
        header.set_slope_inter(1, 0)
        header.set_intent("label")
        header["cal_min"], header["cal_max"] = 0, int(mask.max())
        result = type(self.image)(mask, self.image.affine, header=header)
        result.set_qform(self.image.get_qform(), code=int(self.image.header["qform_code"]))
        result.set_sform(self.image.get_sform(), code=int(self.image.header["sform_code"]))
        mapping = {
            "version": 1, "source": self.export_metadata(), "background_value": 0,
            "value_rule": "mask_value = group_id + 1; class/group IDs in slice JSON are unchanged",
            "classes": [{"mask_value": group + 1, "group_id": group, "labels": sorted(names)}
                        for group, names in sorted(classes.items())],
            "annotated_slices": annotated, "unannotated_slices": missing,
            "slice_tracking_provenance": provenance,
            "unannotated_policy": "zero-filled; these slices have NOT been confirmed as background",
            "overlap_policy": "last polygon in the saved list wins; hidden polygons are included",
        }
        published = destination / f"{self.folder_name}_segmentation_{uuid4().hex[:8]}"
        with TemporaryDirectory(prefix=".annotator-volume-export-", dir=destination) as staging:
            self.nib.save(result, str(Path(staging) / "segmentation.nii.gz"))
            (Path(staging) / "segmentation.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
            self.check_source()
            Path(staging).rename(published)
        return published
