# Install the annotator: Windows, macOS, and Linux

Follow your operating system's steps, then continue with the shared steps below.
Run one command at a time and wait for it to finish. Copy only the commands
inside code blocks. A GitHub account is **not** needed to download this public app.

You need a **64-bit desktop computer**, an internet connection, Git, Python,
and several GB of free disk space for dependencies and model files. A GPU is
optional. These instructions use a separate `.venv` environment for this app.

## 1. Install prerequisites before cloning

### Windows — PowerShell

Open **PowerShell** from the Start menu and install Git and Python 3.11:

```powershell
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.11 -e --source winget
```

Accept the installers' prompts, then **close and reopen PowerShell**. Verify:

```powershell
git --version
py -3.11 --version
```

If `winget` is unavailable, use the [Git installer](https://git-scm.com/install/windows)
and [Python 3.11 installer](https://www.python.org/downloads/release/python-3119/).
Include the Python launcher when installing Python, then reopen PowerShell.

### macOS — Terminal

Open **Terminal**. If Homebrew is not installed, use its
[official installer](https://brew.sh/):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Complete any Command Line Tools installation it requests, and run the **Next
steps** commands printed by the installer so `brew` is available. Then:

```bash
brew install git python@3.11
git --version
python3.11 --version
```

### Linux — Ubuntu 24.04+ or Debian 12+ desktop

Open **Terminal** and install Git, Python, virtual-environment support, and Qt
display libraries:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip libgl1 libegl1 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
git --version
python3 --version
```

For another Linux distribution, install the equivalent packages with its package
manager. This is a desktop GUI; a remote/headless server needs a display setup.

## 2. Download the app and create its environment

Use the same terminal as above. These commands place the app in your home folder.
If you already have a clone, skip cloning and use its existing folder instead.

**Windows PowerShell:**

```powershell
cd $HOME
git clone https://github.com/RViMLab/segment-anything-annotator-v2.git
cd segment-anything-annotator-v2
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, allow scripts for **this terminal only**, then retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

**macOS Terminal:**

```bash
cd ~
git clone https://github.com/RViMLab/segment-anything-annotator-v2.git
cd segment-anything-annotator-v2
python3.11 -m venv .venv
source .venv/bin/activate
```

**Linux Terminal:**

```bash
cd ~
git clone https://github.com/RViMLab/segment-anything-annotator-v2.git
cd segment-anything-annotator-v2
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now start with `(.venv)`. From here on, use `python` and
`python -m pip` inside this environment. Do not use `sudo pip`.

## 3. Install PyTorch and app dependencies

First, on **all systems**:

```bash
python -m pip install --upgrade pip
```

Then choose **one** PyTorch command:

**Windows or Linux, CPU installation:**

```bash
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

**Apple Silicon Mac (M-series):**

```bash
python -m pip install torch torchvision
```

**Intel Mac, legacy compatibility option with Python 3.11:**

```bash
python -m pip install "numpy<2" "torch==2.2.2" "torchvision==0.17.2"
```

Current PyTorch releases no longer publish Intel Mac binaries; this uses an
[older matching pair](https://pytorch.org/get-started/previous-versions/#v222).
This legacy path has not been tested on a Mac by this project's current
maintainer. The [upstream platform discussion](https://github.com/pytorch/pytorch/issues/114602)
explains the limitation.

For an NVIDIA GPU installation, use the matching command from the
[official PyTorch installer](https://pytorch.org/get-started/locally/) **instead
of the CPU command**. The app chooses an available supported device automatically;
there is no manual GPU selector.

Finally, on **all systems**, install the app's dependencies from its folder:

```bash
python -m pip install -r requirements.txt
python -m pip check
```

Stop if installation reports an error. Keep the terminal output when asking
for help. Installation commands are provided for all three systems; current
automated GUI checks have been run on Windows, not fresh macOS/Linux installs.

## 4. Launch the app

With `(.venv)` active and your terminal inside `segment-anything-annotator-v2`:

```bash
python annotator.py --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

The window size is `height,width`. **Load SAM** downloads `vit_b.pth` on first
use (about 375 MB); wait for it to finish. Later runs reuse that file. Manual
polygons do not require loading SAM. Optional STCN video tracking has
[additional setup in the README](README.md#optional-tracking-prerequisites).

## Reopen or update later

Close the app before updating. Open a terminal and return to the app folder:

**Windows:**

```powershell
cd "$HOME\segment-anything-annotator-v2"
.\.venv\Scripts\Activate.ps1
```

**macOS or Linux:**

```bash
cd ~/segment-anything-annotator-v2
source .venv/bin/activate
```

For the latest merged version, run these commands on **any system**:

```bash
git switch master
git pull --ff-only
python -m pip install -r requirements.txt
```

If Git reports local changes or refuses the update, keep your work and ask for
help; do not reset or delete files to force it. Then use the launch command above.

## Optional NIfTI medical volumes

For scalar 3D `.nii` / `.nii.gz` scans, use Python 3.10 or newer and run from the
app folder with your environment active:

```bash
python -m pip install -r requirements-volume.txt
python annotator.py --volume path/to/scan.nii.gz --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

Or launch normally and click **Open Volume**. See the
[volume workflow and export mapping](README.md#nifti-medical-volumes-optional)
before exporting masks. Optional experimental slice propagation also needs the
[STCN prerequisites](README.md#optional-tracking-prerequisites).

For a classic uncompressed CT/MRI DICOM slice folder, install the DICOM reader
instead (it includes the NIfTI reader):

```bash
python -m pip install -r requirements-dicom.txt
python annotator.py --dicom-directory path/to/dicom-folder --app_resolution 1000,1600 --model_type vit_b --keep_input_size True --max_size 720
```

Or click **Open DICOM** and choose a series. See the
[supported DICOM scope and workflow](README.md#dicom-ctmri-folders-optional).

## Quick get started

1. Choose **Image Directory**, then **Save Directory** for your JSON annotations.
2. If you have a category TXT file, load **Category File**, review its proposed
   class/group IDs, and apply the mapping. Save the approved mapping to reuse
   it across sessions. Otherwise, enter labels and IDs when prompted.
3. Click **Load SAM**, select **Box prompt (B)**, draw around the object, choose
   proposal **1**, **2**, or **3**, then **Accept (A)** and confirm its class.
   Alternatively, use **New polygon (N)** to draw manually.
4. Use **Edit polygons (E)** to adjust it, then **Save (S)**. **Page Down** moves
   to the next image; **Page Up** returns; **J** jumps to a frame.
5. For shortcuts or common questions, click **Help (F1)** or press **F1** in
   the annotator. The searchable help window can stay open while you work.
