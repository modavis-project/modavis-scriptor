"use client";

import { useState, type PointerEvent } from "react";
import { Scan } from "lucide-react";
import type { Box, Region, Result } from "@/lib/graphics/types";
import { defaultConfig, isConfig_Input } from "@/lib/graphics/contracts.generated";
import { errorMessage } from "@/lib/graphics/api";
import { fieldClass, sourceLink } from "./shared";

function markerOffset(region: Region, regions: Region[]) {
  const [left, top, width] = region.bbox_normalized;
  let anchor = left;
  for (let index = 0; index < regions.length; index++) {
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

export function EvidencePanel({
  result,
  runId,
  region,
  setRegionId,
  busy,
  onProcessRegions,
  onError,
}: {
  result: Result;
  runId: string;
  region: Region | undefined;
  setRegionId: (id: string) => void;
  busy: boolean;
  onProcessRegions: (regions: Box[]) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [drawing, setDrawing] = useState(false);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [roiText, setRoiText] = useState("");
  const [drag, setDrag] = useState<[number, number] | null>(null);
  async function processRegions() {
    try {
      const input: unknown = roiText.trim() ? JSON.parse(roiText) : boxes;
      const proposal = { ...defaultConfig, regions: input };
      if (!isConfig_Input(proposal) || !proposal.regions?.length)
        throw new Error("Zeichnen Sie zuerst gültige Regionen oder geben Sie Koordinaten ein.");
      await onProcessRegions(proposal.regions);
    } catch (error) {
      onError(errorMessage(error));
    }
  }
  function point(event: PointerEvent<SVGSVGElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    ];
  }
  function endDraw(event: PointerEvent<SVGSVGElement>) {
    if (!drag || !drawing) return;
    const p = point(event);
    const box: Box = [
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

  return (
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
              onClick={() => void processRegions()}
            >
              Mit eigenen Regionen starten
            </button>
          </div>
        </details>
      </div>
    </section>
  );
}
