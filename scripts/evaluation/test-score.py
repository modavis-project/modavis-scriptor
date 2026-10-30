#!/usr/bin/env python3
"""Synthetic scoring/validation tests; these fixtures are not an OCR benchmark."""
import copy
import itertools
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from score import GOLD_SCHEMA, RUN_SCHEMA, ValidationError, edit_distance, evaluate, iou, match_regions, raw_metrics, read_json

SHA = "a" * 64


def region(region_id, value="Ö", bbox=None, gold=False):
    return {"id": region_id, "bbox_normalized": bbox or [0, 0, 0.2, 0.2],
            "text" if gold else "raw_text": value}


def gold_manifest(regions=None):
    return {"schema": GOLD_SCHEMA, "split": "held_out",
            "annotation": {"reviewer": "Synthetic test annotator", "method": "Synthetic unit-test data only"},
            "items": [{"id": "synthetic-image", "source_sha256": SHA,
                       "rights": {"license": "CC0-1.0", "attribution": "Synthetic test data"},
                       "regions": regions if regions is not None else [region("g1", gold=True)]}]}


def run_export(regions=None):
    return {"schema": RUN_SCHEMA, "run_id": "synthetic-run", "image": {"sha256": SHA},
            "regions": regions if regions is not None else [region("r1")]}


class MatchingTests(unittest.TestCase):
    def test_augmenting_path_avoids_greedy_undercount(self):
        expected = [region("a", bbox=[0, 0, 0.6, 1]), region("b", bbox=[0, 0, 0.5, 1])]
        actual = [region("r1", bbox=[0, 0, 0.55, 1]), region("r2", bbox=[0.15, 0, 0.6, 1])]
        self.assertGreater(iou(expected[0]["bbox_normalized"], actual[0]["bbox_normalized"]),
                           iou(expected[0]["bbox_normalized"], actual[1]["bbox_normalized"]))
        self.assertEqual(match_regions(expected, actual), [(0, 1), (1, 0)])

    def test_threshold_inclusive_and_no_duplicate_assignments(self):
        expected = [region("a", bbox=[0, 0, 1, 1]), region("b", bbox=[0, 0, 1, 1])]
        actual = [region("r1", bbox=[0, 0, 0.5, 1])]
        self.assertEqual(len(match_regions(expected, actual, 0.5)), 1)
        self.assertEqual(match_regions(expected, actual, 0.5001), [])

    def test_cardinality_matches_exhaustive_small_rectangle_assignments(self):
        rng = random.Random(142)
        for _ in range(40):
            expected = [region(f"g{i}", bbox=[rng.randrange(4) / 10, 0, rng.randrange(3, 7) / 10, 0.5]) for i in range(4)]
            actual = [region(f"r{i}", bbox=[rng.randrange(4) / 10, 0, rng.randrange(3, 7) / 10, 0.5]) for i in range(4)]
            maximum = 0
            for choices in itertools.product(range(-1, 4), repeat=4):
                assigned = [right for right in choices if right >= 0]
                if len(set(assigned)) != len(assigned):
                    continue
                if all(right < 0 or iou(expected[left]["bbox_normalized"], actual[right]["bbox_normalized"]) >= 0.5
                       for left, right in enumerate(choices)):
                    maximum = max(maximum, len(assigned))
            self.assertEqual(len(match_regions(expected, actual)), maximum)


class MetricTests(unittest.TestCase):
    def test_unreadable_regions_count_for_detection_but_not_recognition(self):
        unreadable = region("g1", "", gold=True)
        unreadable["recognition_evaluable"] = False
        report = evaluate(gold_manifest([unreadable]), [run_export()])
        self.assertEqual(report["detection"]["true_positive"], 1)
        self.assertEqual(report["raw_text"]["recognition_excluded_matches"], 1)
        self.assertEqual(report["raw_text"]["recognition_evaluable_matches"], 0)
        self.assertEqual(report["raw_text"]["character_errors"], 0)
        self.assertIsNone(report["raw_text"]["cer"])
        unreadable["recognition_evaluable"] = "false"
        with self.assertRaises(ValidationError):
            evaluate(gold_manifest([unreadable]), [run_export()])

    def test_nfc_only_preserves_case_diacritics_and_character_whitespace(self):
        self.assertEqual(raw_metrics("O\u0308", "Ö")["character_errors"], 0)
        self.assertEqual(raw_metrics("Ö", "ö")["character_errors"], 1)
        self.assertEqual(raw_metrics("Ö", "O")["character_errors"], 1)
        metrics = raw_metrics("Scharff\nIV-VI", "Scharff IV-VI")
        self.assertEqual(metrics["character_errors"], 1)
        self.assertEqual(metrics["word_errors"], 0)
        self.assertEqual(edit_distance("kitten", "sitting"), 3)

    def test_micro_aggregation_and_detection_misses_are_separate(self):
        expected = [region("g1", "aaaa", [0, 0, 0.2, 0.2], True),
                    region("g2", "a", [0.3, 0, 0.2, 0.2], True),
                    region("miss", "not scored", [0.6, 0, 0.2, 0.2], True)]
        actual = [region("r1", "aaab", [0, 0, 0.2, 0.2]),
                  region("r2", "b", [0.3, 0, 0.2, 0.2]),
                  region("extra", "not scored", [0, 0.6, 0.2, 0.2])]
        report = evaluate(gold_manifest(expected), [run_export(actual)])
        self.assertEqual(report["raw_text"]["cer"], 2 / 5)
        self.assertEqual(report["raw_text"]["reference_characters"], 5)
        self.assertEqual(report["raw_text"]["wer"], 1)
        self.assertEqual(report["detection"]["false_positive"], 1)
        self.assertEqual(report["detection"]["false_negative"], 1)
        self.assertEqual(report["images"][0]["false_negatives"], ["miss"])
        self.assertEqual(report["images"][0]["false_positives"], ["extra"])

    def test_effective_fields_loss_only_when_gold_and_raw_contain_term(self):
        expected = region("g1", "Scharff\nIV-VI", gold=True)
        expected["protected_terms"] = ["Scharff", "IV-VI"]
        actual = region("r1", "Scharff\nIV")
        actual["effective"] = {"name": "Scharf", "specification": "IV-VI", "kind": "stop", "division": ""}
        report = evaluate(gold_manifest([expected]), [run_export([actual])])
        reviewed = report["reviewed_effective_fields"]
        self.assertEqual(reviewed["protected_terms_eligible"], 1)
        self.assertEqual(reviewed["protected_terms_lost"], 1)
        self.assertEqual(reviewed["losses"][0]["term"], "Scharff")
        self.assertNotIn("cer", reviewed)
        self.assertEqual(report["raw_text"]["character_errors"], 3)

    def test_raw_only_does_not_invent_reviewed_score(self):
        report = evaluate(gold_manifest(), [run_export()])
        self.assertEqual(report["reviewed_effective_fields"]["raw_only_results"], 1)
        self.assertEqual(report["reviewed_effective_fields"]["matched_regions_with_effective_fields"], 0)
        self.assertIsNone(report["reviewed_effective_fields"]["protected_term_loss_rate"])

    def test_empty_gold_text_and_no_detections_have_defined_counts(self):
        report = evaluate(gold_manifest([region("g1", "", gold=True)]), [run_export()])
        self.assertEqual(report["raw_text"]["character_errors"], 1)
        self.assertIsNone(report["raw_text"]["cer"])
        report = evaluate(gold_manifest(), [run_export([])])
        self.assertEqual(report["detection"]["false_negative"], 1)
        self.assertEqual(report["detection"]["recall"], 0)
        self.assertIsNone(report["raw_text"]["cer"])
        self.assertIsNone(report["detection"]["precision"])

    def test_multiple_images_match_source_not_order_or_region_id(self):
        gold = gold_manifest()
        other = copy.deepcopy(gold["items"][0])
        other.update(id="second-image", source_sha256="b" * 64)
        gold["items"].append(other)
        first, second = run_export(), run_export()
        second["run_id"], second["image"]["sha256"] = "second-run", "B" * 64
        report = evaluate(gold, [second, first])
        self.assertEqual([item["run_id"] for item in report["images"]], ["synthetic-run", "second-run"])
        self.assertEqual(report["raw_text"]["matched_regions"], 2)


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, gold=None, results=None):
        with self.assertRaises(ValidationError):
            evaluate(gold if gold is not None else gold_manifest(), results if results is not None else [run_export()])

    def test_invalid_boxes_rejected_in_gold_and_results(self):
        for invalid in ([0, 0, 0, 1], [0.9, 0, 0.2, 1], [0, 0, 1, -1],
                        [0, 0, float("nan"), 1], [0, 0, float("inf"), 1],
                        [False, 0, 1, 1], [0, 0, 10 ** 1000, 1], [0, 0, 1], ["0", 0, 1, 1]):
            with self.subTest(invalid=invalid):
                gold = gold_manifest()
                gold["items"][0]["regions"][0]["bbox_normalized"] = invalid
                self.assert_invalid(gold=gold)
                result = run_export()
                result["regions"][0]["bbox_normalized"] = invalid
                self.assert_invalid(results=[result])

    def test_missing_or_duplicate_results_and_source_mismatch_rejected(self):
        self.assert_invalid(results=[])
        duplicate = run_export()
        duplicate["run_id"] = "different-run"
        self.assert_invalid(results=[run_export(), duplicate])
        wrong = run_export()
        wrong["image"]["sha256"] = "b" * 64
        self.assert_invalid(results=[wrong])

    def test_duplicate_item_hash_id_region_and_run_ids_rejected(self):
        for duplicate_key in ("id", "source_sha256"):
            gold = gold_manifest()
            second = copy.deepcopy(gold["items"][0])
            second["id"] = "second" if duplicate_key != "id" else second["id"]
            second["source_sha256"] = "b" * 64 if duplicate_key != "source_sha256" else second["source_sha256"]
            gold["items"].append(second)
            self.assert_invalid(gold=gold)
        gold = gold_manifest()
        gold["items"][0]["regions"] *= 2
        self.assert_invalid(gold=gold)
        result = run_export()
        result["regions"] *= 2
        self.assert_invalid(results=[result])
        gold = gold_manifest()
        other = copy.deepcopy(gold["items"][0])
        other.update(id="second", source_sha256="b" * 64)
        gold["items"].append(other)
        second = run_export()
        second["image"]["sha256"] = "b" * 64
        self.assert_invalid(gold=gold, results=[run_export(), second])

    def test_annotation_rights_schema_and_hash_required(self):
        mutations = [lambda g: g.update(schema="wrong"), lambda g: g.update(split="test"),
                     lambda g: g["annotation"].update(reviewer=" "), lambda g: g["annotation"].pop("method"),
                     lambda g: g["items"][0].pop("rights"),
                     lambda g: g["items"][0]["rights"].update(license=""),
                     lambda g: g["items"][0].update(source_sha256="not a digest")]
        for mutation in mutations:
            gold = gold_manifest()
            mutation(gold)
            self.assert_invalid(gold=gold)
        result = run_export()
        result["schema"] = "wrong"
        self.assert_invalid(results=[result])

    def test_protected_term_absence_duplicates_and_partial_review_rejected(self):
        for terms in (["absent"], ["Ö", "O\u0308"], [""]):
            gold = gold_manifest()
            gold["items"][0]["regions"][0]["protected_terms"] = terms
            self.assert_invalid(gold=gold)
        result = run_export([region("r1"), region("r2")])
        result["regions"][0]["effective"] = dict(name="Ö", specification="", kind="stop", division="")
        self.assert_invalid(results=[result])
        result = run_export()
        result["regions"][0]["effective"] = dict(name="Ö")
        self.assert_invalid(results=[result])

    def test_invalid_threshold(self):
        for value in (0, -0.1, 1.1, math.nan, math.inf, 10 ** 1000, True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                evaluate(gold_manifest(), [run_export()], value)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            for value in ('{"id": 1, "id": 2}', '{"value": NaN}', '{"value": Infinity}'):
                path.write_text(value)
                with self.assertRaises(ValidationError):
                    read_json(path)

    def test_cli_outputs_input_fixity_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            gold, result = directory / "gold.json", directory / "run.json"
            gold.write_text(json.dumps(gold_manifest()))
            result.write_text(json.dumps(run_export()))
            command = [sys.executable, str(Path(__file__).with_name("score.py")), "--gold", str(gold), "--results", str(result)]
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
            report = json.loads(completed.stdout)
            self.assertEqual(len(report["inputs"]["gold"]["sha256"]), 64)
            self.assertEqual(report["raw_text"]["cer"], 0)
            result.write_text("{}")
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stdout, "")
            self.assertIn("Invalid evaluation input", completed.stderr)


if __name__ == "__main__":
    unittest.main()
