# Recognition evaluation

The bundled organ photograph informed parameter tuning. It is a development fixture, not independent ground truth. Eight additional rights-documented source images are listed in `evaluation/candidates.json` and can be collected with pinned SHA-256/SHA-1/size verification. They are explicitly **unreviewed candidates**, with two development and six provisional held-out images from disjoint source groups. No human transcriptions or OCR accuracy results are supplied for them.

## Collect, annotate, adjudicate and freeze

Use the managed Python environment from `DEVELOPMENT.md` (Pillow is needed for EXIF-oriented previews):

```bash
npm run evaluation:workflow -- collect
npm run evaluation:workflow -- status
npm run evaluation:workflow -- serve
```

The server prints a free loopback URL. Open it, enter a reviewer identifier and annotate visible target regions by drawing rectangles or entering normalized coordinates. Enter literal text, optional protected terms and the protocol used. Mark unreadable/partial regions as not recognition-evaluable; they still count for detection. A draft save does not complete or certify an annotation. Completion requires explicit human visual-reading attestation and all evaluable text fields.

Repeat the blind pass with a second independent human reviewer. Blind mode fetches only the requested review and never fetches the other reading, OCR or corpus suggestions. In adjudication mode, a distinct third reviewer explicitly loads both completed readings, resolves their differences against the image, and records an overall rationale plus a rationale for each final region. Every submission is a new revision; stale saves return 409 while the browser keeps the draft. A changed reading invalidates an earlier adjudication revision.

Stop the annotation server before freezing a split:

```bash
npm run evaluation:workflow -- freeze --reviewers ReviewerA ReviewerB \
  --adjudicator ReviewerC --split held_out \
  --output evaluation-data/frozen/held-out.json
```

Freezing checks source fixity, completion/attestation, distinct normalized reviewer IDs, current adjudicated revisions, rationales and group separation. It refuses an existing output, incomplete adjudication, altered sources, or a source/catalog mismatch. The gold manifest records annotation digests, reviewer declarations and adjudication provenance. Software records these declarations; it cannot authenticate identities or independently establish that three identifiers represent three people.

The catalog and its SHA anchor a workspace. Use a new workspace/catalog for a changed collection or split rather than reassigning reviewed sources silently. Global options precede the command, for example `npm run evaluation:workflow -- --workspace /private/annotations collect`. `evaluation-data/` is ignored by Git and Docker builds; it contains original downloads and potentially identifying annotation history. Only the public candidate metadata is committed. Preserve source credits/license terms when sharing material. Sources currently include public-domain and CC BY-SA photographs; each item's exact credit, license URL and source page is in the catalog.

No real candidate is automatically annotated, completed, adjudicated or frozen. UI/workflow acceptance uses explicitly synthetic images and reviewer labels in temporary workspaces. The requested deliverable is the usable workflow and an unreviewed set; genuine human annotation is a later research action.

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

Raw OCR CER/WER are micro-averaged across matched recognition-evaluable regions. A gold region with `recognition_evaluable: false` remains a detection target but is excluded from recognition errors/denominators, with the excluded count reported explicitly. This avoids inventing a transcription for unreadable text. CER counts NFC characters including whitespace; WER uses Unicode whitespace-delimited words. Case, accents and historical spelling remain distinct. Missed/spurious regions are excluded from recognition denominators and reported separately, so good CER alone cannot demonstrate good detection. Inspect per-image and stratum results alongside totals.

When materialized `effective` fields exist, protected-term loss counts a term only if it occurs in both the gold and raw OCR and disappears from the joined effective fields. This is a narrow preservation check, not reviewed-transcription CER/WER or correction precision. Human decisions can intentionally alter text; inspect every flagged case against the image. Measure reviewer time, number of edits and false corrections in a separate adjudicated study.

Do not report a general accuracy improvement until the representative dataset, split independence and annotation protocol have been reviewed and the baseline is reproducible. See `ROADMAP.md` for milestone acceptance criteria.
