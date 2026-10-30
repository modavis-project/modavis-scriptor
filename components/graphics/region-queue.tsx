"use client";
import { useState } from "react";
import type { Region } from "@/lib/graphics/types";
import { Pick, statusLabel } from "./shared";

export function RegionQueue({
  regions,
  selected,
  onSelect,
}: {
  regions: Region[];
  selected?: string;
  onSelect: (id: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const shown = regions.filter(
    (region) => filter === "all" || region.status === "unreviewed" || region.status === "defer",
  );
  return (
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
        {shown.map((region) => (
          <button
            key={region.id}
            onClick={() => onSelect(region.id)}
            aria-pressed={region.id === selected}
            className={`rounded-lg border px-3 py-2 text-sm ${region.id === selected ? "border-teal bg-teal-soft text-teal" : "border-stone-200 hover:bg-stone-50"}`}
          >
            {region.number}. {region.effective.name || "Keine Lesung"}{" "}
            <span className="text-xs">· {statusLabel[region.status]}</span>
          </button>
        ))}
        {!shown.length && <p className="text-sm">Keine offenen Regionen.</p>}
      </div>
    </div>
  );
}
