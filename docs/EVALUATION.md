# Recognition evaluation

The bundled organ photograph informed parameter tuning. It is a development fixture, not independent ground truth. No representative held-out benchmark has been collected or scored in this repository. The scoring tool and synthetic unit tests establish how to evaluate a dataset once it exists; they do not establish OCR accuracy.

## Collection and annotation

Collect rights-cleared images with enough variety to test the intended use: organs and typefaces, German/English labels, historical spellings, fractions and Roman ranks, lighting/reflections, clipping, non-text controls and difficult surfaces. Keep sources of the same organ or photographic session in one split. Freeze a development split for tuning and a held-out split before evaluating changes.

Annotate normalized `[x,y,width,height]` boxes on the EXIF-oriented image. Record literal visible text, preserving case, accents, spelling and line breaks. Independent reviewers should inspect the image without OCR/corpus suggestions, adjudicate disagreements and mark unreadable/clipped material according to a written protocol. Record all target regions, including ones the detector misses. Preserve source digests, rights, annotation version, reviewer identity/pseudonym and adjudication history outside any public artifact when sensitive.

## Gold manifest

The scorer accepts JSON with this structure; replace the descriptive placeholders with actual annotations and a source digest:

```json
{
  "schema": "modavis-scriptor.evaluation/v1",
  "split": "held_out",
  "annotation": {
    "reviewer": "reviewer identifier",
    "method": "protocol version and adjudication reference"
  },
  "items": [
    {
      "id": "image identifier",
      "source_sha256": "64 hexadecimal characters for the original source bytes",
      "rights": {
        "license": "license or documented permission",
        "attribution": "source and required credit"
      },
      "regions": [
        {
          "id": "label-001",
          "bbox_normalized": [0.1, 0.2, 0.15, 0.1],
          "text": "literal image transcription",
          "protected_terms": ["literal"]
        }
      ]
    }
  ]
}
```

Use `development` for data inspected during tuning. Setting `split` to `held_out` is a declaration whose independence must be supported by the collection/annotation record. Item IDs and source digests must be unique; region IDs must be unique within each image. Protected terms are optional literal NFC substrings of the gold text, chosen to track meaningful spelling, pitch or rank expressions.

## Scoring

Create one run per gold image with a recorded configuration, then use native `result.json` or materialized `reviewed.json` exports:

```bash
python3 scripts/evaluation/score.py \
  --gold /path/to/gold.json \
  --results /path/to/run-a/result.json /path/to/run-b/reviewed.json \
  > /path/to/report.json
npm run test:evaluation
```

Exactly one result is required for every gold source; unexpected, duplicate or missing results are rejected. Match by original source SHA-256, not by filename. Compare alternative processing configurations in separate invocations. Inputs are read-only, and the report includes input file digests for provenance.

Detection uses deterministic maximum-cardinality matching at IoU >=0.5 by default (`--iou-threshold` changes it). This maximizes the number of valid matches, not the sum of their IoU values. The report gives precision/recall and missed/spurious counts.

Raw OCR CER/WER are micro-averaged across matched regions. CER counts NFC characters including whitespace; WER uses Unicode whitespace-delimited words. Case, accents and historical spelling remain distinct. Missed/spurious regions are excluded from those recognition denominators and reported separately, so good CER alone cannot demonstrate good detection. Inspect per-image and stratum results alongside totals.

When materialized `effective` fields exist, protected-term loss counts a term only if it occurs in both the gold and raw OCR and disappears from the joined effective fields. This is a narrow preservation check, not reviewed-transcription CER/WER or correction precision. Human decisions can intentionally alter text; inspect every flagged case against the image. Measure reviewer time, number of edits and false corrections in a separate adjudicated study.

Do not report a general accuracy improvement until the representative dataset, split independence and annotation protocol have been reviewed and the baseline is reproducible. See `ROADMAP.md` for milestone acceptance criteria.
