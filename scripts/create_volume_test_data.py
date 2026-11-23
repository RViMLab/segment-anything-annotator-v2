"""Create nonclinical NIfTI data for the volume GUI checklist."""

from pathlib import Path
import argparse

import nibabel as nib
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".manual-test-data-volume"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = np.full((96, 72, 6), -1000, dtype=np.int16)
    for k in range(data.shape[2]):
        data[12 + k:70 + k, 12:60, k] = 200
        data[30:45, 28:42, k] = -1000
        data[84, 64, k] = 800
    affine = np.array([[-.7, .1, 0, 40], [0, 1.2, .2, -20], [0, 0, 2.5, 5], [0, 0, 0, 1]])
    for name in ("toy_volume.nii.gz", "toy_volume.nii"):
        path = args.output / name
        if path.exists():
            print(f"Kept existing {path}")
            continue
        image = nib.Nifti1Image(data, affine)
        image.set_qform(affine, code=2)
        image.set_sform(affine, code=1)
        image.header.set_xyzt_units("mm")
        nib.save(image, path)
        print(path.resolve())


if __name__ == "__main__":
    main()
