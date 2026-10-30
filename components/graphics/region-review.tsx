"use client";

import { useState } from "react";
import type { Fields, Region, Result, Review, RegionDraft } from "@/lib/graphics/types";
import { graphicsApi, errorMessage } from "@/lib/graphics/api";
import { Pick, fieldClass, statusLabel } from "./shared";

export function RegionReview({
  region,
  runId,
  reviewer,
  setReviewer,
  onSaved,
  onError,
  draftData,
  onDraft,
}: {
  region: Region;
  runId: string;
  reviewer: string;
  setReviewer: (value: string) => void;
  onSaved: (result: Result) => void;
  onError: (message: string) => void;
  draftData: RegionDraft;
  onDraft: (draft: RegionDraft) => void;
}) {
  const draft = draftData.fields;
  const rationale = draftData.rationale;
  const candidateId = draftData.candidateId;
  const setDraft = (fields: Fields) => onDraft({ ...draftData, fields });
  const setRationale = (rationale: string) => onDraft({ ...draftData, rationale });
  const [saving, setSaving] = useState(false);
  const valid = reviewer.trim().length >= 2 && rationale.trim().length >= 12;
  async function decide(action: Review["action"]) {
    setSaving(true);
    onError("");
    try {
      onSaved(
        await graphicsApi.review(runId, region.id, {
          ...draft,
          action,
          reviewer,
          rationale,
          candidate_id: candidateId,
          expected_version: draftData.expectedVersion,
        }),
      );
    } catch (e) {
      onError(errorMessage(e));
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
                    onDraft({
                      ...draftData,
                      fields: { ...draft, name: c.name },
                      candidateId: c.id,
                    });
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
      {draftData.expectedVersion !== region.version && (
        <div role="status" className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          Eine neuere Entscheidung liegt vor. Ihr Entwurf bleibt erhalten. Vergleichen Sie die
          aktuelle Lesung vor einem erneuten Speichern.
          <button
            className="mt-2 block underline"
            onClick={() => onDraft({ ...draftData, expectedVersion: region.version })}
          >
            Nach Vergleich auf aktuelle Version beziehen
          </button>
        </div>
      )}
      <div className="border-t pt-4">
        <h4 className="mb-3 font-semibold">Menschliche Entscheidung</h4>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            Lesung / Name
            <input
              className={fieldClass}
              value={draft.name}
              onChange={(e) => {
                onDraft({
                  ...draftData,
                  fields: { ...draft, name: e.target.value },
                  candidateId: null,
                });
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
