# API

The FastAPI service listens on `http://127.0.0.1:8010`. Interactive OpenAPI documentation is available at `/docs`; the machine-readable schema is `/openapi.json`. The web application proxies the supported routes under `/api/graphics`.

## Endpoints

| Method | Path | Result |
| --- | --- | --- |
| `GET` | `/health` | Readiness and corpus report |
| `GET` | `/runs` | Runs ordered by creation time |
| `POST` | `/runs` | Validate, store and queue an image |
| `GET` | `/runs/{id}` | Run record and materialized result |
| `POST` | `/runs/{id}/rerun` | Child run using new configuration |
| `GET` | `/runs/{id}/image` | Normalized PNG |
| `GET` | `/runs/{id}/regions/{region}/crop` | Unmodified evidence crop |
| `PATCH` | `/runs/{id}/regions/{region}/review` | Append a review decision |
| `GET` | `/runs/{id}/export?format=…` | `json`, `markdown`, `raw-markdown`, `csv` or `bundle` |

## Upload

The multipart request accepts a file of at most 20 MiB and 40 megapixels. TIFF input must contain one frame.

```bash
curl --fail-with-body \
  -F 'file=@register.jpg' \
  -F 'title=Registerstaffel, Spieltisch A' \
  -F 'project=Inventarisierung 2026' \
  -F 'config={"mode":"organ_stops","model":"best","language":"deu+eng"}' \
  -F 'metadata={"creator":"Name","source_url":"https://example.org/source","license":"Rights statement","license_url":"https://example.org/rights","attribution":"Citation text"}' \
  http://127.0.0.1:8010/runs
```

Successful creation returns HTTP 202 and a run identifier. Poll `GET /runs/{id}` until the status is `completed` or `failed`.

## Reprocess

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{"mode":"organ_stops","model":"best","language":"deu+eng","brightness":135,"saturation":60,"binarization":"fixed","ink_threshold":150,"min_area":0.0006,"match_threshold":65,"regions":[[0.10,0.20,0.15,0.08]]}' \
  http://127.0.0.1:8010/runs/RUN_ID/rerun
```

Supplying `regions` disables automatic detection for the new run.

## Review

```bash
curl --fail-with-body -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"action":"accept","reviewer":"AB","rationale":"The final two f characters are independently visible in the crop.","name":"Scharff","specification":"IV-VI","kind":"stop","division":"","candidate_id":null,"expected_version":0}' \
  http://127.0.0.1:8010/runs/RUN_ID/regions/r003/review
```

Reviewer labels require two non-whitespace characters and rationales require twelve. A candidate identifier, when supplied, must belong to the region. Stale `expected_version` values return HTTP 409.

## Errors

Validation failures return HTTP 422. Missing records return 404. Pending artifacts and checksum mismatches return 409. A full queue returns 429. Errors use FastAPI's JSON `detail` field.

Direct API calls do not provide authentication. Bind the service to loopback as supplied, or place a suitably configured gateway in front of it.
