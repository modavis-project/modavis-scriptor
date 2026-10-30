import {
  isConfig_Input,
  isGraphicsResult,
  isQueuedRunResponse,
  isReview_Input,
  isRunListResponse,
  isRunResponse,
  isErrorResponse,
  type Config_Input,
  type Review_Input,
} from "./contracts.generated.js";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: "http" | "contract" | "network",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Die Anfrage konnte nicht verarbeitet werden.";
}

function serverMessage(value: unknown, fallback: string): string {
  if (!isErrorResponse(value)) return fallback;
  if (typeof value.detail === "string") return value.detail;
  return value.detail.map((issue) => `${issue.loc.join(".")}: ${issue.msg}`).join("; ");
}

export async function request<T>(
  path: string,
  guard: (value: unknown) => value is T,
  options?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/graphics${path}`, options);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError("Der lokale Grafikdienst ist nicht erreichbar.", 0, "network");
  }
  const body = await response.text();
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    if (!response.ok)
      throw new ApiError(
        `Grafikdienst: HTTP ${response.status}${response.headers.get("content-type")?.startsWith("text/plain") && body.length < 1000 ? ` · ${body}` : ""}`,
        response.status,
        "http",
      );
    throw new ApiError(
      "Ungültige Antwort des Grafikdiensts: JSON erwartet.",
      response.status,
      "contract",
    );
  }
  if (!response.ok)
    throw new ApiError(
      serverMessage(value, `Grafikdienst: HTTP ${response.status}`),
      response.status,
      "http",
    );
  if (!guard(value))
    throw new ApiError(
      "Die Antwort des Grafikdiensts entspricht nicht dem API-Vertrag. Bitte Versionen und Dienstprotokoll prüfen.",
      response.status,
      "contract",
    );
  return value;
}

function jsonOptions(method: string, value: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) };
}

export const graphicsApi = {
  list(signal?: AbortSignal) {
    return request("/runs", isRunListResponse, { signal });
  },
  run(id: string, signal?: AbortSignal) {
    return request(`/runs/${encodeURIComponent(id)}`, isRunResponse, { signal });
  },
  upload(form: FormData) {
    return request("/runs", isQueuedRunResponse, { method: "POST", body: form });
  },
  rerun(id: string, config: Config_Input) {
    if (!isConfig_Input(config))
      throw new ApiError(
        "Ungültige Verarbeitungseinstellungen oder Regionskoordinaten.",
        0,
        "contract",
      );
    return request(
      `/runs/${encodeURIComponent(id)}/rerun`,
      isQueuedRunResponse,
      jsonOptions("POST", config),
    );
  },
  review(id: string, regionId: string, decision: Review_Input) {
    if (!isReview_Input(decision))
      throw new ApiError(
        "Ungültige Entscheidung: Identität, Begründung und Felder prüfen.",
        0,
        "contract",
      );
    return request(
      `/runs/${encodeURIComponent(id)}/regions/${encodeURIComponent(regionId)}/review`,
      isGraphicsResult,
      jsonOptions("PATCH", decision),
    );
  },
};
