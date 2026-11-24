"""Create nonclinical classic CT/MR stacks with deliberately reversed filenames."""

import argparse
import json
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, MRImageStorage, ExplicitVRLittleEndian, generate_uid


def write_series(directory, modality="CT", slices=6, shape=(72, 96),
                 orientation=(.8, .6, 0, -.6, .8, 0), origin=(10, 20, 30),
                 step=(0, 0, 2.5), spacing=(1.3, .7), photometric="MONOCHROME2"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError(f"Refusing to overwrite a nonempty folder: {directory}")
    series_uid, study_uid, frame_uid = generate_uid(), generate_uid(), generate_uid()
    klass = CTImageStorage if modality == "CT" else MRImageStorage
    paths = []
    for index in range(slices):
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = klass
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        path = directory / f"slice_{slices - index:03}.dcm"
        ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = klass, file_meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study_uid, series_uid, frame_uid
        ds.Modality, ds.SeriesNumber = modality, 1 if modality == "CT" else 2
        ds.SeriesDescription = f"Synthetic {modality} example"
        ds.PatientName, ds.PatientID = "SYNTHETIC^EXAMPLE", "SYNTHETIC_NO_PATIENT"
        ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
        ds.InstanceNumber = slices - index  # intentionally not the spatial order
        ds.Rows, ds.Columns = shape
        ds.ImageOrientationPatient = [f"{x:.10g}" for x in orientation]
        ds.ImagePositionPatient = [f"{x:.10g}" for x in np.asarray(origin) + index * np.asarray(step)]
        ds.PixelSpacing = [str(x) for x in spacing]
        ds.SpacingBetweenSlices = "2.5"
        ds.SliceThickness = "2.5"
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, photometric
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
        ds.RescaleSlope, ds.RescaleIntercept = (2, -1000) if modality == "CT" else (1, 0)
        if modality == "CT":
            ds.RescaleType = "HU"
        pixels = np.zeros(shape, dtype=np.int16)
        h, w = shape
        pixels[h // 6:5 * h // 6, w // 6:5 * w // 6] = 600 + 10 * index
        pixels[h // 3:h // 2, w // 3:w // 2] = 0
        pixels[-3, -3] = 900
        ds.PixelData = pixels.astype("<i2").tobytes()
        ds.save_as(path, enforce_file_format=True)
        paths.append(path)
    return series_uid, tuple(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".manual-test-data-dicom"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for modality in ("CT", "MR"):
        folder = args.output / f"{modality}_series"
        if folder.exists() and any(folder.iterdir()):
            print(f"Kept existing {folder}")
            continue
        uid, _ = write_series(folder, modality=modality)
        manifest[modality] = {"series_uid": uid, "directory": str(folder)}
        print(f"{modality}: {folder.resolve()} | {uid}")
    if manifest:
        path = args.output / "generated_series.json"
        if not path.exists():
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
