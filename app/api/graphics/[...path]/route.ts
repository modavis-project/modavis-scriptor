import { env } from "cloudflare:workers";

async function proxy(request: Request) {
  const url = new URL(request.url);
  if (!["GET", "POST", "PATCH"].includes(request.method))
    return new Response("Method not allowed", { status: 405 });
  if (
    request.method !== "GET" &&
    request.headers.get("origin") &&
    request.headers.get("origin") !== url.origin
  ) {
    return new Response("Cross-origin writes are not allowed", { status: 403 });
  }
  const suffix = url.pathname.slice("/api/graphics".length);
  if (
    !/^\/(health|runs(?:\/[a-zA-Z0-9-]+(?:\/(image|export|rerun|regions\/r\d+\/(crop|review)))?)?)$/.test(
      suffix,
    )
  ) {
    return new Response("Not found", { status: 404 });
  }
  const base = env.GRAPHICS_API_URL || "http://127.0.0.1:8010";
  try {
    const headers = new Headers();
    for (const key of ["content-type", "content-length"]) {
      const value = request.headers.get(key);
      if (value) headers.set(key, value);
    }
    const response = await fetch(`${base}${suffix}${url.search}`, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : request.body,
    });
    const outgoing = new Headers();
    for (const key of ["content-type", "content-disposition"]) {
      const value = response.headers.get(key);
      if (value) outgoing.set(key, value);
    }
    outgoing.set("Cache-Control", "no-store");
    outgoing.set("X-Content-Type-Options", "nosniff");
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch {
    return Response.json(
      {
        detail:
          "Der lokale Grafikdienst ist nicht erreichbar. Starten Sie docker compose up -d oder den Grafikdienst auf Port 8010.",
      },
      { status: 503 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
