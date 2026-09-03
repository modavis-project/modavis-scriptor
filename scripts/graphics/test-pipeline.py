#!/usr/bin/env python3
"""Read-only fixtures, temporary outputs; execute inside the graphics image."""
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from app import CATALOGUE, Config
from pipeline import process_image, regions_from_surfaces

fixture = Path("/app/example/processed")
config = Config().model_dump()
baseline = json.loads((fixture / "result.json").read_text())
regions = regions_from_surfaces(np.array(Image.open(fixture / "image.png")), config)
assert len(regions) == 21, len(regions)
assert sorted(r["bbox"] for r in regions) == sorted(r["bbox"] for r in baseline["regions"])

with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    shutil.copyfile(fixture / "r003-crop.png", folder / "original")
    result = process_image(folder, config, CATALOGUE)
    assert len(result["regions"]) == 1, result["regions"]
    region = result["regions"][0]
    assert region["detector"] == "light-surface-contour"
    assert region["raw_text"] == "Scharff\nIV-VI", region["raw_text"]
    assert region["parsed"]["specification"] == "IV-VI"

print("Passed: 21 unchanged panel boxes; one close-up surface with Scharff / IV-VI.")
