"use client";
import { ImagePlus, ShieldCheck } from "lucide-react";
import { useWorkbench } from "@/lib/graphics/use-workbench";
import { ConfigurationPanel } from "./graphics/configuration-panel";
import { UploadPanel } from "./graphics/upload-panel";
import { EvidencePanel } from "./graphics/evidence-panel";
import { RegionQueue } from "./graphics/region-queue";
import { RegionReview } from "./graphics/region-review";
import { OutputPanel } from "./graphics/output-panel";
import { statusLabel } from "./graphics/shared";

export function GraphicsWorkbench({ initialRunId }: { initialRunId: string }) {
  const state = useWorkbench(initialRunId);
  const { run, result, region, runId } = state;
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
        <button className="primary-action" onClick={() => state.setShowUpload((value) => !value)}>
          <ImagePlus className="size-4" /> Bild hinzufügen
        </button>
      </header>
      {state.error && (
        <div
          role="alert"
          className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
        >
          {state.error}
          <button className="ml-3 underline" onClick={state.reload}>
            Erneut laden
          </button>
        </div>
      )}
      {state.notice && (
        <output className="block rounded-lg bg-teal-soft p-3 text-sm text-teal">
          {state.notice}
        </output>
      )}
      {result?.integrity.coverage === "legacy-recorded-hashes" && (
        <p
          role="status"
          className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
        >
          Historischer Lauf: Original, Bild und Ausschnitte werden anhand der gespeicherten
          Prüfsummen geprüft. Für ältere OCR-Dateien fehlen Prüfsummen; diese Dateien sind vom
          Export ausgeschlossen. Für vollständig geprüfte Artefakte einen neuen Lauf anlegen.
        </p>
      )}
      <ConfigurationPanel
        runs={state.runs}
        runId={runId}
        run={run}
        config={state.config}
        setConfig={state.setConfig}
        selectRun={state.selectRun}
        rerun={() => state.rerun()}
        busy={state.busy}
        setNotice={state.setNotice}
      />
      {state.showUpload && (
        <UploadPanel
          upload={state.upload}
          project={state.project}
          setProject={state.setProject}
          busy={state.busy}
        />
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
            <button
              className="text-teal underline"
              onClick={() => {
                if (run.parent_id) state.selectRun(run.parent_id);
              }}
            >
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
              {
                result.regions.filter((region) => ["accept", "retain"].includes(region.status))
                  .length
              }{" "}
              menschlich entschieden.
            </p>
          </div>
          <div className="grid items-start gap-5 xl:grid-cols-[1.05fr_1fr]">
            <EvidencePanel
              key={runId}
              result={result}
              runId={runId}
              region={region}
              setRegionId={state.setRegionId}
              busy={state.busy}
              onProcessRegions={state.rerun}
              onError={state.setError}
            />
            <div className="min-w-0 space-y-4">
              <RegionQueue
                key={runId}
                regions={result.regions}
                selected={region?.id}
                onSelect={state.setRegionId}
              />
              {region && state.draft && (
                <RegionReview
                  key={`${runId}:${region.id}`}
                  region={region}
                  runId={runId}
                  reviewer={state.reviewer}
                  setReviewer={state.setReviewer}
                  onSaved={state.saved}
                  onError={state.setError}
                  draftData={state.draft}
                  onDraft={state.setDraft}
                />
              )}
            </div>
          </div>
          <OutputPanel result={result} runId={runId} view={state.view} setView={state.setView} />
        </>
      )}
    </div>
  );
}
