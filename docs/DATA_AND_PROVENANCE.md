# Data and provenance

## Run identity and immutability

Every upload receives a random hexadecimal run identifier. Reprocessing creates another identifier and stores the original run in `parent_id`. The original file bytes are copied unchanged into the child run.

The run table records title, project label, status, creation time, metadata JSON, processing configuration, parent, error state and the immutable result checksum. Project labels are descriptive grouping values in version 0.1.0; they are not foreign keys to a separate project registry.

## Result schema

`result.json` uses schema identifier `modavis-scriptor.graphics-run/v1`. It contains:

- normalized image dimensions and original/normalized SHA-256 values;
- region pixel and normalized coordinates;
- raw and alternate OCR strings, word confidences, model and page-segmentation mode;
- rule-based fields for name, literal specification, kind and division;
- clipping and OCR-disagreement flags;
- advisory corpus matches and their evidence rows;
- processing configuration, runtime versions, model hashes, source hashes and corpus checksum.

Coordinates refer to `image.png` after EXIF orientation has been applied. Pixel boxes use `[x1, y1, x2, y2]` from the upper-left origin. Normalized boxes use `[x, y, width, height]`.

## Review events

A review event records:

- run and region identifiers;
- monotonic region version;
- action: `accept`, `retain` or `defer`;
- reviewer label and rationale;
- complete proposed field values;
- optional corpus candidate identifier;
- UTC timestamp.

`accept` materializes the supplied fields. `retain` and `defer` materialize the original parsed OCR fields. Earlier events remain in the event table and research export.

## Corpus evidence

Each displayed evidence row may include `component_id`, `organ_mdvs_id`, `source_record_id`, `source_key`, hashes, original label, pitch label, division label and disclosure/outcome fields. The compact projection stores at most three deterministic evidence rows for each exact name/type group together with the total component count. It is a retrieval index, not an exhaustive replacement for MODAVIS POD.

OrgRec does not provide a direct external URL for every component evidence row. The application therefore exports the dataset DOI and internal identifiers rather than constructing unverified links.

## Research ZIP

The bundle contains, where produced:

```text
original                 uploaded source bytes
image.png                EXIF-normalized derivative
result.json              immutable machine result
reviewed.json            materialized state and complete event history
reviewed.md              complete reviewed working table
raw.md                   complete raw OCR table and strings
table.csv                tabular materialized state
source.json              source, creator and rights metadata
regions.svg              boxes referencing sibling image.png
rNNN-crop.png            evidence crops
rNNN-ocr.png[.tsv]       configured OCR inputs and outputs
rNNN-alt.png[.tsv]       alternate OCR inputs and outputs
source-*.py              executing service source snapshot
```

CSV values beginning with spreadsheet formula characters receive a leading apostrophe. JSON preserves literal values and should be used for character-level analysis.

The SVG references `image.png`; keep both files together. The boxes and labels are separate annotations and do not alter the normalized image.

## Sensitive data

Uploads, source metadata, reviewer labels and rationales remain in the local volume. A research export can contain the same information. Review rights and personal-data requirements before sharing either one.
