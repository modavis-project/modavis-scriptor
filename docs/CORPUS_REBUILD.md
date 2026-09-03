# Rebuilding the retrieval projection

The committed `catalogue.sqlite` is the exact projection used by the bundled example. Rebuilding is optional for normal installation.

## Source

- Dataset: MODAVIS Pipe Organ Dataset 1.5.0
- Record: <https://zenodo.org/records/22234059>
- File: `modavis-pod-1.5-orgrec.sqlite`
- Size: 418,177,024 bytes
- MD5: `4a5f45e397ca0070b9d246a18454435a`
- SHA-256: `dd57394627c91d9fa3f4f3bfd1770c773184345448af80bef63d834de0cbc464`

Download the source into `services/graphics/corpus/`. The original Zenodo metadata snapshot is already included as `zenodo-record.json`. The importer checks the MD5 from that snapshot, calculates SHA-256 and executes SQLite `PRAGMA quick_check` before querying the file.

## Execution

Create an isolated Python environment and install RapidFuzz 3.14.3. Preserve the existing `catalogue.sqlite` and `import-report.json` outside the repository before running:

```bash
python scripts/graphics/import-modavis.py
```

The importer refuses to overwrite an existing `catalogue.sqlite`. It writes a new SQLite projection and `import-report.json` in the corpus directory. The large source database is ignored by Git and excluded from the graphics Docker context.

## Validation

The expected counts are 503,980 provenance-linked component rows and 38,103 exact name/type groups:

| Component type | Rows |
| --- | ---: |
| stop | 425,230 |
| coupler | 46,388 |
| accessory | 32,254 |
| division | 108 |

Evidence rows retain the source component fields and provenance identifiers. Every group stores its total component count and at most three rows, ordered by original label and component identifier.

The report records the importer hash, source hashes, transformation policy, row counts and projection checksum. Its creation timestamp changes on rebuild, so a semantically equivalent rebuild need not have the same database SHA-256. Use the committed projection for byte-identical source data; use row/evidence comparison when validating a new projection.

A projection change must create new OCR/retrieval runs. It must not overwrite a completed run's original candidates or provenance.
