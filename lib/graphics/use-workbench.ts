"use client";
import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import { graphicsApi, errorMessage } from "./api";
import { defaultConfig } from "./contracts.generated";
import type { Box, Config, RegionDraft, Result, Run, RunSummary } from "./types";

/** Own run loading/mutations; view components receive validated data and explicit actions. */
export function useWorkbench(initialRunId: string) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState(initialRunId);
  const activeRun = useRef(initialRunId);
  const [run, setRun] = useState<Run | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [regionId, setRegionId] = useState("r001");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<Config>(defaultConfig);
  const [project, setProject] = useState("Organ-stop images");
  const [showUpload, setShowUpload] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [view, setView] = useState("effective");
  const [reload, setReload] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, RegionDraft>>({});
  const region = result?.regions.find((region) => region.id === regionId) ?? result?.regions[0];
  const draft = region
    ? (drafts[region.id] ?? {
        fields: region.effective,
        rationale: "",
        candidateId: null,
        expectedVersion: region.version,
      })
    : null;

  function selectRun(id: string) {
    activeRun.current = id;
    setRunId(id);
    setResult(null);
    setRun(null);
    setDrafts({});
    setRegionId("r001");
    window.history.replaceState(null, "", `/graphics?run=${encodeURIComponent(id)}`);
  }

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const [list, data] = await Promise.all([
          graphicsApi.list(controller.signal),
          graphicsApi.run(runId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setRuns(list.runs);
        setRun(data.run);
        setResult(data.result);
        setError("");
        if (data.run.status === "queued" || data.run.status === "running")
          timer = setTimeout(load, 2000);
      } catch (error) {
        if (!controller.signal.aborted) setError(errorMessage(error));
      }
    };
    void load();
    return () => {
      controller.abort();
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
    const metadata = Object.fromEntries(
      ["creator", "source_url", "license", "license_url", "attribution"].map((key) => {
        const value = form.get(key);
        return [key, typeof value === "string" ? value : ""];
      }),
    );
    form.set("metadata", JSON.stringify(metadata));
    try {
      const data = await graphicsApi.upload(form);
      selectRun(data.id);
      setShowUpload(false);
      setNotice("Bild gespeichert. Die Verarbeitung läuft lokal.");
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function rerun(regions: Box[] = []) {
    setBusy(true);
    setError("");
    try {
      const data = await graphicsApi.rerun(runId, { ...config, regions });
      selectRun(data.id);
      setNotice("Neuer Lauf angelegt; bisherige OCR und Entscheidungen bleiben unverändert.");
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function saved(data: Result) {
    if (data.run_id !== activeRun.current) return;
    setResult(data);
    if (region)
      setDrafts((previous) =>
        Object.fromEntries(Object.entries(previous).filter(([id]) => id !== region.id)),
      );
    setView("effective");
    setNotice("Entscheidung gespeichert. Die vollständige Markdown-Tabelle wurde aktualisiert.");
  }

  return {
    runs,
    runId,
    run,
    result,
    region,
    regionId,
    setRegionId,
    error,
    setError,
    notice,
    setNotice,
    busy,
    config,
    setConfig,
    project,
    setProject,
    showUpload,
    setShowUpload,
    reviewer,
    setReviewer,
    view,
    setView,
    draft,
    setDraft: (value: RegionDraft) => {
      if (region) setDrafts((previous) => ({ ...previous, [region.id]: value }));
    },
    selectRun,
    upload,
    rerun,
    saved,
    reload: () => setReload((value) => value + 1),
  };
}
