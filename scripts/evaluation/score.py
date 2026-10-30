#!/usr/bin/env python3
"""Score independently annotated images against native raw/reviewed run exports.

Gold schema: modavis-scriptor.evaluation/v1; required fields are split
(development or held_out), annotation {reviewer, method}, and items. Each item
has a unique id and source_sha256, rights {license, attribution}, and regions
[{id, bbox_normalized: [x,y,width,height], text, protected_terms?: [string]}].
Boxes refer to the EXIF-normalized image. Each protected term must occur as an
exact NFC substring of its gold text. A split label does not establish dataset
independence: collection, annotation and split governance remain research work.

Results must be native modavis-scriptor.graphics-run/v1 result.json or
reviewed.json exports, exactly one per gold image, matched by image.sha256.
Detection uses deterministic maximum-cardinality IoU matching (default >=0.5),
not greedy matching or a claim of maximum total IoU. CER/WER are micro-averaged
on matched raw_text only: NFC characters including whitespace for CER; Unicode
whitespace-delimited words for WER. No case, spelling or accent normalization.
Missed/spurious regions are reported separately and excluded from CER/WER.
Reviewed effective fields do not reconstruct a full transcription: only optional
protected-term loss is scored there, when a gold term was present in raw_text.
"""
import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import deque
from pathlib import Path

GOLD_SCHEMA = "modavis-scriptor.evaluation/v1"
RUN_SCHEMA = "modavis-scriptor.graphics-run/v1"
FIELDS = ("name", "specification", "kind", "division")


class ValidationError(ValueError):
    """The supplied inputs cannot be scored without ambiguity."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def text(value, location, nonempty=False):
    require(isinstance(value, str), f"{location} must be a string")
    require(not nonempty or bool(value.strip()), f"{location} must not be blank")
    return value


def object_at(value, location):
    require(isinstance(value, dict), f"{location} must be an object")
    return value


def list_at(value, location):
    require(isinstance(value, list), f"{location} must be a list")
    return value


def nfc(value):
    return unicodedata.normalize("NFC", value)


def digest(value, location):
    text(value, location)
    require(re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None,
            f"{location} must be a SHA-256 hex digest")
    return value.lower()


def box(value, location):
    list_at(value, location)
    require(len(value) == 4, f"{location} must contain x, y, width, height")
    require(all(type(v) in (int, float) and (type(v) is int or math.isfinite(v)) for v in value),
            f"{location} values must be finite numbers")
    x, y, width, height = value
    require(0 <= x < 1 and 0 <= y < 1 and 0 < width <= 1 and 0 < height <= 1
            and x + width <= 1 and y + height <= 1,
            f"{location} must be positive and within the normalized image")
    return value


def regions_at(value, location, gold=False):
    regions = list_at(value, location)
    ids = set()
    reviewed = []
    for index, region in enumerate(regions):
        where = f"{location}[{index}]"
        object_at(region, where)
        region_id = text(region.get("id"), f"{where}.id", nonempty=True)
        require(region_id not in ids, f"duplicate region id {region_id!r} in {location}")
        ids.add(region_id)
        box(region.get("bbox_normalized"), f"{where}.bbox_normalized")
        value = text(region.get("text" if gold else "raw_text"), f"{where}.text" if gold else f"{where}.raw_text")
        if gold:
            require(type(region.get("recognition_evaluable", True)) is bool,
                    f"{where}.recognition_evaluable must be boolean")
            terms = list_at(region.get("protected_terms", []), f"{where}.protected_terms")
            seen_terms = set()
            for term in terms:
                term = nfc(text(term, f"{where}.protected_terms entry", nonempty=True))
                require(term not in seen_terms, f"duplicate protected term {term!r} in {where}")
                require(term in nfc(value), f"protected term {term!r} absent from {where}.text")
                seen_terms.add(term)
        else:
            reviewed.append("effective" in region)
            if "effective" in region:
                effective = object_at(region["effective"], f"{where}.effective")
                for field in FIELDS:
                    text(effective.get(field), f"{where}.effective.{field}")
    require(not reviewed or all(reviewed) or not any(reviewed),
            f"{location} mixes raw-only and reviewed regions")
    return regions


def validate_gold(gold):
    object_at(gold, "gold")
    require(gold.get("schema") == GOLD_SCHEMA, f"gold.schema must be {GOLD_SCHEMA}")
    require(gold.get("split") in ("development", "held_out"),
            "gold.split must be development or held_out")
    annotation = object_at(gold.get("annotation"), "gold.annotation")
    for key in ("reviewer", "method"):
        text(annotation.get(key), f"gold.annotation.{key}", nonempty=True)
    items = list_at(gold.get("items"), "gold.items")
    require(bool(items), "gold.items must contain at least one image")
    ids, hashes = set(), set()
    for index, item in enumerate(items):
        where = f"gold.items[{index}]"
        object_at(item, where)
        item_id = text(item.get("id"), f"{where}.id", nonempty=True)
        source = digest(item.get("source_sha256"), f"{where}.source_sha256")
        require(item_id not in ids, f"duplicate gold item id {item_id!r}")
        require(source not in hashes, f"duplicate gold source SHA-256 {source}")
        ids.add(item_id)
        hashes.add(source)
        rights = object_at(item.get("rights"), f"{where}.rights")
        for key in ("license", "attribution"):
            text(rights.get(key), f"{where}.rights.{key}", nonempty=True)
        regions_at(item.get("regions"), f"{where}.regions", gold=True)
    return gold


def validate_results(results, gold):
    list_at(results, "results")
    by_hash, run_ids = {}, set()
    expected = {item["source_sha256"].lower() for item in gold["items"]}
    for index, result in enumerate(results):
        where = f"results[{index}]"
        object_at(result, where)
        require(result.get("schema") == RUN_SCHEMA, f"{where}.schema must be {RUN_SCHEMA}")
        run_id = text(result.get("run_id"), f"{where}.run_id", nonempty=True)
        require(run_id not in run_ids, f"duplicate result run_id {run_id!r}")
        run_ids.add(run_id)
        image = object_at(result.get("image"), f"{where}.image")
        source = digest(image.get("sha256"), f"{where}.image.sha256")
        require(source in expected, f"unexpected result source SHA-256 {source}")
        require(source not in by_hash, f"duplicate result for source SHA-256 {source}")
        regions_at(result.get("regions"), f"{where}.regions")
        by_hash[source] = result
    missing = expected - set(by_hash)
    require(not missing, f"missing results for source SHA-256: {', '.join(sorted(missing))}")
    return by_hash


def iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    union = a[2] * a[3] + b[2] * b[3] - intersection
    return intersection / union if union else 0.0


def match_regions(gold, predicted, threshold=0.5):
    """Bipartite augmenting paths: maximize pair count, with stable tie-breaking."""
    edges = []
    for region in gold:
        candidates = [(index, iou(region["bbox_normalized"], other["bbox_normalized"]))
                      for index, other in enumerate(predicted)]
        edges.append([index for index, overlap in sorted(candidates, key=lambda pair: (-pair[1], predicted[pair[0]]["id"]))
                      if overlap >= threshold])
    left_match, right_match = {}, {}
    for start in sorted(range(len(gold)), key=lambda index: gold[index]["id"]):
        queue, seen_left, parent = deque([start]), {start}, {}
        end = None
        while queue and end is None:
            current = queue.popleft()
            for right in edges[current]:
                if right in parent:
                    continue
                parent[right] = current
                if right not in right_match:
                    end = right
                    break
                owner = right_match[right]
                if owner not in seen_left:
                    seen_left.add(owner)
                    queue.append(owner)
        if end is not None:
            while True:
                left = parent[end]
                previous = left_match.get(left)
                left_match[left], right_match[end] = end, left
                if previous is None:
                    break
                end = previous
    return sorted(left_match.items())


def edit_distance(reference, hypothesis):
    """Unit-cost Levenshtein distance for character or word sequences."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, value in enumerate(reference, 1):
        current = [row]
        for column, other in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (value != other)))
        previous = current
    return previous[-1]


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def raw_metrics(reference, hypothesis):
    reference, hypothesis = nfc(reference), nfc(hypothesis)
    return {"character_errors": edit_distance(reference, hypothesis),
            "reference_characters": len(reference),
            "word_errors": edit_distance(reference.split(), hypothesis.split()),
            "reference_words": len(reference.split())}


def detection_metrics(true_positive, false_positive, false_negative):
    return {"true_positive": true_positive, "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": ratio(true_positive, true_positive + false_positive),
            "recall": ratio(true_positive, true_positive + false_negative),
            "f1": ratio(2 * true_positive, 2 * true_positive + false_positive + false_negative)}


def evaluate(gold, results, threshold=0.5):
    require(type(threshold) in (int, float) and 0 < threshold <= 1 and math.isfinite(threshold),
            "IoU threshold must be a finite number greater than 0 and at most 1")
    validate_gold(gold)
    by_hash = validate_results(results, gold)
    totals = dict(character_errors=0, reference_characters=0, word_errors=0, reference_words=0)
    images, losses = [], []
    tp = fp = fn = eligible = reviewed_matches = reviewed_results = scored_matches = excluded_matches = 0
    for item in gold["items"]:
        source = item["source_sha256"].lower()
        result = by_hash[source]
        expected, predicted = item["regions"], result["regions"]
        pairs = match_regions(expected, predicted, threshold)
        matched_gold, matched_result = {a for a, _ in pairs}, {b for _, b in pairs}
        image_reviewed = "review_events" in result or (bool(predicted) and "effective" in predicted[0])
        reviewed_results += image_reviewed
        image = {"item_id": item["id"], "source_sha256": source, "run_id": result["run_id"],
                 "rights": item["rights"], "matches": [],
                 "false_negatives": [r["id"] for i, r in enumerate(expected) if i not in matched_gold],
                 "false_positives": [r["id"] for i, r in enumerate(predicted) if i not in matched_result]}
        for left, right in pairs:
            target, actual = expected[left], predicted[right]
            evaluable = target.get("recognition_evaluable", True)
            metrics = raw_metrics(target["text"], actual["raw_text"]) if evaluable else None
            if metrics is not None:
                scored_matches += 1
                for key, value in metrics.items():
                    totals[key] += value
            else:
                excluded_matches += 1
            match = {"gold_region_id": target["id"], "result_region_id": actual["id"],
                     "iou": iou(target["bbox_normalized"], actual["bbox_normalized"]), "raw_text": metrics}
            if "effective" in actual and evaluable:
                reviewed_matches += 1
                effective = nfc("\n".join(actual["effective"][field] for field in FIELDS))
                match["effective_fields_protected_terms"] = []
                for term in target.get("protected_terms", []):
                    term = nfc(term)
                    raw_present = term in nfc(actual["raw_text"])
                    effective_present = term in effective
                    lost = raw_present and not effective_present
                    eligible += raw_present
                    match["effective_fields_protected_terms"].append({"term": term, "raw_present": raw_present,
                                                                      "effective_present": effective_present, "lost": lost})
                    if lost:
                        losses.append({"item_id": item["id"], "gold_region_id": target["id"],
                                       "result_region_id": actual["id"], "term": term})
            image["matches"].append(match)
        image["detection"] = detection_metrics(len(pairs), len(image["false_positives"]), len(image["false_negatives"]))
        tp += len(pairs)
        fp += len(image["false_positives"])
        fn += len(image["false_negatives"])
        images.append(image)
    return {"schema": "modavis-scriptor.evaluation-report/v1", "split": gold["split"],
            "annotation": gold["annotation"], "iou_threshold": threshold,
            "matching": "maximum cardinality; descending IoU then region ID for deterministic traversal",
            "detection": detection_metrics(tp, fp, fn),
            "raw_text": {"stage": "matched raw OCR; NFC only; WER uses Unicode whitespace split", "matched_regions": tp,
                         "recognition_evaluable_matches": scored_matches, "recognition_excluded_matches": excluded_matches,
                         **totals, "cer": ratio(totals["character_errors"], totals["reference_characters"]),
                         "wer": ratio(totals["word_errors"], totals["reference_words"])},
            "reviewed_effective_fields": {"stage": "literal NFC substring retention in name/specification/kind/division; no reviewed CER/WER",
                                          "reviewed_results": reviewed_results, "raw_only_results": len(results) - reviewed_results,
                                          "matched_regions_with_effective_fields": reviewed_matches,
                                          "protected_terms_eligible": eligible, "protected_terms_lost": len(losses),
                                          "protected_term_loss_rate": ratio(len(losses), eligible), "losses": losses},
            "images": images}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def read_json(path):
    raw = Path(path).read_bytes()
    def reject_constant(value):
        raise ValidationError(f"non-finite JSON number {value}")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    return value, {"file": Path(path).name, "sha256": hashlib.sha256(raw).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", required=True, type=Path, help="independently annotated evaluation manifest JSON")
    parser.add_argument("--results", required=True, nargs="+", type=Path, help="one raw/reviewed native run export per gold source")
    parser.add_argument("--iou-threshold", type=float, default=0.5, help="minimum detection IoU (default: 0.5)")
    args = parser.parse_args(argv)
    try:
        gold, gold_input = read_json(args.gold)
        results, result_inputs = [], []
        for path in args.results:
            result, info = read_json(path)
            results.append(result)
            result_inputs.append(info)
        report = evaluate(gold, results, args.iou_threshold)
        report["inputs"] = {"gold": gold_input, "results": result_inputs}
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, UnicodeError, RecursionError) as error:
        parser.exit(2, f"Invalid evaluation input: {error}\n")


if __name__ == "__main__":
    main()
