"""CPU-only scene-label OCR; independent of the retrieval corpus during recognition."""
import csv
import hashlib
import io
import json
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

VERSION = "modavis-scriptor-ocr-0.1.0"
Image.MAX_IMAGE_PIXELS = 40_000_000


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(source, destination):
    with Image.open(source) as image:
        if image.format not in {"JPEG", "PNG", "WEBP", "TIFF"}:
            raise ValueError("Supported formats: JPEG, PNG, WebP and single-page TIFF.")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Multi-frame images are not supported; export individual images first.")
        if image.width * image.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("Image exceeds 40 megapixels.")
        original = {"format": image.format, "size": list(image.size), "exif_orientation": image.getexif().get(274, 1)}
        oriented = ImageOps.exif_transpose(image)
        if oriented.mode in {"RGBA", "LA", "P"}:
            rgba = oriented.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, "white")
            bg.alpha_composite(rgba)
            oriented = bg
        oriented.convert("RGB").save(destination, "PNG")
    return original


def regions_from_surfaces(image, config):
    height, width = image.shape[:2]
    scale = min(1, 1800 / max(width, height))
    small = cv2.resize(image, (round(width * scale), round(height * scale)))
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    # Light, low-chroma stop faces; not a general organ/object detector.
    mask = cv2.inRange(hsv, np.array([0, 0, config["brightness"]]), np.array([180, config["saturation"], 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    area = small.shape[0] * small.shape[1]
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        fill = cv2.contourArea(contour) / (w * h)
        # Allow a close-up of one face, not only a panel of many small faces.
        if not (config["min_area"] <= w * h / area <= 1 and .35 < w / h < 6 and fill > .42):
            continue
        box = [max(0, int(x / scale)), max(0, int(y / scale)), min(width, int((x + w) / scale)), min(height, int((y + h) / scale))]
        regions.append({"bbox": box, "detector": "light-surface-contour", "fill_ratio": round(fill, 3)})
    return regions


def tesseract(image, path, lang, psm, model="fast"):
    image.save(path)
    command = ["tesseract", str(path), "stdout", "-l", lang, "--oem", "1", "--psm", str(psm),
               "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0", "-c", "tessedit_create_tsv=1"]
    if model == "best":
        command += ["--tessdata-dir", str(Path(__file__).parent / "models/best")]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    Path(str(path) + ".tsv").write_text(completed.stdout)
    words = []
    for row in csv.DictReader(io.StringIO(completed.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = row.get("text", "").strip()
        if not text or float(row["conf"]) < 0:
            continue
        words.append({"text": text, "confidence": float(row["conf"]),
                      "bbox": [int(row[k]) for k in ["left", "top", "width", "height"]],
                      "line": [int(row[k]) for k in ["block_num", "par_num", "line_num"]]})
    lines = {}
    for word in words:
        lines.setdefault(tuple(word["line"]), []).append(word["text"])
    return {"text": "\n".join(" ".join(line) for line in lines.values()), "words": words,
            "mean_confidence": round(sum(w["confidence"] for w in words) / len(words), 2) if words else None,
            "psm": psm, "model": model, "tsv_file": Path(str(path) + ".tsv").name}


def parse_label(text, shape="surface"):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = " ".join(lines)
    spec = ""
    if re.search(r"\b(couplers?|pedal|manual|ruckpositive|rückpositiv)\b", name, re.I):
        return {"name": name, "specification": "", "kind": "division", "division": ""}
    if len(lines) > 1 and re.fullmatch(r"[\dIVXivx\s/.,'′’⅓⅔½\-–]+", lines[-1]):
        name, spec = " ".join(lines[:-1]), lines[-1]
    else:
        match = re.match(r"^(.+?)\s+(\d[\d\s/.,'′’⅓⅔½]*|[IVX]+(?:[-–][IVX]+)?)$", name)
        if match:
            name, spec = match.groups()
    kind = "unknown"
    if spec:
        kind = "stop"
    elif re.search(r"\b(couplers?|pedal|manual|ruckpositive|rückpositiv)\b", name, re.I):
        kind = "division"
    elif re.search(r"\b(swell|great|choir)\b", name, re.I) and len(lines) > 1:
        kind = "coupler"
    return {"name": name, "specification": spec, "kind": kind, "division": ""}


def process_image(folder, config, catalogue):
    started = time.monotonic()
    for script in Path(__file__).parent.glob("*.py"):
        shutil.copyfile(script, folder / ("source-" + script.name))
    image_path = folder / "image.png"
    original = normalize(folder / "original", image_path)
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    array = np.array(image)
    supplied = config.get("regions") or []
    if supplied:
        regions = [{"bbox": [round(b[0] * width), round(b[1] * height), round((b[0] + b[2]) * width), round((b[1] + b[3]) * height)], "detector": "human-supplied-roi"} for b in supplied]
    elif config["mode"] == "organ_stops":
        regions = regions_from_surfaces(array, config)
    else:
        regions = []
    global_ocr = None
    if not supplied and (config["mode"] == "graphics" or not regions):
        global_ocr = tesseract(image, folder / "sparse.png", config["language"], 11, config["model"])
        groups = {}
        for word in global_ocr["words"]:
            groups.setdefault(tuple(word["line"]), []).append(word)
        for words in groups.values():
            x = min(w["bbox"][0] for w in words); y = min(w["bbox"][1] for w in words)
            x2 = max(w["bbox"][0] + w["bbox"][2] for w in words); y2 = max(w["bbox"][1] + w["bbox"][3] for w in words)
            regions.append({"bbox": [max(0,x-8),max(0,y-8),min(width,x2+8),min(height,y2+8)], "detector": "tesseract-sparse-line"})
    if len(regions) > 120:
        raise ValueError("More than 120 regions detected. Increase minimum area or supply regions.")
    regions.sort(key=lambda r: (round((r["bbox"][1]+r["bbox"][3])/2/height/.045), r["bbox"][0]))
    results = []
    for index, region in enumerate(regions):
        region_id = f"r{index+1:03d}"
        x, y, x2, y2 = region["bbox"]
        crop = image.crop((x, y, x2, y2))
        crop.save(folder / f"{region_id}-crop.png")
        # Whiten dark backing outside the low-chroma face, but never alter the evidence crop.
        prepared = crop
        if region["detector"] == "light-surface-contour":
            arr = np.array(crop)
            hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
            face = cv2.inRange(hsv, np.array([0,0,config["brightness"]]), np.array([180,config["saturation"],255]))
            contours, _ = cv2.findContours(face, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                mask = np.zeros(face.shape, np.uint8)
                cv2.drawContours(mask, [max(contours, key=cv2.contourArea)], -1, 255, -1)
                mask = cv2.erode(mask, np.ones((5,5),np.uint8))
                arr[mask == 0] = 255
                prepared = Image.fromarray(arr)
        prepared = ImageOps.autocontrast(ImageOps.grayscale(prepared))
        if config["binarization"] == "fixed":
            prepared = Image.fromarray(cv2.threshold(np.array(prepared), config["ink_threshold"], 255, cv2.THRESH_BINARY)[1])
        elif config["binarization"] == "otsu":
            prepared = Image.fromarray(cv2.threshold(np.array(prepared), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
        prepared = ImageOps.expand(prepared, border=24, fill=255)
        view = tesseract(prepared, folder / f"{region_id}-ocr.png", config["language"], 6, config["model"])
        alternative_model = "fast" if config["model"] == "best" else "best"
        alt = tesseract(prepared, folder / f"{region_id}-alt.png", config["language"], 6, alternative_model)
        # Deterministic baseline: configured model stays authoritative; scores never select a replacement.
        parsed = parse_label(view["text"])
        clipped = x <= 2 or y <= 2 or x2 >= width-2 or y2 >= height-2
        candidates = catalogue.match(parsed["name"], threshold=config["match_threshold"]) if config["mode"] == "organ_stops" else []
        results.append({**region, "id": region_id, "number": index+1, "bbox_normalized": [x/width,y/height,(x2-x)/width,(y2-y)/height],
                        "raw_text": view["text"], "parsed": parsed, "ocr": view, "alternative_ocr": alt,
                        "ocr_disagreement": view["text"] != alt["text"], "clipped": clipped,
                        "candidates": candidates, "crop_sha256": sha256(folder / f"{region_id}-crop.png")})
    models = {"fast/"+p.name: sha256(p) for p in sorted(Path("/usr/share/tesseract-ocr/5/tessdata").glob("*.traineddata"))}
    models.update({"best/"+p.name:sha256(p) for p in sorted((Path(__file__).parent / "models/best").glob("*.traineddata"))})
    return {"schema": "modavis-scriptor.graphics-run/v1", "regions": results,
            "image": {"width": width, "height": height, "original": original, "sha256": sha256(folder / "original"), "normalized_sha256": sha256(image_path),
                      "coordinates": "EXIF-normalized image; top-left origin; bbox [x1,y1,x2,y2] in pixels; normalized [x,y,width,height]; no perspective warp"},
            "paradata": {"pipeline_version": VERSION, "config": config, "processed_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": round(time.monotonic()-started,2),
                         "engine": subprocess.check_output(["tesseract", "--version"], text=True).splitlines()[0],
                         "packages": {p: version(p) for p in ["Pillow", "numpy", "opencv-python-headless", "rapidfuzz", "fastapi"]},
                         "python": platform.python_version(), "platform": platform.platform(), "model_sha256": models,
                         "source_code_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                         "corpus": catalogue.report if config["mode"] == "organ_stops" else None,
                         "catalogue_sha256": sha256(catalogue.path) if config["mode"] == "organ_stops" else None,
                         "policy": "Image evidence first. Corpus advisory only; no automatic replacements. Similarity and OCR scores are not calibrated probabilities. All regions initially unreviewed.",
                         "limitations": ["Light-face heuristic can miss dark, reflective or irregular labels.", "No automatic organ identification or division assignment.", "Pitch/rank strings are not normalized to feet or expanded.", "General graphics mode extracts visible text, not a semantic description of non-text artwork.", "Partially visible controls may be incomplete. Detection coverage requires visual review."]}}
