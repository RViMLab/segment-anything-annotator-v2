"""Classic regular-grid CT/MR series; no resampling or source-file rewriting."""

from dataclasses import dataclass
from hashlib import sha256
from math import prod
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from utils.medical_volume import NiftiVolume, VolumeError


HEADER_TAGS = (
    "SOPClassUID", "SOPInstanceUID", "StudyInstanceUID", "SeriesInstanceUID",
    "FrameOfReferenceUID", "Modality", "SeriesNumber", "SeriesDescription",
    "Rows", "Columns", "ImagePositionPatient", "ImageOrientationPatient",
    "PixelSpacing", "SpacingBetweenSlices", "NumberOfFrames", "ImageType",
    "SamplesPerPixel", "PhotometricInterpretation", "AnatomicalOrientationType",
    "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation",
    "RescaleSlope", "RescaleIntercept", "RescaleType", "ModalityLUTSequence",
    "RealWorldValueMappingSequence",
)


def _reader():
    try:
        import pydicom
        return pydicom
    except ImportError as error:
        raise VolumeError("DICOM import is optional. In your activated environment run:\n"
                          "python -m pip install -r requirements-dicom.txt") from error


def _inventory(directory):
    """Recognize Part-10 files regardless of extension; ignore normal outputs."""
    records = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        candidate = path.suffix.lower() in (".dcm", ".dicom", ".ima")
        if not candidate:
            with path.open("rb") as stream:
                candidate = stream.read(132)[128:132] == b"DICM"
        if candidate:
            stat = path.stat()
            records.append((path.relative_to(directory).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(records)


@dataclass(frozen=True)
class DicomSeries:
    directory: Path
    uid: str
    files: tuple
    inventory: tuple
    modality: str
    number: str
    description: str

    @property
    def label(self):
        return f"{self.modality} | series {self.number or '?'} | {len(self.files)} slices | {self.description} | {self.uid}"


def discover_dicom_series(directory):
    reader = _reader()
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise VolumeError("Choose a DICOM slice folder.")
    inventory = _inventory(directory)
    groups, headers = {}, {}
    for name, _, _ in inventory:
        path = directory / name
        try:
            ds = reader.dcmread(path, stop_before_pixels=True, specific_tags=HEADER_TAGS)
        except Exception as error:
            raise VolumeError(f"Could not read DICOM header: {name}. Choose an intact series folder.") from error
        if str(ds.get("Modality", "")) not in ("CT", "MR"):
            continue
        uid = str(ds.get("SeriesInstanceUID", ""))
        if not uid:
            raise VolumeError(f"{name}: CT/MR image has no SeriesInstanceUID.")
        groups.setdefault(uid, []).append(path)
        headers.setdefault(uid, ds)
    if not groups:
        raise VolumeError("No CT/MR DICOM series found. This importer reads classic single-frame Part-10 CT/MR files.")
    if inventory != _inventory(directory):
        raise VolumeError("The DICOM folder changed during discovery. Try opening it again.")
    return tuple(DicomSeries(directory, uid, tuple(files), inventory,
                             str(headers[uid].Modality), str(headers[uid].get("SeriesNumber", "")),
                             str(headers[uid].get("SeriesDescription", "")))
                 for uid, files in sorted(groups.items()))


def _vector(ds, name, length):
    value = np.asarray(ds.get(name, []), dtype=float)
    if value.shape != (length,) or not np.isfinite(value).all():
        raise VolumeError(f"DICOM needs a finite {name} with {length} values.")
    return value


def _geometry(series, headers):
    if len(headers) < 2:
        raise VolumeError("Choose a series with at least two spatial slices; single images are not supported yet.")
    first = headers[0]
    try:
        rows, columns = int(first.Rows), int(first.Columns)
    except (AttributeError, TypeError, ValueError) as error:
        raise VolumeError("CT/MR slices need valid Rows and Columns.") from error
    if min(rows, columns) < 1 or len(headers) > 10_000 or prod((rows, columns, len(headers))) > 256_000_000:
        raise VolumeError("DICOM volume exceeds the 256-million-voxel / 10,000-slice limit or has invalid dimensions.")
    orientation = _vector(first, "ImageOrientationPatient", 6)
    u, v = orientation[:3], orientation[3:]
    if (not np.allclose([np.linalg.norm(u), np.linalg.norm(v)], 1, atol=1e-5)
            or abs(np.dot(u, v)) > 1e-5):
        raise VolumeError("DICOM image orientation must contain orthogonal unit direction vectors.")
    normal = np.cross(u, v)
    normal /= np.linalg.norm(normal)
    spacing = _vector(first, "PixelSpacing", 2)
    if np.any(spacing <= 0):
        raise VolumeError("DICOM PixelSpacing must be positive.")
    identities = {name: str(first.get(name, "")) for name in ("StudyInstanceUID", "FrameOfReferenceUID")}
    if not all(identities.values()):
        raise VolumeError("CT/MR series needs StudyInstanceUID and FrameOfReferenceUID.")
    positions, seen = [], set()
    for ds in headers:
        expected_class = "1.2.840.10008.5.1.4.1.1.2" if series.modality == "CT" else "1.2.840.10008.5.1.4.1.1.4"
        image_type = ds.get("ImageType", [])
        if isinstance(image_type, str):
            image_type = [image_type]
        if (str(ds.get("SOPClassUID", "")) != expected_class
                or int(ds.get("NumberOfFrames", 1)) != 1
                or "MOSAIC" in [str(value).upper() for value in image_type]):
            raise VolumeError("Only classic single-frame CT/MR slices are supported; enhanced, multiframe and mosaic images are not.")
        if (str(ds.get("SeriesInstanceUID", "")) != series.uid or str(ds.get("Modality", "")) != series.modality
                or any(str(ds.get(name, "")) != value for name, value in identities.items())):
            raise VolumeError("DICOM series contains mixed scan identities. Choose one consistent acquisition.")
        uid = str(ds.get("SOPInstanceUID", ""))
        if not uid or uid in seen:
            raise VolumeError("DICOM series has missing or duplicate SOP instance identifiers.")
        seen.add(uid)
        if (str(ds.file_meta.get("MediaStorageSOPInstanceUID", "")) != uid
                or str(ds.file_meta.get("MediaStorageSOPClassUID", "")) != expected_class):
            raise VolumeError("DICOM file and image SOP identifiers disagree.")
        if str(ds.get("AnatomicalOrientationType", "BIPED")) != "BIPED":
            raise VolumeError("Only the standard human/BIPED patient coordinate system is supported.")
        if (int(ds.get("Rows", 0)), int(ds.get("Columns", 0))) != (rows, columns):
            raise VolumeError("DICOM slices have different image dimensions.")
        if (not np.allclose(_vector(ds, "ImageOrientationPatient", 6), orientation, rtol=0, atol=1e-5)
                or not np.allclose(_vector(ds, "PixelSpacing", 2), spacing, rtol=1e-5, atol=1e-6)):
            raise VolumeError("DICOM slices have mixed orientations or pixel spacing; resample/split the acquisition first.")
        if (int(ds.get("SamplesPerPixel", 0)) != 1
                or str(ds.get("PhotometricInterpretation", "")) not in ("MONOCHROME1", "MONOCHROME2")
                or ds.PhotometricInterpretation != first.PhotometricInterpretation):
            raise VolumeError("DICOM import requires consistently grayscale MONOCHROME1/2 slices.")
        if "RealWorldValueMappingSequence" in ds:
            raise VolumeError("Real-world value mapping requires a separate importer; this version uses modality rescale/LUT only.")
        if bool("RescaleSlope" in ds) != bool("RescaleIntercept" in ds):
            raise VolumeError("RescaleSlope and RescaleIntercept must be supplied together.")
        if "ModalityLUTSequence" in ds and "RescaleSlope" in ds:
            raise VolumeError("The slice has both a modality LUT and rescale; resolve the ambiguous transform first.")
        if "RescaleSlope" in ds:
            scale = np.asarray([float(ds.RescaleSlope), float(ds.RescaleIntercept)])
            if not np.isfinite(scale).all() or scale[0] == 0:
                raise VolumeError("DICOM modality rescale must be finite with a nonzero slope.")
        elif series.modality == "CT" and "ModalityLUTSequence" not in ds:
            raise VolumeError("CT slices need a modality rescale or LUT; stored values cannot be assumed to be HU.")
        positions.append(_vector(ds, "ImagePositionPatient", 3))
    positions = np.asarray(positions)
    order = np.argsort(positions @ normal, kind="stable")
    positions = positions[order]
    if np.any(np.diff(positions @ normal) <= 1e-5):
        raise VolumeError("DICOM has duplicate spatial positions or mixed time/echo images; split them into separate stacks.")
    # Use the full extent to avoid accumulating the rounding error of just the
    # first two DICOM decimal positions across a large stack.
    step = (positions[-1] - positions[0]) / (len(headers) - 1)
    distance = float(np.dot(step, normal))
    if distance <= 1e-5:
        raise VolumeError("DICOM has duplicate spatial positions or mixed time/echo images; split them into separate stacks.")
    expected = positions[0] + np.arange(len(headers))[:, None] * step
    if not np.allclose(positions, expected, rtol=0, atol=.001):
        raise VolumeError("DICOM positions do not form a regular grid (missing slices, mixed echoes, or irregular spacing).")
    for ds in headers:
        if "SpacingBetweenSlices" in ds and not np.isclose(abs(float(ds.SpacingBetweenSlices)), distance, rtol=1e-4, atol=.01):
            raise VolumeError("Slice positions disagree with SpacingBetweenSlices; check for missing or mixed slices.")
    lps = np.eye(4)
    lps[:3, 0], lps[:3, 1] = u * spacing[1], v * spacing[0]
    lps[:3, 2], lps[:3, 3] = step, positions[0]
    ras = np.diag([-1., -1., 1., 1.]) @ lps
    return (columns, rows, len(headers)), ras, order


class DicomVolume(NiftiVolume):
    format_name = "DICOM"

    def __init__(self, series):
        reader = _reader()
        from pydicom.pixels import apply_modality_lut
        try:
            import nibabel as nib
        except ImportError as error:
            raise VolumeError("Install requirements-dicom.txt in your activated environment.") from error
        if series.inventory != _inventory(series.directory):
            raise VolumeError("The DICOM folder changed after discovery. Open it again.")
        headers = [reader.dcmread(path, stop_before_pixels=True, specific_tags=HEADER_TAGS) for path in series.files]
        shape, affine, order = _geometry(series, headers)
        files = tuple(series.files[int(i)] for i in order)
        headers = [headers[int(i)] for i in order]
        cache = TemporaryDirectory(prefix="annotator-dicom-")
        data = None
        try:
            # Stream directly into one temporary NIfTI backing file. A separate
            # NumPy volume plus NIfTI copy would double peak disk requirements.
            converted = Path(cache.name) / "volume.nii"
            header = nib.Nifti1Header()
            header.set_data_shape(shape)
            header.set_data_dtype(np.float64)
            header.set_slope_inter(1, 0)
            header.set_xyzt_units("mm")
            header.set_zooms(np.linalg.norm(affine[:3, :3], axis=0))
            header.set_sform(affine, code=1)
            try:
                header.set_qform(affine, code=1, strip_shears=False)
            except nib.spatialimages.HeaderDataError:
                header.set_qform(None, code=0)  # tilted grids need the exact sform
            with converted.open("wb") as stream:
                header.write_to(stream)
                stream.truncate(header.get_data_offset() + prod(shape) * 8)
            data = np.memmap(converted, mode="r+", dtype=header.get_data_dtype(),
                             offset=header.get_data_offset(), shape=shape, order="F")
            digest = sha256(series.uid.encode("ascii"))
            for index, path in enumerate(files):
                file_digest = sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        file_digest.update(block)
                digest.update(file_digest.digest())
                ds = reader.dcmread(path, specific_tags=(*HEADER_TAGS, "PixelData"))
                syntax = ds.file_meta.get("TransferSyntaxUID")
                if syntax is None or syntax.is_compressed:
                    raise VolumeError("This first importer requires uncompressed DICOM pixel data. "
                                      "Decompress a copy using your DICOM software; originals were not changed.")
                try:
                    values = np.asarray(apply_modality_lut(ds.pixel_array, ds), dtype=np.float64)
                except Exception as error:
                    raise VolumeError(f"Could not decode slice {index}. Check its pixel encoding and modality transform.") from error
                if values.shape != shape[1::-1] or not np.isfinite(values).all():
                    raise VolumeError("DICOM pixel dimensions or rescaled intensities are invalid.")
                data[:, :, index] = values.T
            data.flush()
            data._mmap.close()
            data = None
            super().__init__(converted)
            self._dicom_cache = cache
            self._dicom_series = series
            self._dicom_sops = tuple(str(ds.SOPInstanceUID) for ds in headers)
            self._dicom_identity = {key: str(headers[0].get(key, ""))
                                    for key in ("StudyInstanceUID", "FrameOfReferenceUID", "PhotometricInterpretation")}
            self.path = series.directory
            self.source_hash = digest.hexdigest()
            self.folder_name = f"DICOM_{sha256(series.uid.encode()).hexdigest()[:8]}_{self.source_hash[:12]}"
            self.display_inverted = str(headers[0].PhotometricInterpretation) == "MONOCHROME1"
            self.check_source()
        except Exception:
            if data is not None:
                data._mmap.close()
            cache.cleanup()
            raise

    @property
    def display_name(self):
        return f"{self._dicom_series.modality} series {self._dicom_series.number or self._dicom_series.uid[-12:]}"

    def check_source(self):
        if not hasattr(self, "_dicom_series"):
            return super().check_source()
        if self._dicom_series.inventory != _inventory(self._dicom_series.directory):
            raise VolumeError("The DICOM source folder changed. Reopen the series before tracking, windowing or export.")

    def metadata(self, index):
        data = super().metadata(index)
        data["source_file"] = "DICOM series"  # do not export the containing folder's potentially identifying name
        data["source_format"] = "DICOM-series"
        first = self._dicom_identity
        data["dicom"] = {
            "modality": self._dicom_series.modality,
            "series_instance_uid": self._dicom_series.uid,
            "study_instance_uid": first["StudyInstanceUID"],
            "frame_of_reference_uid": first["FrameOfReferenceUID"],
            "sop_instance_uid": self._dicom_sops[index],
            "coordinate_mapping": "DICOM LPS to NIfTI RAS: negate patient x and y; pixels are not resampled",
            "intensity_mapping": "per-slice modality LUT or RescaleSlope/Intercept; no embedded VOI/presentation LUT",
            "photometric_interpretation": first["PhotometricInterpretation"],
        }
        return data

    def export_metadata(self):
        data = self.metadata(0)
        data["dicom"]["ordered_sop_instance_uids"] = list(self._dicom_sops)
        return data

    def validate_annotation(self, document, index):
        super().validate_annotation(document, index)
        meta = document["medical_volume"]
        dicom = meta.get("dicom")
        expected = self.metadata(index)["dicom"]
        if (meta.get("source_format") != "DICOM-series" or not isinstance(dicom, dict)
                or any(dicom.get(key) != expected[key] for key in ("series_instance_uid", "sop_instance_uid"))):
            raise VolumeError("Saved annotation does not match the selected DICOM series and slice identities.")

    def close(self):
        super().close()
        if hasattr(self, "_dicom_cache"):
            self._dicom_cache.cleanup()
