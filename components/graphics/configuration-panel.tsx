"use client";

import { RefreshCw } from "lucide-react";
import type { Config, Run, RunSummary } from "@/lib/graphics/types";
import { defaultConfig as initialConfig } from "@/lib/graphics/contracts.generated";
import { Pick, fieldClass, statusLabel } from "./shared";

export function ConfigurationPanel({
  runs,
  runId,
  run,
  config,
  setConfig,
  selectRun,
  rerun,
  busy,
  setNotice,
}: {
  runs: RunSummary[];
  runId: string;
  run: Run | null;
  config: Config;
  setConfig: (value: Config) => void;
  selectRun: (id: string) => void;
  rerun: () => Promise<void>;
  busy: boolean;
  setNotice: (value: string) => void;
}) {
  return (
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
          onClick={() => void rerun()}
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
  );
}
