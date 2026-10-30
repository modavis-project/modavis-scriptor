#!/usr/bin/env python3
"""Read-only fixtures, temporary outputs; execute inside the graphics image."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

script = Path(__file__).resolve()
local_graphics = script.parents[2] / "services/graphics" if len(script.parents) > 2 else Path("/app")
graphics = Path(os.environ.get("SCRIPTOR_GRAPHICS_ROOT", local_graphics if (local_graphics / "pipeline.py").exists() else "/app"))
sys.path.insert(0, str(graphics))

# Importing app creates DATA. Keep even this side effect outside research storage.
with tempfile.TemporaryDirectory(prefix="scriptor-pipeline-") as directory:
    os.environ["GRAPHICS_DATA"] = str(Path(directory) / "data")
    from app import CATALOGUE, Config
    from pipeline import process_image, regions_from_surfaces

    fixture = graphics / "example/processed"
    config = Config().model_dump()
    baseline = json.loads((fixture / "result.json").read_text(encoding="utf-8"))
    regions = regions_from_surfaces(np.array(Image.open(fixture / "image.png")), config)
    assert len(regions) == 21, len(regions)
    assert sorted(r["bbox"] for r in regions) == sorted(r["bbox"] for r in baseline["regions"])

    folder = Path(directory) / "close-up"
    folder.mkdir()
    shutil.copyfile(fixture / "r003-crop.png", folder / "original")
    result = process_image(folder, config, CATALOGUE)
    assert len(result["regions"]) == 1, result["regions"]
    region = result["regions"][0]
    assert region["detector"] == "light-surface-contour"
    assert region["raw_text"] == "Scharff\nIV-VI", region["raw_text"]
    assert region["parsed"]["specification"] == "IV-VI"

print("Passed: 21 unchanged panel boxes; one close-up surface with Scharff / IV-VI.")
