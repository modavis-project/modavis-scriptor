"use client";

import { lazy, Suspense } from "react";
import { Download } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Result } from "@/lib/graphics/types";
const MarkdownRenderer = lazy(() =>
  import("@/components/markdown-renderer").then((module) => ({ default: module.MarkdownRenderer })),
);

export function OutputPanel({
  result,
  runId,
  view,
  setView,
}: {
  result: Result;
  runId: string;
  view: string;
  setView: (view: string) => void;
}) {
  return (
    <Suspense fallback={<p role="status">Markdown wird geladen…</p>}>
      <section className="surface-panel min-w-0 p-5">
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
    </Suspense>
  );
}
