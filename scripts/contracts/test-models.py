#!/usr/bin/env python3
"""Public model semantics and generation checks, without research storage or a server."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/graphics"))
from pydantic import ValidationError
from contracts import Config, GraphicsResult, Review

spec = importlib.util.spec_from_file_location("contract_generator", Path(__file__).with_name("generate.py"))
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class Models(unittest.TestCase):
    def test_manual_regions_reject_nonfinite_outside_and_too_small_values(self):
        for box in ([0, 0, float("nan"), .2], [0, 0, .2], [0, 0, .001, .2], [.9, 0, .2, .2]):
            with self.subTest(box=box), self.assertRaises(ValidationError):
                Config(regions=[box])
        self.assertEqual(Config(regions=[[.1, .1, .2, .2]]).regions, [(.1, .1, .2, .2)])

    def test_review_semantics_remain_image_based_and_explicit(self):
        for payload in ({"reviewer": "  ", "rationale": "long enough rationale", "name": "Scharff"},
                        {"reviewer": "QA", "rationale": " " * 12, "name": "Scharff"},
                        {"reviewer": "QA", "rationale": "long enough rationale", "name": ""}):
            with self.assertRaises(ValidationError):
                Review(action="accept", **payload)
        decision = Review(action="accept", reviewer="QA", rationale="visible spelling checked", kind="not_text")
        self.assertEqual(decision.kind, "not_text")

    def test_actual_frozen_structures_validate_without_losing_provenance(self):
        source = json.loads((ROOT / "services/graphics/example/processed/result.json").read_text())
        for region in source["regions"]:
            region.update(effective=region["parsed"], status="unreviewed", version=0, review=None)
        source.update(markdown="", raw_markdown="", review_events=[], immutable_result_sha256="a" * 64,
                      integrity={"coverage": "frozen-example", "verified_files": {}, "unverified_files": [], "note": "Test transport projection"},
                      future_provenance={"literal": "Scharff"})
        result = GraphicsResult.model_validate(source).model_dump(by_alias=True)
        self.assertEqual(result["regions"][2]["raw_text"], "Scharff\nIV-VI")
        self.assertEqual(result["future_provenance"], {"literal": "Scharff"})
        self.assertEqual(result["schema"], source["schema"])

    def test_generator_fails_closed_on_unsupported_validation_keywords(self):
        with self.assertRaisesRegex(ValueError, "Unsupported schema"):
            generator.validate_schema({"type": "string", "format": "date-time"})
        with self.assertRaisesRegex(ValueError, "Unsupported schema"):
            generator.validate_schema({"type": "object", "properties": {"nested": {"oneOf": []}}})

    def test_generated_file_matches_actual_response_models_and_is_deterministic(self):
        content = generator.generate()
        self.assertEqual(content, generator.generate())
        self.assertEqual(generator.TARGET.read_text(), content, "Run scripts/contracts/generate.py after model changes")
        self.assertIn("export type Config_Input", content)
        self.assertIn("export type Config_Output", content)
        self.assertIn("function isGraphicsResult", content)


if __name__ == "__main__":
    unittest.main()
