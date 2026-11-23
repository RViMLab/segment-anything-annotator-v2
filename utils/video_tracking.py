"""Optional video tracking backend; importing this module never imports STCN."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import importlib
import sys

import cv2
import numpy as np


class VideoTrackingError(ValueError):
    pass


class DirectionalSliceTracker:
    """Map decreasing native slice indices to increasing backend frame indices.

    A new wrapper/backend is initialized for each direction. Public reference
    indices remain native voxel indices for persistence and UI messages.
    """

    def __init__(self, backend, slices, direction=1):
        if direction not in (-1, 1) or slices < 1:
            raise VideoTrackingError("Choose a valid slice direction and volume.")
        self.backend, self.slices, self.direction = backend, int(slices), int(direction)

    def _index(self, index):
        if not 0 <= index < self.slices:
            raise VideoTrackingError("Slice index is outside this volume.")
        return int(index) if self.direction == 1 else self.slices - 1 - int(index)

    @property
    def reference_index(self):
        value = self.backend.reference_index
        return None if value is None else self._index(value)

    @property
    def reference_indices(self):
        return [self._index(i) for i in getattr(self.backend, "reference_indices", [self.backend.reference_index])]

    def start(self, image, masks, index):
        return self.backend.start(image, masks, self._index(index))

    def correct(self, image, masks, index):
        callback = getattr(self.backend, "correct", self.backend.start)
        return callback(image, masks, self._index(index))

    def predict(self, image, index):
        mapped = self._index(index)
        if mapped <= self.backend.reference_index:
            raise VideoTrackingError("Choose a slice beyond the reference in the selected direction, "
                                     "or Stop tracking and initialize a new reference/direction.")
        return self.backend.predict(image, mapped)

    def commit_prediction(self):
        callback = getattr(self.backend, "commit_prediction", None)
        if callback:
            callback()

    def discard_prediction(self):
        callback = getattr(self.backend, "discard_prediction", None)
        if callback:
            callback()


@dataclass(frozen=True)
class VideoSequence:
    name: str
    directory: Path
    frames: tuple


def discover_sequences(directory):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise VideoTrackingError("Choose a directory containing extracted video frames.")

    def frames(folder):
        found = tuple(sorted((p for p in folder.iterdir()
                              if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}),
                             key=lambda p: p.name.casefold()))
        keys = [p.stem.casefold() for p in found]
        if len(keys) != len(set(keys)):
            raise VideoTrackingError(f"{folder.name}: frame names would overwrite the same JSON. Rename duplicates.")
        return found

    direct = frames(root)
    if direct:
        return (VideoSequence(root.name, root, direct),)
    sequences = []
    for child in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        images = frames(child)
        if images:
            sequences.append(VideoSequence(child.name, child, images))
    if not sequences:
        raise VideoTrackingError("No JPG, JPEG, or PNG frame sequences were found.")
    if len({s.name.casefold() for s in sequences}) != len(sequences):
        raise VideoTrackingError("Sequence names must be unique, including letter case.")
    return tuple(sequences)


class TrackingBackend(Protocol):
    """UI-independent interface for STCN and future evaluated alternatives."""

    def start(self, image_path, masks, frame_index): ...
    def correct(self, image_path, masks, frame_index): ...
    def predict(self, image_path, frame_index): ...
    def commit_prediction(self): ...
    def discard_prediction(self): ...


class StcnTracker:
    def __init__(self, app_directory, max_size=600, device="cpu"):
        root = Path(app_directory)
        code, weights = root / "STCN", root / "stcn.pth"
        if not (code / "model" / "eval_network.py").is_file() or not weights.is_file():
            raise VideoTrackingError(
                "STCN is optional and is not ready. Clone hkchengrex/STCN into the app's STCN folder "
                "and place its stcn.pth checkpoint beside annotator.py. See README → Video annotation."
            )
        if int(max_size) < 32:
            raise VideoTrackingError("STCN maximum size must be at least 32 pixels.")
        import torch
        from torchvision import transforms
        if str(code.resolve()) not in sys.path:
            sys.path.insert(0, str(code.resolve()))
        network = importlib.import_module("model.eval_network").STCN
        self.bank_type = importlib.import_module("inference_memory_bank").MemoryBank
        tensor_utils = importlib.import_module("util.tensor_util")
        self.pad = tensor_utils.pad_divide_by
        self.unpad = tensor_utils.unpad
        self.torch, self.device, self.max_size = torch, device, int(max_size)
        self.transform = transforms.Compose([
            transforms.ToTensor(), transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
        self.model = network().to(device).eval()
        state = torch.load(str(weights), map_location=device, weights_only=True)
        key = "value_encoder.conv1.weight"
        if key in state and state[key].shape[1] == 4:
            state[key] = torch.cat([state[key], torch.zeros((64, 1, 7, 7), device=device)], dim=1)
        self.model.load_state_dict(state)
        self.reference_index = None
        self.last_index = None
        self._pending = None

    def _image(self, path):
        from PIL import Image
        image = Image.open(path).convert("RGB")
        width, height = image.size
        factor = min(1.0, self.max_size / max(width, height))
        size = (max(1, int(height * factor)), max(1, int(width * factor)))
        tensor = self.transform(image).unsqueeze(0).to(self.device)
        tensor = self.torch.nn.functional.interpolate(tensor, size=size, mode="bilinear", align_corners=False)
        tensor, padding = self.pad(tensor, 16)
        return tensor, padding, size, (height, width)

    def _encode_reference(self, image_path, masks):
        if not masks or any(not np.any(mask) for mask in masks):
            raise VideoTrackingError("Each selected object needs nonempty polygon pixels.")
        torch = self.torch
        with torch.inference_mode():
            image, padding, size, native = self._image(image_path)
            if any(mask.shape != native for mask in masks):
                raise VideoTrackingError("Reference mask dimensions do not match the frame.")
            mask_tensor = torch.from_numpy(np.stack(masks).astype(np.float32)).unsqueeze(1).to(self.device)
            mask_tensor = torch.nn.functional.interpolate(mask_tensor, size=size, mode="nearest")
            mask_tensor, _ = self.pad(mask_tensor, 16)
            key, _, features, _, _ = self.model.encode_key(image)
            value = self.model.encode_value(image, features, mask_tensor)
        return key.unsqueeze(2), value

    def _set_references(self, references, frame_index, objects):
        bank = self.bank_type(k=objects, top_k=min(20, sum(k.shape[-2] * k.shape[-1] for _, k, _ in references)))
        for _, key, value in references:
            bank.add_memory(key, value)
        # Commit the new reference only after all computations succeed.
        self.bank = bank
        self._references = references
        self.reference_index = int(frame_index)
        self.last_index = int(frame_index)
        self._pending = None

    @property
    def reference_indices(self):
        return [index for index, _, _ in self._references]

    def start(self, image_path, masks, frame_index):
        key, value = self._encode_reference(image_path, masks)
        self._set_references([(int(frame_index), key, value)], frame_index, len(masks))

    def correct(self, image_path, masks, frame_index):
        if len(masks) != self.bank.num_objects:
            raise VideoTrackingError("A correction must include every tracked object.")
        key, value = self._encode_reference(image_path, masks)
        # Keep the initial reference plus four recent corrections. Revising
        # an earlier frame discards future references, avoiding future leakage.
        references = [(i, k, v) for i, k, v in self._references if i < frame_index]
        references.append((int(frame_index), key, value))
        if len(references) > 5:
            references = references[:1] + references[-4:]
        self._set_references(references, frame_index, len(masks))

    def predict(self, image_path, frame_index):
        if self.reference_index is None or frame_index <= self.reference_index:
            raise VideoTrackingError("Choose a frame after the tracking reference, or start tracking from this frame.")
        torch = self.torch
        self._pending = None
        with torch.inference_mode():
            image, padding, _, native = self._image(image_path)
            key, query, features, f8, f4 = self.model.encode_key(image)
            # A jump/backtrack must not retain a temporary reference from a future frame.
            old_temp = self.bank.temp_k, self.bank.temp_v
            try:
                if frame_index != self.last_index + 1:
                    self.bank.temp_k = self.bank.temp_v = None
                masks = self.model.segment_with_query(self.bank, f8, f4, key, query)
                value = self.model.encode_value(image, features, masks)
            finally:
                self.bank.temp_k, self.bank.temp_v = old_temp
            result = self.unpad(masks, padding)
            result = torch.nn.functional.interpolate(result, size=native, mode="bilinear", align_corners=False)
            result = (result[:, 0] > 0.5).cpu().numpy().astype(np.uint8)
            self._pending = (int(frame_index), key.unsqueeze(2).flatten(start_dim=2), value.flatten(start_dim=2))
        return list(result)

    def commit_prediction(self):
        if self._pending is not None:
            self.last_index, self.bank.temp_k, self.bank.temp_v = self._pending
            self._pending = None

    def discard_prediction(self):
        self._pending = None
