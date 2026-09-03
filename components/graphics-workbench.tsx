"use client";

import { useEffect, useRef, useState, type SyntheticEvent, type PointerEvent } from "react";
import { Download, ImagePlus, Play, RefreshCw, Scan, ShieldCheck } from "lucide-react";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Fields = { name: string; specification: string; kind: string; division: string };
type Candidate = {
  id: number;
  name: string;
  component_type: string;
  similarity: number;
  relation: string;
  component_rows: number;
  evidence: Record<string, string>[];
};
type Region = {
  id: string;
  number: number;
  bbox_normalized: number[];
  raw_text: string;
  parsed: Fields;
  effective: Fields;
  status: string;
  version: number;
  clipped: boolean;
  ocr_disagreement: boolean;
  ocr: { mean_confidence: number | null; model?: string; psm: number };
  alternative_ocr: { text: string; model?: string; psm: number };
  candidates: Candidate[];
  review: { payload: { reviewer: string; rationale: string }; created_at: string } | null;
};
type Config = {
  mode: string;
  model: string;
  language: string;
  brightness: number;
  saturation: number;
  binarization: string;
  ink_threshold: number;
  min_area: number;
  match_threshold: number;
  regions: number[][];
};
type Run = {
  id: string;
  title: string;
  project: string;
  status: string;
  error: string | null;
  parent_id?: string;
  config: Config;
  metadata: Record<string, string>;
};
type Result = {
  run_id: string;
  regions: Region[];
  image: { width: number; height: number; sha256: string };
  markdown: string;
  raw_markdown: string;
  metadata: Record<string, string>;
  paradata: Record<string, unknown>;
  review_events: unknown[];
};
const initialConfig: Config = {
  mode: "organ_stops",
  model: "best",
  language: "eng+deu",
  brightness: 135,
  saturation: 60,
  binarization: "fixed",
  ink_threshold: 150,
  min_area: 0.0006,
  match_threshold: 65,
  regions: [],
};
const fieldClass = "w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm";
const statusLabel: Record<string, string> = {
  unreviewed: "Ungeprüft",
  accept: "Freigegeben",
  retain: "OCR bestätigt",
  defer: "Zurückgestellt",
  queued: "Wartend",
  running: "In Verarbeitung",
  completed: "Abgeschlossen",
  failed: "Fehlgeschlagen",
};

function Pick({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <div className="space-y-1 text-sm">
      <span>{label}</span>
      <Select
        value={value}
        onValueChange={(v) => {
          if (v !== null) onChange(v);
        }}
      >
        <SelectTrigger aria-label={label} className="h-10 w-full bg-white">
          <SelectValue>{options.find(([v]) => v === value)?.[1] ?? value}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {options.map(([v, text]) => (
            <SelectItem key={v} value={v}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/graphics${path}`, options);
  const data = (await response.json()) as { detail?: unknown };
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data),
    );
  return data as T;
}

function sourceLink(value: string | undefined) {
  return value && /^https?:\/\//i.test(value) ? value : undefined;
}

function markerOffset(region: Region, regions: Region[]) {
  const [left, top, width] = region.bbox_normalized;
  let anchor = left;
  for (const _region of regions) {
    const blockers = regions.filter(
      (other) =>
        other.id !== region.id &&
        other.bbox_normalized[1] <= top + 0.025 &&
        other.bbox_normalized[1] + other.bbox_normalized[3] >= top - 0.01 &&
        other.bbox_normalized[0] < anchor &&
        anchor <= other.bbox_normalized[0] + other.bbox_normalized[2],
    );
    if (!blockers.length) break;
    anchor = Math.min(...blockers.map((other) => other.bbox_normalized[0]));
  }
  return `${((anchor - left) / width) * 100}%`;
}

export function GraphicsWorkbench({ initialRunId }: { initialRunId: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState(initialRunId);
  const [run, setRun] = useState<Run | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [regionId, setRegionId] = useState("r001");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<Config>(initialConfig);
  const [project, setProject] = useState("Organ-stop images");
  const [showUpload, setShowUpload] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [boxes, setBoxes] = useState<number[][]>([]);
  const [roiText, setRoiText] = useState("");
  const [drag, setDrag] = useState<number[] | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [view, setView] = useState("effective");
  const [filter, setFilter] = useState("all");
  const [reload, setReload] = useState(0);
  const outputRef = useRef<HTMLDivElement>(null);
  const region = result?.regions.find((r) => r.id === regionId) ?? result?.regions[0];

  function selectRun(id: string) {
    setRunId(id);
    setResult(null);
    setRun(null);
    setBoxes([]);
    setRoiText("");
    setDrawing(false);
    window.history.replaceState(null, "", `/graphics?run=${encodeURIComponent(id)}`);
  }

  useEffect(() => {
    let canceled = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const [list, data] = await Promise.all([
          api<{ runs: Run[] }>("/runs"),
          api<{ run: Run; result: Result | null }>(`/runs/${runId}`),
        ]);
        if (canceled) return;
        setRuns(list.runs);
        setRun(data.run);
        setResult(data.result);
        setError("");
        if (data.run.status === "queued" || data.run.status === "running")
          timer = setTimeout(load, 2000);
      } catch (e) {
        if (!canceled) setError((e as Error).message);
      }
    };
    void load();
    return () => {
      canceled = true;
      clearTimeout(timer);
    };
  }, [runId, reload]);

  async function upload(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    form.set("config", JSON.stringify(config));
    form.set("project", project);
    const meta = Object.fromEntries(
      ["creator", "source_url", "license", "license_url", "attribution"].map((k) => {
        const value = form.get(k);
        return [k, typeof value === "string" ? value : ""];
      }),
    );
    form.set("metadata", JSON.stringify(meta));
    try {
      const data = await api<{ id: string }>("/runs", { method: "POST", body: form });
      selectRun(data.id);
      setShowUpload(false);
      setNotice("Bild gespeichert. Die Verarbeitung läuft lokal.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function rerun(manual: boolean) {
    setBusy(true);
    setError("");
    try {
      const regions = manual ? (roiText.trim() ? JSON.parse(roiText) : boxes) : [];
      if (manual && !regions.length)
        throw new Error("Zeichnen Sie zuerst eine Region oder geben Sie Koordinaten ein.");
      const data = await api<{ id: string }>(`/runs/${runId}/rerun`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...config, regions }),
      });
      selectRun(data.id);
      setNotice("Neuer Lauf angelegt; bisherige OCR und Entscheidungen bleiben unverändert.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function point(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    ];
  }
  function endDraw(event: PointerEvent<SVGSVGElement>) {
    if (!drag || !drawing) return;
    const p = point(event);
    const box = [
      Math.min(drag[0], p[0]),
      Math.min(drag[1], p[1]),
      Math.abs(drag[0] - p[0]),
      Math.abs(drag[1] - p[1]),
    ];
    if (box[2] >= 0.005 && box[3] >= 0.005) {
      setBoxes((old) => [...old, box]);
      setRoiText("");
    }
    setDrag(null);
  }

  const shownRegions =
    result?.regions.filter(
      (r) => filter === "all" || r.status === "unreviewed" || r.status === "defer",
    ) ?? [];
  return (
    <div className="mx-auto max-w-[1320px] space-y-5" lang="de">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Bildquellen · Lokaler Forschungsmodus</p>
          <h1 className="mt-1 font-serif text-3xl font-semibold">Grafiken & Registerzüge</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            Bildregionen erkennen, Beschriftungen transkribieren und MODAVIS-Belege prüfen.
            Bildlesung und Korpusvorschläge bleiben getrennt.
          </p>
        </div>
        <button className="primary-action" onClick={() => setShowUpload((v) => !v)}>
          <ImagePlus className="size-4" /> Bild hinzufügen
        </button>
      </header>
      {error && (
        <div
          role="alert"
          className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
        >
          {error}
          <button className="ml-3 underline" onClick={() => setReload((v) => v + 1)}>
            Erneut laden
          </button>
        </div>
      )}
      {notice && (
        <output className="block rounded-lg bg-teal-soft p-3 text-sm text-teal">{notice}</output>
      )}
      <section className="surface-panel p-4">
        <div className="grid gap-4 md:grid-cols-[1.4fr_1fr_auto]">
          <Pick
            label="Gespeicherter Bildlauf"
            value={runId}
            onChange={selectRun}
            options={
              runs.length
                ? runs.map((r) => [
                    r.id,
                    `${r.title} · ${statusLabel[r.status]} · ${r.id.slice(0, 8)}`,
                  ])
                : [[runId, "Beispiel wird geladen…"]]
            }
          />
          <Pick
            label="Verarbeitungsmodus für neue Läufe"
            value={config.mode}
            onChange={(mode) => setConfig({ ...config, mode })}
            options={[
              ["organ_stops", "Registerzüge + MODAVIS"],
              ["graphics", "Grafik: Textregionen ohne Korpus"],
            ]}
          />
          <button
            className="secondary-action self-end"
            disabled={busy || !run}
            onClick={() => void rerun(false)}
          >
            <RefreshCw className="size-4" /> Neu verarbeiten
          </button>
        </div>
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold">
            Einstellungen und Grenzen
          </summary>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Pick
              label="OCR-Sprachen"
              value={config.language}
              onChange={(language) => setConfig({ ...config, language })}
              options={[
                ["eng+deu", "Englisch + Deutsch"],
                ["deu+eng", "Deutsch + Englisch"],
                ["deu", "Deutsch"],
                ["eng", "Englisch"],
              ]}
            />
            <Pick
              label="Binarisierung"
              value={config.binarization}
              onChange={(binarization) => setConfig({ ...config, binarization })}
              options={[
                ["fixed", "Feste Schwelle (helle Schilder)"],
                ["otsu", "Otsu (automatisch)"],
                ["none", "Graustufen"],
              ]}
            />
            <Pick
              label="Basis-Modell"
              value={config.model}
              onChange={(model) => setConfig({ ...config, model })}
              options={[
                ["best", "Tesseract tessdata_best"],
                ["fast", "Tesseract fast (Debian)"],
              ]}
            />
            <label className="space-y-1 text-sm">
              Schrift-Schwellenwert
              <input
                className={fieldClass}
                type="number"
                min={50}
                max={230}
                value={config.ink_threshold}
                onChange={(e) => setConfig({ ...config, ink_threshold: Number(e.target.value) })}
              />
            </label>
            {(
              [
                ["brightness", "Minimale Helligkeit", 60, 240, 1],
                ["saturation", "Maximale Sättigung", 10, 160, 1],
                ["min_area", "Minimale Bildflächenquote", 0.0001, 0.05, 0.0001],
                ["match_threshold", "Ähnlichkeitsschwelle (%)", 50, 100, 1],
              ] as const
            ).map(([key, label, min, max, step]) => (
              <label className="space-y-1 text-sm" key={key}>
                {label}
                <input
                  className={fieldClass}
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={config[key]}
                  onChange={(e) => setConfig({ ...config, [key]: Number(e.target.value) })}
                />
              </label>
            ))}
            {run && (
              <button
                className="secondary-action self-end"
                onClick={() => {
                  setConfig({ ...initialConfig, ...run.config });
                  setNotice("Einstellungen dieses Laufs übernommen.");
                }}
              >
                Laufeinstellungen übernehmen
              </button>
            )}
          </div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Registermodus: helle, wenig gesättigte Schildflächen; dunkle oder spiegelnde Schilder
            können fehlen. Grafikmodus: sichtbarer Text, keine semantische Beschreibung von
            Zeichnungen. Ähnlichkeitswerte sind keine Richtigkeitswahrscheinlichkeiten. Eigene
            Regionen ersetzen die automatische Detektion in einem neuen Lauf.
          </p>
        </details>
      </section>
      {showUpload && (
        <form onSubmit={upload} className="surface-panel space-y-4 p-5">
          <h2 className="font-serif text-xl">Bildquelle registrieren</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              Bilddatei (max. 20 MiB / 40 MP)
              <input
                required
                name="file"
                type="file"
                accept="image/jpeg,image/png,image/webp,image/tiff"
                className={fieldClass}
              />
            </label>
            <label className="space-y-1 text-sm">
              Titel
              <input name="title" required maxLength={200} className={fieldClass} />
            </label>
            <label className="space-y-1 text-sm">
              Projekt
              <input
                required
                value={project}
                onChange={(e) => setProject(e.target.value)}
                className={fieldClass}
              />
            </label>
            {[
              ["creator", "Urheber/in"],
              ["source_url", "Quellen-URL"],
              ["license", "Lizenz / Rechtevermerk"],
              ["license_url", "Lizenz-URL"],
              ["attribution", "Zitierempfehlung / Bildnachweis"],
            ].map(([name, label]) => (
              <label key={name} className="space-y-1 text-sm">
                {label}
                <input name={name} className={fieldClass} />
              </label>
            ))}
          </div>
          <p className="text-sm text-muted-foreground">
            Die Datei wird ausschließlich im lokalen Grafikdienst gespeichert. Fehlende
            Rechteangaben werden nicht ergänzt.
          </p>
          <button disabled={busy} className="primary-action" type="submit">
            <Play className="size-4" /> Speichern und verarbeiten
          </button>
        </form>
      )}
      {run && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="rounded-full bg-teal-soft px-3 py-1 font-semibold text-teal">
            {statusLabel[run.status]}
          </span>
          <span>{run.project}</span>
          <code className="break-all text-xs">{run.id}</code>
          <span>
            {run.config.mode === "organ_stops"
              ? "Registermodus · MODAVIS"
              : "Grafikmodus · ohne Korpus"}
          </span>
          {run.parent_id && (
            <button className="text-teal underline" onClick={() => selectRun(run.parent_id!)}>
              Ausgangslauf öffnen
            </button>
          )}
        </div>
      )}
      {run?.status === "failed" && (
        <p role="alert" className="text-red-800">
          Verarbeitung fehlgeschlagen: {run.error}. Passen Sie die Einstellungen an und starten Sie
          einen neuen Lauf.
        </p>
      )}
      {run && ["queued", "running"].includes(run.status) && (
        <output className="surface-panel block p-6">
          Bild wird lokal ausgewertet. Der Status aktualisiert sich automatisch; Sie können die
          Seite verlassen.
        </output>
      )}
      {result && (
        <>
          <div className="flex items-start gap-3 rounded-xl border border-teal/25 bg-teal-soft/30 p-4 text-sm leading-6">
            <ShieldCheck className="mt-1 size-5 shrink-0 text-teal" />
            <p>
              <strong>Bildbeleg vor Korpus.</strong> MODAVIS ist hier ein Fachkorpus, kein
              Autorenkorpus. Ein ähnlicher Name belegt weder dieselbe Lesung noch dieselbe Orgel.
              Ungeprüfte und zurückgestellte Stellen behalten die OCR; auch Fußton- und
              Chorzahl-Angaben bleiben wörtlich. {result.regions.length} Regionen, davon{" "}
              {result.regions.filter((r) => ["accept", "retain"].includes(r.status)).length}{" "}
              menschlich entschieden.
            </p>
          </div>
          <div className="grid items-start gap-5 xl:grid-cols-[1.05fr_1fr]">
            <section className="surface-panel min-w-0 overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
                <h2 className="font-semibold">Bildbeleg</h2>
                <button
                  aria-pressed={drawing}
                  className="secondary-action"
                  onClick={() => setDrawing((v) => !v)}
                >
                  <Scan className="size-4" /> {drawing ? "Zeichnen beenden" : "Regionen zeichnen"}
                </button>
                <a
                  target="_blank"
                  rel="noreferrer"
                  href={`/api/graphics/runs/${runId}/image`}
                  className="text-sm text-teal underline"
                >
                  Originalgröße
                </a>
              </div>
              <div className="max-h-[840px] overflow-auto bg-[#192722] p-7">
                <div
                  className="relative"
                  style={{ aspectRatio: `${result.image.width}/${result.image.height}` }}
                >
                  <img
                    alt={result.metadata.description || result.metadata.title}
                    src={`/api/graphics/runs/${runId}/image`}
                    className="block h-full w-full"
                  />
                  {drawing ? (
                    <svg
                      aria-label="Regionen durch Ziehen markieren; alternativ Koordinaten unten eingeben"
                      viewBox="0 0 1000 1000"
                      preserveAspectRatio="none"
                      className="absolute inset-0 h-full w-full touch-none cursor-crosshair"
                      onPointerDown={(e) => {
                        e.currentTarget.setPointerCapture(e.pointerId);
                        setDrag(point(e));
                      }}
                      onPointerUp={endDraw}
                      onPointerCancel={() => setDrag(null)}
                    >
                      {boxes.map((b, i) => (
                        <rect
                          key={i}
                          x={b[0] * 1000}
                          y={b[1] * 1000}
                          width={b[2] * 1000}
                          height={b[3] * 1000}
                          fill="#fff4"
                          stroke="#ffb84d"
                          strokeWidth="3"
                        />
                      ))}
                    </svg>
                  ) : (
                    result.regions.map((r) => (
                      <button
                        key={r.id}
                        aria-label={`Region ${r.number}: ${r.raw_text || "Keine Lesung"}`}
                        aria-pressed={r.id === region?.id}
                        onClick={() => setRegionId(r.id)}
                        className={`absolute border-2 transition focus-visible:outline-4 focus-visible:outline-white ${r.id === region?.id ? "z-10 border-[#ffb84d] bg-amber-200/10 shadow-[0_0_0_2px_#0005]" : "border-teal-300/70 hover:border-amber-300 hover:bg-white/10"}`}
                        style={{
                          left: `${r.bbox_normalized[0] * 100}%`,
                          top: `${r.bbox_normalized[1] * 100}%`,
                          width: `${r.bbox_normalized[2] * 100}%`,
                          height: `${r.bbox_normalized[3] * 100}%`,
                        }}
                      >
                        <span
                          style={{ left: markerOffset(r, result.regions) }}
                          className="absolute -ml-1 top-0 -translate-x-full text-right text-sm font-bold leading-none text-amber-200 [text-shadow:0_1px_2px_black]"
                        >
                          {r.number}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
              <div className="space-y-2 p-4 text-sm leading-6">
                <p>
                  {result.metadata.attribution || "Kein Bildnachweis angegeben."}{" "}
                  {sourceLink(result.metadata.source_url) && (
                    <a
                      className="text-teal underline"
                      href={sourceLink(result.metadata.source_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Quelle
                    </a>
                  )}{" "}
                  ·{" "}
                  {sourceLink(result.metadata.license_url) ? (
                    <a
                      className="text-teal underline"
                      href={sourceLink(result.metadata.license_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {result.metadata.license}
                    </a>
                  ) : (
                    result.metadata.license
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  Anzeige: EXIF-ausgerichtetes Bild; darüber separate Markierungen. Das unveränderte
                  Original liegt im Forschungsexport.
                </p>
                <details open={drawing || boxes.length > 0}>
                  <summary className="cursor-pointer font-semibold">
                    Eigene Regionen ({boxes.length} gezeichnet)
                  </summary>
                  <p>
                    Alle gewünschten Schilder markieren. Nur diese Regionen werden im neuen Lauf
                    verarbeitet; die bisherige Auswertung bleibt erhalten.
                  </p>
                  <label>
                    Alternativ: JSON-Koordinaten [x, y, Breite, Höhe], jeweils 0–1
                    <textarea
                      aria-label="Eigene Regionen als JSON"
                      className={`${fieldClass} mt-2 h-20 font-mono`}
                      value={roiText}
                      placeholder="[[0.15, 0.1, 0.2, 0.08]]"
                      onChange={(e) => setRoiText(e.target.value)}
                    />
                  </label>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      className="secondary-action"
                      onClick={() => {
                        setBoxes(result.regions.map((r) => r.bbox_normalized));
                        setRoiText("");
                      }}
                    >
                      Bestehende Regionen übernehmen
                    </button>
                    <button
                      className="secondary-action"
                      onClick={() => {
                        setBoxes([]);
                        setRoiText("");
                      }}
                    >
                      Auswahl leeren
                    </button>
                    <button
                      disabled={busy}
                      className="primary-action"
                      onClick={() => void rerun(true)}
                    >
                      Mit eigenen Regionen starten
                    </button>
                  </div>
                </details>
              </div>
            </section>
            <div className="min-w-0 space-y-4">
              <div className="surface-panel p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h2 className="font-serif text-xl">Prüfwarteschlange</h2>
                  <Pick
                    label="Ansicht"
                    value={filter}
                    onChange={setFilter}
                    options={[
                      ["all", "Alle Regionen"],
                      ["pending", "Offene Entscheidungen"],
                    ]}
                  />
                </div>
                <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto">
                  {shownRegions.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => setRegionId(r.id)}
                      aria-pressed={r.id === region?.id}
                      className={`rounded-lg border px-3 py-2 text-sm ${r.id === region?.id ? "border-teal bg-teal-soft text-teal" : "border-stone-200 hover:bg-stone-50"}`}
                    >
                      {r.number}. {r.effective.name || "Keine Lesung"}{" "}
                      <span className="text-xs">· {statusLabel[r.status]}</span>
                    </button>
                  ))}
                  {!shownRegions.length && <p className="text-sm">Keine offenen Regionen.</p>}
                </div>
              </div>
              {region && (
                <RegionReview
                  key={`${runId}:${region.id}:${region.version}`}
                  region={region}
                  runId={runId}
                  reviewer={reviewer}
                  setReviewer={setReviewer}
                  onSaved={(data) => {
                    setResult(data);
                    setView("effective");
                    setNotice(
                      "Entscheidung gespeichert. Die vollständige Markdown-Tabelle wurde aktualisiert.",
                    );
                  }}
                  onError={setError}
                />
              )}
            </div>
          </div>
          <section ref={outputRef} className="surface-panel min-w-0 p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-serif text-2xl">Vollständiges Ergebnis</h2>
              <div className="flex flex-wrap gap-2">
                {[
                  ["markdown", "Markdown"],
                  ["csv", "CSV"],
                  ["json", "JSON"],
                  ["bundle", "Forschungs-ZIP"],
                ].map(([format, label]) => (
                  <a
                    key={format}
                    className="secondary-action"
                    href={`/api/graphics/runs/${runId}/export?format=${format}`}
                  >
                    <Download className="size-4" />
                    {label}
                  </a>
                ))}
              </div>
            </div>
            <Tabs value={view} onValueChange={(v) => setView(String(v))}>
              <TabsList>
                <TabsTrigger value="effective">Arbeitsstand</TabsTrigger>
                <TabsTrigger value="raw">Unveränderte OCR</TabsTrigger>
                <TabsTrigger value="source">Markdown-Quelltext</TabsTrigger>
                <TabsTrigger value="provenance">Metadaten & Paradata</TabsTrigger>
              </TabsList>
              <TabsContent value="effective">
                <MarkdownRenderer
                  content={result.markdown}
                  label="Vollständiger Arbeitsstand der Bildauswertung"
                />
              </TabsContent>
              <TabsContent value="raw">
                <MarkdownRenderer
                  content={result.raw_markdown}
                  label="Vollständige unveränderte Bild-OCR"
                />
              </TabsContent>
              <TabsContent value="source">
                <pre className="max-h-[700px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-stone-50 p-4 text-sm">
                  {result.markdown}
                </pre>
              </TabsContent>
              <TabsContent value="provenance">
                <p className="my-3 text-sm">
                  Die JSON- und ZIP-Exporte enthalten zusätzlich alle Korpusbelege, Koordinaten und
                  Entscheidungen. SHA-256: {result.image.sha256}
                </p>
                <pre className="max-h-[700px] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-stone-50 p-4 text-xs">
                  {JSON.stringify(
                    {
                      metadata: result.metadata,
                      paradata: result.paradata,
                      review_events: result.review_events,
                    },
                    null,
                    2,
                  )}
                </pre>
              </TabsContent>
            </Tabs>
          </section>
        </>
      )}
    </div>
  );
}

function RegionReview({
  region,
  runId,
  reviewer,
  setReviewer,
  onSaved,
  onError,
}: {
  region: Region;
  runId: string;
  reviewer: string;
  setReviewer: (v: string) => void;
  onSaved: (r: Result) => void;
  onError: (v: string) => void;
}) {
  const [draft, setDraft] = useState(region.effective);
  const [rationale, setRationale] = useState("");
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const valid = reviewer.trim().length >= 2 && rationale.trim().length >= 12;
  async function decide(action: string) {
    setSaving(true);
    onError("");
    try {
      onSaved(
        await api<Result>(`/runs/${runId}/regions/${region.id}/review`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...draft,
            action,
            reviewer,
            rationale,
            candidate_id: candidateId,
            expected_version: region.version,
          }),
        }),
      );
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="surface-panel space-y-4 p-5" aria-label={`Prüfung Region ${region.number}`}>
      <div className="flex justify-between gap-2">
        <h3 className="font-serif text-xl">Region {region.number}</h3>
        <span className="text-sm text-teal">
          {statusLabel[region.status]} · v{region.version}
        </span>
      </div>
      <img
        className="max-h-56 w-full rounded-lg border bg-stone-100 object-contain"
        alt={`Unveränderter Bildausschnitt, Region ${region.number}`}
        src={`/api/graphics/runs/${runId}/regions/${region.id}/crop`}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-sm font-semibold">
            OCR-Basis ({region.ocr.model || "fast"}, PSM {region.ocr.psm})
          </p>
          <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-stone-50 p-3 text-base">
            {region.raw_text || "[keine Lesung]"}
          </pre>
        </div>
        <div>
          <p className="text-sm font-semibold">
            Alternative ({region.alternative_ocr.model || "fast"}, PSM {region.alternative_ocr.psm})
          </p>
          <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-stone-50 p-3 text-base">
            {region.alternative_ocr.text || "[keine Lesung]"}
          </pre>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        OCR-Score: {region.ocr.mean_confidence ?? "n/a"} / 100 (unkalibriert).{" "}
        {region.ocr_disagreement
          ? "OCR-Ansichten widersprechen sich."
          : "OCR-Ansichten stimmen überein; kein Korrektheitsnachweis."}{" "}
        {region.clipped && <strong className="text-amber-800"> Am Bildrand abgeschnitten.</strong>}
      </p>
      <div>
        <h4 className="mb-2 text-sm font-semibold">MODAVIS-Belege (beratend)</h4>
        {region.candidates.length ? (
          <div className="space-y-2">
            {region.candidates.map((c) => (
              <details key={c.id} className="rounded-lg border border-stone-200 p-3">
                <summary className="cursor-pointer text-sm">
                  <strong>{c.name}</strong> · {Math.round(c.similarity * 100)} % Zeichenähnlichkeit
                  ·{" "}
                  {c.relation === "attestation"
                    ? "Schreibweise belegt"
                    : "abweichende Schreibweise"}
                </summary>
                <p className="my-2 text-xs leading-5">
                  {c.component_type}; {c.component_rows.toLocaleString("de-DE")} Komponenten-Zeilen.
                  Bis zu drei exemplarische Belege; kein Häufigkeitsprior, kein Identitätsnachweis.
                </p>
                {c.evidence.map((e) => (
                  <div
                    key={e.component_id}
                    className="my-2 break-all rounded bg-stone-50 p-2 text-xs leading-5"
                  >
                    <p className="font-semibold">
                      {e.label} · {e.pitch_label || "Angabe unbekannt"} ·{" "}
                      {e.division_label || "Werk unbekannt"}
                    </p>
                    <p>{e.component_id}</p>
                    <p>{e.source_record_id}</p>
                    <p>Orgel: {e.organ_mdvs_id}</p>
                  </div>
                ))}
                <a
                  className="text-xs text-teal underline"
                  target="_blank"
                  rel="noreferrer"
                  href="https://doi.org/10.5281/zenodo.22234059"
                >
                  Ukolov: MODAVIS POD 1.5.0 · CC BY 4.0
                </a>
                <button
                  className="secondary-action mt-3 w-full"
                  onClick={() => {
                    setDraft({ ...draft, name: c.name });
                    setCandidateId(c.id);
                  }}
                >
                  Name als Entwurf übernehmen
                </button>
              </details>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Kein passender Beleg über der Schwelle oder Korpus deaktiviert. Nicht ergänzen, was im
            Bild nicht lesbar ist.
          </p>
        )}
      </div>
      <div className="border-t pt-4">
        <h4 className="mb-3 font-semibold">Menschliche Entscheidung</h4>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            Lesung / Name
            <input
              className={fieldClass}
              value={draft.name}
              onChange={(e) => {
                setDraft({ ...draft, name: e.target.value });
                setCandidateId(null);
              }}
            />
          </label>
          <label className="space-y-1 text-sm">
            Angabe wörtlich (z. B. IV–VI)
            <input
              className={fieldClass}
              value={draft.specification}
              onChange={(e) => setDraft({ ...draft, specification: e.target.value })}
            />
          </label>
          <Pick
            label="Typ"
            value={draft.kind}
            onChange={(kind) => setDraft({ ...draft, kind })}
            options={[
              ["stop", "Register"],
              ["coupler", "Koppel"],
              ["division", "Werkschild"],
              ["accessory", "Spielhilfe"],
              ["unknown", "Unbekannt"],
              ["not_text", "Keine Beschriftung"],
            ]}
          />
          <label className="space-y-1 text-sm">
            Werk (optional, bildbasiert)
            <input
              className={fieldClass}
              value={draft.division}
              onChange={(e) => setDraft({ ...draft, division: e.target.value })}
            />
          </label>
          <label className="space-y-1 text-sm sm:col-span-2">
            Prüfer/in
            <input
              autoComplete="name"
              className={fieldClass}
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm sm:col-span-2">
            Begründung anhand des Bildes
            <textarea
              className={`${fieldClass} min-h-24`}
              minLength={12}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="Welche sichtbaren Buchstaben oder Merkmale begründen Ihre Entscheidung?"
            />
          </label>
        </div>
        <p className="my-3 text-xs leading-5 text-muted-foreground">
          Mindestens 2 Zeichen für Prüfer/in und 12 für die Begründung. „OCR bestätigen“ verwirft
          den Entwurf und bestätigt die unveränderte OCR. „Zurückstellen“ behält die OCR als
          Arbeitsstand.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            disabled={!valid || saving || (!draft.name.trim() && draft.kind !== "not_text")}
            onClick={() => void decide("accept")}
            className="primary-action"
          >
            Lesung freigeben
          </button>
          <button
            disabled={!valid || saving}
            onClick={() => void decide("retain")}
            className="secondary-action"
          >
            OCR bestätigen
          </button>
          <button
            disabled={!valid || saving}
            onClick={() => void decide("defer")}
            className="secondary-action"
          >
            Zurückstellen
          </button>
        </div>
      </div>
      {region.review && (
        <p className="border-t pt-3 text-sm leading-6">
          Letzte Entscheidung: {region.review.payload.reviewer} · {region.review.created_at}
          <br />
          {region.review.payload.rationale}
        </p>
      )}
    </section>
  );
}
