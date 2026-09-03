# Recognition and review method

## Scope

Version 0.1.0 extracts visible text from raster images. The specialized organ-stop mode detects light label surfaces and retrieves possible names from MODAVIS POD. The general graphics mode locates sparse text without corpus retrieval. Neither mode provides semantic interpretation of non-text drawings, automatic organ identification or automatic division assignment.

## Source normalization

JPEG, PNG, WebP and single-page TIFF are accepted up to 20 MiB and 40 megapixels. EXIF orientation is applied to a separate RGB PNG. The original bytes are retained and hashed independently of that normalized derivative. All region coordinates refer to the normalized image.

## Region detection

For organ-stop images, the longest analysis dimension is limited to 1,800 pixels. A HSV mask selects low-saturation, bright surfaces, followed by morphological closing with a 3 × 3 kernel. The defaults are:

| Parameter | Default |
| --- | ---: |
| Minimum brightness | 135 |
| Maximum saturation | 60 |
| Minimum relative box area | 0.0006 |
| Maximum relative box area | 1.0 |
| Permitted width/height ratio | 0.35–6.0 |
| Minimum contour fill ratio | 0.42 |

The upper area limit permits a close-up containing a single label. These thresholds are an image-processing heuristic, not a trained object detector. Dark, reflective, strongly skewed or irregular labels may be missed or merged.

In general graphics mode, Tesseract sparse-text mode (PSM 11) supplies line regions. User-supplied regions replace automatic detection in either mode. A run may contain no more than 120 regions.

## OCR views

Evidence crops are retained without OCR preprocessing. For detected light surfaces only, dark backing outside the selected contour is replaced by white in the OCR input. The input is converted to autocontrasted grayscale, optionally binarized, and padded by 24 pixels.

The default is a fixed binarization threshold of 150. Grayscale and Otsu binarization are available for comparison. Recognition uses PSM 6 with the selected German/English language order and both the configured and alternate model families (`fast` and `best`). The configured model always supplies the raw reading; a confidence score never selects an automatic replacement.

The `tessdata_best` files are the unchanged upstream English and German models at commit `e12c65a915945e4c28e237a9b52bc4a8f39a0cec`. Both views use Tesseract and therefore do not constitute statistically independent recognizers. Agreement and confidence values are not calibrated correctness probabilities.

The [Tesseract quality guide](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html) describes the role of preprocessing and page segmentation. The [model repository](https://github.com/tesseract-ocr/tessdata_best) documents the recognition files used here.

## Structured field proposal

The parser separates a trailing numeric, fractional or Roman expression from a name when it matches a limited syntax. It does not interpret the expression numerically. Thus `11/3` remains `11/3`; it is not automatically converted to `1 1/3` or a foot pitch. Roman expressions such as `IV-VI` are retained literally and are not treated as foot pitches.

Stop, division and coupler types are heuristic proposals. The division field is initially empty and requires a manual assignment based on the image.

## Corpus retrieval

The corpus projection is derived from the public OrgRec SQLite profile of MODAVIS POD 1.5.0. All 503,980 component rows join to provenance rows. The projection contains 38,103 exact name/type groups and at most the first three deterministic evidence rows per group.

Search keys use Unicode NFC, case folding and whitespace normalization. A trailing pitch/rank may be removed for retrieval only. Diacritics and vowel differences are preserved; there is no synonym list, frequency prior, identity match or automatic pitch match.

RapidFuzz `fuzz.ratio` returns at most five candidates above a configurable threshold, default 65%. Each candidate retains original evidence labels and source identifiers. A candidate is an attestation or alternative, not proof that the image carries that reading.

MODAVIS is a domain corpus assembled from heterogeneous sources, not a same-author corpus. It does not establish the identity of the photographed instrument.

## Authority and review

The source image is the documentary authority. Raw OCR is the unresolved machine default, not a presumed correct transcription. A proposed change to a name, spelling variant, pitch/rank expression, type or division requires explicit acceptance.

Acceptance records complete field values, reviewer label, an image-based rationale and an optional candidate identifier. The candidate selection button changes only an editable draft. A later `retain` or `defer` event restores the original parsed fields in the working output without deleting the earlier event.

A frequent corpus form must not displace a visually plausible rare form. For example, a match for `Scharf` does not make the image reading `Scharff` incorrect. Clipped labels are not completed from corpus context.

## Example and limitations

The bundled photograph produces 21 regions, including three clipped at the bottom edge. Legible outputs include `Scharff / IV-VI`, `Octave / 2`, `Quintadena / 16`, `Gedackt / 8` and `Mixture / V-VI`. Other outputs, including `Waldflite`, `S esquialter`, `Robrflite )` and fractional notation, require review.

The parameters were explored on this photograph. There is no independently annotated gold transcription or representative image benchmark for the release. Region count is not a recall estimate; the example supports functional validation, not a general accuracy claim. An evaluation study should use held-out images, separate detection and recognition errors, and report protected-term false corrections and reviewer effort.
