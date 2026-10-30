"""Public API models. OpenAPI is the source for generated browser types/validators."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RegionKind = Literal["stop", "coupler", "division", "accessory", "unknown", "not_text"]
RunStatus = Literal["queued", "running", "completed", "failed"]
ReviewAction = Literal["accept", "retain", "defer"]
Coordinate = Annotated[float, Field(ge=0, le=1)]
NormalizedBox = tuple[Coordinate, Coordinate, Coordinate, Coordinate]


class Config(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, json_schema_serialization_defaults_required=True)
    mode: Literal["graphics", "organ_stops"] = "organ_stops"
    model: Literal["best", "fast"] = "best"
    language: Literal["eng", "deu", "eng+deu", "deu+eng"] = "eng+deu"
    brightness: int = Field(135, ge=60, le=240)
    saturation: int = Field(60, ge=10, le=160)
    binarization: Literal["fixed", "otsu", "none"] = "fixed"
    ink_threshold: int = Field(150, ge=50, le=230)
    min_area: float = Field(.0006, ge=.0001, le=.05)
    match_threshold: int = Field(65, ge=50, le=100)
    regions: list[NormalizedBox] = Field(default_factory=list, max_length=120)

    @model_validator(mode="after")
    def valid_regions(self):
        for box in self.regions:
            if box[2] < .005 or box[3] < .005 or box[0] + box[2] > 1.000001 or box[1] + box[3] > 1.000001:
                raise ValueError("Each region is normalized [x,y,width,height], inside the image, at least 0.005 wide/high.")
        return self


class Review(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    action: ReviewAction
    reviewer: str = Field(min_length=2, max_length=120)
    rationale: str = Field(min_length=12, max_length=2000)
    name: str = Field("", max_length=300)
    specification: str = Field("", max_length=100)
    kind: RegionKind = "unknown"
    division: str = Field("", max_length=100)
    candidate_id: int | None = None
    expected_version: int = Field(0, ge=0)

    @model_validator(mode="after")
    def meaningful(self):
        if len(self.reviewer.strip()) < 2 or len(self.rationale.strip()) < 12:
            raise ValueError("Provide reviewer identity and an image-based rationale (12 characters minimum).")
        if self.action == "accept" and not self.name.strip() and self.kind != "not_text":
            raise ValueError("A reviewed reading cannot be empty unless the region is marked not_text.")
        return self


class OutputModel(BaseModel):
    # Preserve extension/provenance fields when validating existing runs.
    model_config = ConfigDict(extra="allow", allow_inf_nan=False, json_schema_serialization_defaults_required=True)


class Fields(OutputModel):
    name: str
    specification: str
    kind: RegionKind
    division: str


class CandidateEvidence(OutputModel):
    component_id: str
    organ_mdvs_id: str
    component_type: str
    label: str
    division_label: str | None
    pitch_label: str | None
    source_record_id: str
    source_key: str
    evidence_sha256: str
    decision_sha256: str | None = None
    occurrence_count: int | None = None


class Candidate(OutputModel):
    id: int
    name: str
    component_type: str
    search_key: str
    component_rows: int = Field(ge=0)
    evidence: list[CandidateEvidence]
    similarity: float = Field(ge=0, le=1)
    relation: Literal["attestation", "alternative"]
    warning: str


class OCRWord(OutputModel):
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]
    line: tuple[int, int, int]


class OCR(OutputModel):
    text: str
    words: list[OCRWord]
    mean_confidence: float | None
    psm: int
    model: Literal["best", "fast"]
    tsv_file: str


class ReviewEvent(OutputModel):
    id: int
    run_id: str
    region_id: str
    version: int = Field(ge=1)
    payload: Review
    created_at: str


class Region(OutputModel):
    id: str = Field(pattern=r"^r\d+$")
    number: int = Field(ge=1)
    bbox: tuple[int, int, int, int]
    bbox_normalized: NormalizedBox
    detector: str
    raw_text: str
    parsed: Fields
    effective: Fields
    status: Literal["unreviewed", "accept", "retain", "defer"]
    version: int = Field(ge=0)
    clipped: bool
    ocr_disagreement: bool
    ocr: OCR
    alternative_ocr: OCR
    candidates: list[Candidate]
    review: ReviewEvent | None
    crop_sha256: str


class ImageInfo(OutputModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    normalized_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    original: dict[str, Any]
    coordinates: str


class Integrity(OutputModel):
    coverage: Literal["complete", "frozen-example", "legacy-recorded-hashes"]
    verified_files: dict[str, str]
    unverified_files: list[str]
    note: str


class Paradata(OutputModel):
    config: Config
    pipeline_version: str
    processed_at: str
    duration_seconds: float = Field(ge=0)
    engine: str
    packages: dict[str, str]
    python: str
    platform: str
    model_sha256: dict[str, str]
    source_code_sha256: dict[str, str]
    corpus: dict[str, Any] | None
    catalogue_sha256: str | None
    policy: str
    limitations: list[str]


class GraphicsResult(OutputModel):
    schema_: Literal["modavis-scriptor.graphics-run/v1"] = Field(alias="schema")
    run_id: str
    regions: list[Region]
    image: ImageInfo
    metadata: dict[str, str]
    paradata: Paradata
    markdown: str
    raw_markdown: str
    review_events: list[ReviewEvent]
    immutable_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    integrity: Integrity


class RunSummary(OutputModel):
    id: str
    title: str
    project: str
    status: RunStatus
    created_at: str
    parent_id: str | None
    error: str | None


class RunRecord(RunSummary):
    config: Config
    metadata: dict[str, str]
    result_sha256: str | None
    source_sha256: str | None


class RunListResponse(OutputModel):
    runs: list[RunSummary]
    corpus: dict[str, Any]


class RunResponse(OutputModel):
    run: RunRecord
    result: GraphicsResult | None


class QueuedRunResponse(OutputModel):
    id: str
    status: Literal["queued"]


class HealthResponse(OutputModel):
    ok: bool
    corpus: dict[str, Any]
    local_only: bool
    database_schema: int
    disposable_test_instance: bool


class ValidationIssue(OutputModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorResponse(OutputModel):
    detail: str | list[ValidationIssue]
