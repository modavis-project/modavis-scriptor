"use client";

import type { SyntheticEvent } from "react";
import { Play } from "lucide-react";
import { fieldClass } from "./shared";

export function UploadPanel({
  upload,
  project,
  setProject,
  busy,
}: {
  upload: (event: SyntheticEvent<HTMLFormElement>) => Promise<void>;
  project: string;
  setProject: (value: string) => void;
  busy: boolean;
}) {
  return (
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
        Die Datei wird ausschließlich im lokalen Grafikdienst gespeichert. Fehlende Rechteangaben
        werden nicht ergänzt.
      </p>
      <button disabled={busy} className="primary-action" type="submit">
        <Play className="size-4" /> Speichern und verarbeiten
      </button>
    </form>
  );
}
