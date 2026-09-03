# Citation and rights

## Software

Ukolov, Dominik. 2026. *MODAVIS Scriptor*, version 0.1.0. Zenodo. <https://doi.org/10.5281/zenodo.22284008>.

BibTeX:

```bibtex
@software{ukolov2026modavisscriptor,
  author    = {Ukolov, Dominik},
  title     = {{MODAVIS Scriptor}},
  version   = {0.1.0},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.22284008},
  url       = {https://doi.org/10.5281/zenodo.22284008}
}
```

The DOI is reserved for the release record. It resolves publicly only after the Zenodo draft has been published.

## MODAVIS POD

Ukolov, Dominik. 2026. *MODAVIS Pipe Organ Dataset (POD)*, version 1.5.0. Zenodo. <https://doi.org/10.5281/zenodo.22234059>.

The included retrieval projection derives from the public OrgRec SQLite profile. Cite the dataset when reporting corpus-assisted results. The database arrangement and MODAVIS documentation are CC BY 4.0 where rights apply; underlying facts and third-party sources retain their own status.

## Example photograph

Tucker501. 2020. *Organ-stops.jpg*. Wikimedia Commons, photograph dated 22 February 2020. <https://commons.wikimedia.org/wiki/File:Organ-stops.jpg>. CC BY-SA 4.0, <https://creativecommons.org/licenses/by-sa/4.0/>.

The photograph shows the stop controls of the Brombaugh Opus 35 organ at First Presbyterian Church, Springfield, Illinois, USA. The included derivative applies EXIF orientation normalization and separate OCR annotations; the original JPEG bytes are retained in the research example.

Redistribution of the photograph or an adaptation requires attribution, a license link, identification of changes and compliance with CC BY-SA 4.0. That share-alike condition applies to the photograph adaptations, not automatically to independent source code.

## Recognition models

The English and German `tessdata_best` files come from the Tesseract project at commit `e12c65a915945e4c28e237a9b52bc4a8f39a0cec` and are provided under Apache License 2.0. Their upstream license and source record are stored beside the model files.

## Reporting a processed run

A publication should identify at least:

- MODAVIS Scriptor version and run identifier;
- source identifier and original SHA-256;
- processing configuration and model hashes;
- MODAVIS POD version and projection checksum when corpus retrieval was enabled;
- number of regions, clipped regions and reviewed regions;
- distinction between raw OCR, parsed fields and accepted human decisions;
- reviewer protocol and whether an independent gold transcription exists.

Do not describe corpus similarity or Tesseract confidence as a correctness probability.
