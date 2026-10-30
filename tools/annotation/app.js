const DEFAULT_PROTOCOL =
  "MODAVIS literal-visible-text protocol v1; independent visual reading, NFC only for scoring.";
const $ = (id) => document.getElementById(id);
const state = {
  items: [],
  item: null,
  reviewer: "",
  current: null,
  selected: null,
  drawing: false,
  drag: null,
  comparison: null,
  comparisonKey: "",
  drafts: new Map(),
  dirty: false,
  loading: 0,
  saving: false,
  view: "fit",
  zoom: 100,
  pan: null,
  suppressClick: false,
};
const SVG = "http://www.w3.org/2000/svg";
const coordinates = ["box-x", "box-y", "box-width", "box-height"].map($);

function message(value) {
  $("message").textContent = value;
}
function error(value) {
  $("error").textContent = value instanceof Error ? value.message : String(value);
  $("error").hidden = false;
}
function clearError() {
  $("error").hidden = true;
  $("error").textContent = "";
}
function action(callback) {
  return () => {
    clearError();
    Promise.resolve().then(callback).catch(error);
  };
}
function selected() {
  return state.current?.regions.find((region) => region.id === state.selected);
}
function draftKey(reviewer = state.reviewer, item = state.item?.id) {
  return JSON.stringify([reviewer, item]);
}
function requireCurrent() {
  if (state.saving) throw new Error("Wait for the current save to finish.");
  if (!state.current) throw new Error("Enter your reviewer ID and open an annotation first.");
}
function changed(resetDeclarations = true) {
  state.dirty = true;
  if (resetDeclarations) {
    $("complete").checked = false;
    $("human-reviewed").checked = false;
    if (state.current) {
      state.current.complete = false;
      state.current.human_reviewed = false;
    }
  }
  renderState();
}
function renderState() {
  $("annotation-state").textContent = state.current
    ? `${state.reviewer} · ${state.item.id} · revision ${state.current.revision}${state.dirty ? " · unsaved local changes" : " · saved state"}`
    : "Enter your reviewer ID and open an image to annotate.";
}
async function request(path, options) {
  const response = await fetch(path, options);
  const body = await response.text();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    throw new Error(`Server returned HTTP ${response.status} without valid JSON.`);
  }
  if (!response.ok) {
    const detail =
      typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    const failure = new Error(
      response.status === 409
        ? `Conflict (409): ${detail} Your local draft is retained. Use “Reload saved” only when ready to discard it.`
        : `HTTP ${response.status}: ${detail}`,
    );
    failure.status = response.status;
    throw failure;
  }
  return data;
}
function safeLink(url, label) {
  if (!url) return null;
  try {
    const target = new URL(url);
    if (!["http:", "https:"].includes(target.protocol)) return null;
    const link = document.createElement("a");
    link.href = target.href;
    link.textContent = label;
    link.target = "_blank";
    link.rel = "noreferrer";
    return link;
  } catch {
    return null;
  }
}
function source(item) {
  const url = new URL(item.image_url, location.href);
  if (url.origin !== location.origin)
    throw new Error("Image evidence must be served by this local annotation server.");
  state.view = "fit";
  state.zoom = 100;
  for (const id of ["view-fit", "view-natural", "view-zoom"]) $(id).disabled = true;
  $("source-image").src = url.href;
  $("source-image").alt = `EXIF-normalized source image ${item.id}`;
  $("image-title").textContent = item.id;
  const rights = item.rights ?? {};
  $("rights").replaceChildren(
    document.createTextNode(
      `${rights.attribution ?? "Attribution not supplied"} · ${rights.license ?? "Rights not supplied"}`,
    ),
  );
  for (const [url, label] of [
    [rights.license_url, "License"],
    [rights.source_url, "Source"],
  ]) {
    const link = safeLink(url, label);
    if (link) $("rights").append(document.createTextNode(" · "), link);
  }
}
function clearComparison() {
  state.comparison = null;
  state.comparisonKey = "";
  $("reading-panels").replaceChildren();
  $("matching").textContent = "";
  $("copy-left").disabled = true;
  $("copy-right").disabled = true;
}
function renderItems() {
  $("items").replaceChildren();
  for (const item of state.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.disabled = state.saving;
    button.textContent = `${item.id} · ${item.split} · group ${item.group_id}`;
    button.title = JSON.stringify(item.strata ?? {});
    button.setAttribute("aria-current", String(item.id === state.item?.id));
    button.addEventListener(
      "click",
      action(() => openItem(item)),
    );
    $("items").append(button);
  }
}
function normalizeAnnotation(value) {
  if (!Number.isInteger(value.revision) || value.revision < 0 || !Array.isArray(value.regions))
    throw new Error("Invalid saved annotation response.");
  for (const region of value.regions) {
    if (
      typeof region.id !== "string" ||
      !validBox(region.bbox_normalized) ||
      typeof region.text !== "string" ||
      !Array.isArray(region.protected_terms) ||
      !region.protected_terms.every((term) => typeof term === "string")
    )
      throw new Error("Invalid saved region data.");
  }
  return {
    ...value,
    protocol: value.protocol || DEFAULT_PROTOCOL,
    human_reviewed: false,
    regions: value.regions.map((region) => ({
      ...region,
      recognition_evaluable: region.recognition_evaluable !== false,
      rationale: region.rationale ?? "",
    })),
  };
}
async function openItem(item, force = false) {
  const reviewer = $("reviewer").value.trim();
  if (state.current)
    state.drafts.set(draftKey(), { annotation: state.current, dirty: state.dirty });
  if (state.saving) throw new Error("Wait for the current save to finish.");
  const sequence = ++state.loading;
  state.item = item;
  state.selected = null;
  state.drag = null;
  state.drawing = false;
  state.current = null;
  state.reviewer = "";
  clearComparison();
  source(item);
  renderItems();
  render();
  if (!reviewer) {
    state.current = null;
    state.reviewer = "";
    render();
    message("Enter a reviewer ID, then choose Open annotation.");
    return;
  }
  const cached = !force && state.drafts.get(draftKey(reviewer, item.id));
  const value =
    cached?.annotation ??
    normalizeAnnotation(
      await request(`/api/annotation?${new URLSearchParams({ reviewer, item: item.id })}`),
    );
  if (sequence !== state.loading) return;
  state.current = value;
  state.reviewer = reviewer;
  state.dirty = Boolean(cached?.dirty);
  state.selected = value.regions[0]?.id ?? null;
  $("protocol").value = value.protocol;
  $("complete").checked = Boolean(value.complete);
  $("human-reviewed").checked = false;
  $("adjudication-rationale").value = value.adjudication?.rationale ?? "";
  if (value.adjudication?.reviewers) {
    $("reviewer-a").value = value.adjudication.reviewers[0] ?? "";
    $("reviewer-b").value = value.adjudication.reviewers[1] ?? "";
  }
  render();
  message(
    cached?.dirty
      ? "Unsaved local draft restored. No server write was made."
      : "Annotation loaded. Other reviewers remain hidden until an explicit adjudication comparison.",
  );
}
function validBox(box) {
  return (
    Array.isArray(box) &&
    box.length === 4 &&
    box.every((value) => Number.isFinite(value) && value >= 0 && value <= 1) &&
    box[2] > 0 &&
    box[3] > 0 &&
    box[0] + box[2] <= 1.000001 &&
    box[1] + box[3] <= 1.000001
  );
}
function point(event) {
  const rect = $("overlay").getBoundingClientRect();
  return [
    Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
  ];
}
function rectangle(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
}
function svgElement(tag, attributes) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}
function overlay(preview) {
  $("overlay").replaceChildren();
  for (const region of state.current?.regions ?? []) {
    const [x, y, width, height] = region.bbox_normalized;
    const rect = svgElement("rect", {
      x: x * 1000,
      y: y * 1000,
      width: width * 1000,
      height: height * 1000,
      class: region.id === state.selected ? "selected" : "",
      tabindex: "0",
      role: "button",
      "aria-label": `Select region ${region.id}`,
    });
    rect.addEventListener("click", () => {
      if (!state.drawing && !state.suppressClick) selectRegion(region.id);
    });
    rect.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectRegion(region.id);
      }
    });
    const label = svgElement("text", { x: x * 1000, y: Math.max(24, y * 1000 - 8) });
    label.textContent = region.id;
    $("overlay").append(rect, label);
  }
  if (preview)
    $("overlay").append(
      svgElement("rect", {
        x: preview[0] * 1000,
        y: preview[1] * 1000,
        width: preview[2] * 1000,
        height: preview[3] * 1000,
        class: "selected",
      }),
    );
}
function selectRegion(id) {
  if (state.saving) return;
  state.selected = id;
  renderRegions();
  renderEditor();
  overlay();
}
function renderRegions() {
  $("regions").replaceChildren();
  $("region-count").textContent = String(state.current?.regions.length ?? 0);
  for (const region of state.current?.regions ?? []) {
    const button = document.createElement("button");
    button.type = "button";
    button.disabled = state.saving;
    button.textContent = `${region.id}: ${region.text.slice(0, 80) || "[no transcription]"}`;
    button.setAttribute("aria-current", String(region.id === state.selected));
    button.addEventListener("click", () => selectRegion(region.id));
    $("regions").append(button);
  }
}
function renderEditor() {
  const region = selected();
  $("region-fields").disabled = !region || state.saving;
  $("selected-heading").textContent = region ? `Region ${region.id}` : "Select or draw a region";
  coordinates.forEach((input, index) => {
    input.value = region ? String(region.bbox_normalized[index]) : "";
    input.setCustomValidity("");
  });
  $("literal-text").value = region?.text ?? "";
  $("protected-terms").value = region?.protected_terms.join("\n") ?? "";
  $("recognition-evaluable").checked = region?.recognition_evaluable !== false;
  $("region-rationale").value = region?.rationale ?? "";
  renderCrop();
}
function render() {
  const active = Boolean(state.current) && !state.saving;
  for (const id of [
    "reviewer",
    "mode",
    "open",
    "reviewer-a",
    "reviewer-b",
    "compare",
    "adjudication-rationale",
  ])
    $(id).disabled = state.saving;
  for (const id of ["protocol", "draw", "add", "save", "reload", "complete", "human-reviewed"])
    $(id).disabled = !active;
  $("draw").setAttribute("aria-pressed", String(state.drawing));
  $("draw").textContent = state.drawing ? "Finish drawing" : "Draw region";
  $("overlay").classList.toggle("drawing", state.drawing);
  renderState();
  renderRegions();
  renderEditor();
  overlay();
}
function addRegion(box) {
  requireCurrent();
  const ids = new Set(state.current.regions.map((region) => region.id));
  let index = 1;
  while (ids.has(`g${String(index).padStart(3, "0")}`)) index++;
  const region = {
    id: `g${String(index).padStart(3, "0")}`,
    bbox_normalized: box,
    text: "",
    protected_terms: [],
    recognition_evaluable: true,
    rationale: "",
  };
  state.current.regions.push(region);
  state.selected = region.id;
  changed();
  render();
  $("literal-text").focus();
}
function deleteRegion() {
  if (!selected()) return;
  const index = state.current.regions.findIndex((region) => region.id === state.selected);
  state.current.regions.splice(index, 1);
  state.selected =
    state.current.regions[Math.min(index, state.current.regions.length - 1)]?.id ?? null;
  changed();
  render();
}
function toggleDrawing() {
  requireCurrent();
  state.drawing = !state.drawing;
  state.drag = null;
  render();
  $("overlay").focus();
}
function updateBox() {
  const region = selected();
  if (!region) return;
  coordinates.forEach((input) => input.setCustomValidity(""));
  const box = coordinates.map((input) => (input.value === "" ? NaN : Number(input.value)));
  if (!validBox(box)) {
    coordinates[0].setCustomValidity("Use a positive rectangle inside the normalized image.");
    $("region-form").reportValidity();
    return;
  }
  region.bbox_normalized = box;
  changed();
  overlay();
  renderCrop();
}
function compareKey() {
  return JSON.stringify([
    state.item?.id,
    $("reviewer-a").value.trim(),
    $("reviewer-b").value.trim(),
  ]);
}
async function compare() {
  requireCurrent();
  if ($("mode").value !== "adjudicate")
    throw new Error("Independent readings are available only in adjudication mode.");
  const a = $("reviewer-a").value.trim(),
    b = $("reviewer-b").value.trim();
  if (!a || !b || a === b || [a, b].includes(state.reviewer))
    throw new Error("Use two distinct original reviewers and a separate adjudicator ID.");
  const key = compareKey();
  const value = await request(
    `/api/compare?${new URLSearchParams({ item: state.item.id, reviewer_a: a, reviewer_b: b })}`,
  );
  if (key !== compareKey() || $("mode").value !== "adjudicate") return;
  state.comparison = value;
  state.comparisonKey = key;
  $("reading-panels").replaceChildren();
  for (const [name, annotation] of [
    [a, value.left],
    [b, value.right],
  ]) {
    const panel = document.createElement("section");
    panel.className = "reading";
    const heading = document.createElement("h3");
    heading.textContent = `Reviewer ${name} · revision ${annotation.revision}`;
    const list = document.createElement("ol");
    for (const region of annotation.regions) {
      const entry = document.createElement("li"),
        id = document.createElement("strong"),
        text = document.createElement("pre"),
        box = document.createElement("code");
      id.textContent = region.id;
      text.textContent = region.text;
      box.textContent = JSON.stringify(region.bbox_normalized);
      entry.append(id, text, box);
      list.append(entry);
    }
    panel.append(heading, list);
    $("reading-panels").append(panel);
  }
  $("matching").textContent =
    `IoU matches: ${value.pairs.map((pair) => `${pair.left_id} ↔ ${pair.right_id} (${Number(pair.iou).toFixed(3)})`).join("; ") || "none"}. Unmatched A: ${value.unmatched_left.join(", ") || "none"}; B: ${value.unmatched_right.join(", ") || "none"}.`;
  $("copy-left").disabled = false;
  $("copy-right").disabled = false;
  message(
    "Independent readings loaded on your explicit request. Resolve each region against the image before completing adjudication.",
  );
}
function copyReading(side) {
  requireCurrent();
  if (!state.comparison || state.comparisonKey !== compareKey())
    throw new Error("Load the current comparison first.");
  state.current.regions = structuredClone(state.comparison[side].regions).map((region) => ({
    ...region,
    rationale: "",
  }));
  state.selected = state.current.regions[0]?.id ?? null;
  changed();
  render();
  message(
    "Reading copied into an editable draft. It has not been certified or saved; enter image-based rationales.",
  );
}
async function save() {
  requireCurrent();
  if (!$("region-form").reportValidity()) return;
  const complete = $("complete").checked,
    human_reviewed = $("human-reviewed").checked;
  const protocol = $("protocol").value;
  if (protocol.trim().length < 12)
    throw new Error("Document the annotation protocol in at least 12 characters.");
  if (complete && !human_reviewed)
    throw new Error("Final completion requires your explicit human-review declaration.");
  for (const region of state.current.regions) {
    if (!validBox(region.bbox_normalized)) throw new Error(`Invalid coordinates for ${region.id}.`);
    if (complete && region.recognition_evaluable && !region.text.trim())
      throw new Error(
        `Enter literal text for ${region.id}, or mark its recognition truth as not evaluable.`,
      );
    if (
      region.protected_terms.some(
        (term) => !term.trim() || !region.text.normalize("NFC").includes(term.normalize("NFC")),
      )
    )
      throw new Error(`Protected terms for ${region.id} must occur literally in its text.`);
  }
  const payload = {
    item_id: state.item.id,
    reviewer: state.reviewer,
    expected_revision: state.current.revision,
    complete,
    human_reviewed,
    protocol,
    regions: state.current.regions,
  };
  if ($("mode").value === "adjudicate") {
    const a = $("reviewer-a").value.trim(),
      b = $("reviewer-b").value.trim(),
      rationale = $("adjudication-rationale").value;
    if (!a || !b || a === b || [a, b].includes(state.reviewer))
      throw new Error("The adjudicator must differ from both original reviewers.");
    if (complete && (!state.comparison || state.comparisonKey !== compareKey()))
      throw new Error(
        "Load and inspect the current independent readings before final adjudication.",
      );
    if (
      complete &&
      (rationale.trim().length < 32 ||
        state.current.regions.some((region) => region.rationale.trim().length < 12))
    )
      throw new Error(
        "Final adjudication needs an overall rationale of at least 32 characters and at least 12 characters for every region.",
      );
    payload.adjudication = { reviewers: [a, b], rationale };
  }
  const key = draftKey();
  state.saving = true;
  renderItems();
  render();
  try {
    const saved = normalizeAnnotation(
      await request("/api/annotation", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Scriptor-Annotation": "1" },
        body: JSON.stringify(payload),
      }),
    );
    state.drafts.set(key, { annotation: saved, dirty: false });
    if (key !== draftKey()) return;
    state.current = saved;
    state.dirty = false;
    $("complete").checked = Boolean(saved.complete);
    $("human-reviewed").checked = false;
    render();
    message(
      `Saved revision ${saved.revision}${saved.complete ? " with your explicit completion declaration" : " as an incomplete draft"}. No gold release was frozen.`,
    );
  } finally {
    state.saving = false;
    renderItems();
    render();
  }
}

$("open").addEventListener(
  "click",
  action(() => {
    if (!state.item) throw new Error("No source images are available.");
    return openItem(state.item);
  }),
);
$("reload").addEventListener(
  "click",
  action(() => openItem(state.item, true)),
);
$("save").addEventListener("click", action(save));
$("draw").addEventListener("click", action(toggleDrawing));
$("add").addEventListener(
  "click",
  action(() => addRegion([0.25, 0.25, 0.3, 0.15])),
);
$("delete").addEventListener("click", deleteRegion);
$("compare").addEventListener("click", action(compare));
$("copy-left").addEventListener(
  "click",
  action(() => copyReading("left")),
);
$("copy-right").addEventListener(
  "click",
  action(() => copyReading("right")),
);
$("mode").addEventListener("change", () => {
  $("comparison").hidden = $("mode").value !== "adjudicate";
  clearComparison();
  if (state.current) changed();
});
for (const id of ["reviewer-a", "reviewer-b"])
  $(id).addEventListener("input", () => {
    clearComparison();
    if (state.current) changed();
  });
$("protocol").addEventListener("input", () => {
  if (state.current) {
    state.current.protocol = $("protocol").value;
    changed();
  }
});
$("adjudication-rationale").addEventListener("input", () => {
  if (state.current) {
    state.current.adjudication = {
      reviewers: [$("reviewer-a").value.trim(), $("reviewer-b").value.trim()],
      rationale: $("adjudication-rationale").value,
    };
    changed();
  }
});
for (const id of ["complete", "human-reviewed"])
  $(id).addEventListener("change", () => {
    if (state.current) {
      state.current.complete = $("complete").checked;
      state.current.human_reviewed = $("human-reviewed").checked;
      changed(false);
    }
  });
for (const input of coordinates) input.addEventListener("change", updateBox);
for (const [id, field] of [
  ["literal-text", "text"],
  ["region-rationale", "rationale"],
])
  $(id).addEventListener("input", () => {
    const region = selected();
    if (region) {
      region[field] = $(id).value;
      changed();
      if (field === "text") renderRegions();
    }
  });
$("protected-terms").addEventListener("input", () => {
  const region = selected();
  if (region) {
    region.protected_terms = $("protected-terms")
      .value.split(/\r?\n/)
      .filter((line) => line.length);
    changed();
  }
});
$("recognition-evaluable").addEventListener("change", () => {
  const region = selected();
  if (region) {
    region.recognition_evaluable = $("recognition-evaluable").checked;
    changed();
  }
});
$("region-form").addEventListener("submit", (event) => event.preventDefault());
// Viewing never calls changed(): zoom and pan do not edit annotation or attest review.
function applyView(reset = false) {
  const image = $("source-image"),
    stage = $("image-stage"),
    scroll = $("image-scroll");
  if (!image.complete || !image.naturalWidth) return;
  const padding = getComputedStyle(scroll);
  const horizontal = parseFloat(padding.paddingLeft) + parseFloat(padding.paddingRight);
  const vertical = parseFloat(padding.paddingTop) + parseFloat(padding.paddingBottom);
  const before = stage.getBoundingClientRect();
  const center = [
    (scroll.scrollLeft + (scroll.clientWidth - horizontal) / 2) / (before.width || 1),
    (scroll.scrollTop + (scroll.clientHeight - vertical) / 2) / (before.height || 1),
  ];
  const width =
    state.view === "fit"
      ? Math.max(1, scroll.clientWidth - horizontal)
      : (image.naturalWidth * state.zoom) / 100;
  stage.style.width = `${width}px`;
  if (reset || state.view === "fit") {
    scroll.scrollLeft = 0;
    scroll.scrollTop = 0;
  } else {
    scroll.scrollLeft = center[0] * width - (scroll.clientWidth - horizontal) / 2;
    scroll.scrollTop =
      (center[1] * width * image.naturalHeight) / image.naturalWidth -
      (scroll.clientHeight - vertical) / 2;
  }
  const percent = Math.round((100 * width) / image.naturalWidth);
  $("zoom-value").textContent = state.view === "fit" ? `Fit · ${percent}%` : `${state.zoom}%`;
  $("view-zoom").value = String(
    state.view === "fit" ? Math.max(25, Math.min(400, percent)) : state.zoom,
  );
  $("view-zoom").setAttribute(
    "aria-valuetext",
    state.view === "fit"
      ? `Fit to viewport, ${percent} percent of natural pixels`
      : `${state.zoom} percent of natural pixels`,
  );
  $("view-fit").setAttribute("aria-pressed", String(state.view === "fit"));
  $("view-natural").setAttribute(
    "aria-pressed",
    String(state.view !== "fit" && state.zoom === 100),
  );
}
function renderCrop() {
  const image = $("source-image"),
    region = selected();
  $("crop-preview").hidden = !region || !image.complete || !image.naturalWidth;
  if ($("crop-preview").hidden) return;
  const [x, y, width, height] = region.bbox_normalized;
  const sx = Math.min(image.naturalWidth - 1, Math.floor(x * image.naturalWidth));
  const sy = Math.min(image.naturalHeight - 1, Math.floor(y * image.naturalHeight));
  const sw = Math.max(
    1,
    Math.min(image.naturalWidth, Math.ceil((x + width) * image.naturalWidth)) - sx,
  );
  const sh = Math.max(
    1,
    Math.min(image.naturalHeight, Math.ceil((y + height) * image.naturalHeight)) - sy,
  );
  const scale = Math.min(4, 800 / Math.max(sw, sh));
  const canvas = $("region-crop");
  canvas.width = Math.max(1, Math.round(sw * scale));
  canvas.height = Math.max(1, Math.round(sh * scale));
  canvas.setAttribute("aria-label", `Unchanged source pixel crop for region ${region.id}`);
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = false;
  context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  $("crop-info").textContent =
    `${region.id} · ${sw} × ${sh} source pixels · ${Math.round(scale * 100)}% display scale. Scroll to inspect the crop.`;
}
$("view-fit").addEventListener("click", () => {
  state.view = "fit";
  applyView(true);
});
$("view-natural").addEventListener("click", () => {
  state.view = "manual";
  state.zoom = 100;
  applyView();
});
$("view-zoom").addEventListener("input", () => {
  state.view = "manual";
  state.zoom = Number($("view-zoom").value);
  applyView();
});
new ResizeObserver(() => {
  if (state.view === "fit") applyView();
}).observe($("image-scroll"));
$("source-image").addEventListener("load", () => {
  $("image-stage").style.aspectRatio =
    `${$("source-image").naturalWidth}/${$("source-image").naturalHeight}`;
  for (const id of ["view-fit", "view-natural", "view-zoom"]) $(id).disabled = false;
  applyView(true);
  overlay();
  renderCrop();
});
$("overlay").addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || state.saving) return;
  if (state.drawing && state.current) {
    state.drag = point(event);
    $("overlay").setPointerCapture(event.pointerId);
  } else if (event.pointerType !== "touch") {
    state.pan = {
      x: event.clientX,
      y: event.clientY,
      left: $("image-scroll").scrollLeft,
      top: $("image-scroll").scrollTop,
    };
  }
});
$("overlay").addEventListener("pointermove", (event) => {
  if (state.drag) overlay(rectangle(state.drag, point(event)));
  else if (state.pan) {
    const dx = event.clientX - state.pan.x,
      dy = event.clientY - state.pan.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) {
      state.suppressClick = true;
      if (!$("overlay").hasPointerCapture(event.pointerId))
        $("overlay").setPointerCapture(event.pointerId);
      $("overlay").classList.add("panning");
    }
    $("image-scroll").scrollLeft = state.pan.left - dx;
    $("image-scroll").scrollTop = state.pan.top - dy;
  }
});
function endPan() {
  state.pan = null;
  $("overlay").classList.remove("panning");
  setTimeout(() => {
    state.suppressClick = false;
  }, 0);
}
$("overlay").addEventListener("pointerup", (event) => {
  if (!state.drag) {
    endPan();
    return;
  }
  const box = rectangle(state.drag, point(event));
  state.drag = null;
  if (box[2] >= 0.005 && box[3] >= 0.005) addRegion(box);
  else overlay();
});
$("overlay").addEventListener("pointercancel", () => {
  state.drag = null;
  endPan();
  overlay();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    state.drag = null;
    endPan();
    state.drawing = false;
    render();
    return;
  }
  if (event.target.closest("input,textarea,select") || !state.current || state.saving) return;
  if (event.key.toLowerCase() === "n") {
    event.preventDefault();
    toggleDrawing();
  }
  if (event.key === "Delete") {
    event.preventDefault();
    deleteRegion();
  }
  if (["ArrowDown", "ArrowUp"].includes(event.key) && state.current.regions.length) {
    event.preventDefault();
    const regions = state.current.regions,
      index = regions.findIndex((region) => region.id === state.selected);
    selectRegion(
      regions[(index + (event.key === "ArrowDown" ? 1 : regions.length - 1)) % regions.length].id,
    );
  }
});

request("/api/catalog")
  .then(async (catalog) => {
    if (!Array.isArray(catalog.items)) throw new Error("Invalid catalog response.");
    state.items = catalog.items;
    $("catalog-info").textContent =
      `${catalog.items.length} images · catalog ${String(catalog.catalog_sha256).slice(0, 12)}`;
    renderItems();
    if (state.items.length) await openItem(state.items[0]);
    else message("No images in this collection.");
  })
  .catch(error);
