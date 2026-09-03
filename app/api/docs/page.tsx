import { AppShell } from "@/components/app-shell";

const routes = [
  ["GET", "/api/graphics/health", "Service status and corpus provenance"],
  ["GET / POST", "/api/graphics/runs", "List runs or upload an image"],
  ["GET", "/api/graphics/runs/{id}", "Run, immutable OCR, review state and paradata"],
  ["POST", "/api/graphics/runs/{id}/rerun", "Create a derived processing run"],
  ["GET", "/api/graphics/runs/{id}/image", "EXIF-normalized evidence image"],
  ["GET", "/api/graphics/runs/{id}/regions/{region}/crop", "Unmodified region crop"],
  [
    "PATCH",
    "/api/graphics/runs/{id}/regions/{region}/review",
    "Append a rationale-bearing review event",
  ],
  [
    "GET",
    "/api/graphics/runs/{id}/export?format=json|markdown|raw-markdown|csv|bundle",
    "Research exports",
  ],
];

export default function ApiDocs() {
  return (
    <AppShell active="API">
      <article className="mx-auto max-w-5xl space-y-6">
        <header>
          <p className="eyebrow">Version 0.1.0</p>
          <h1 className="mt-2 font-serif text-4xl font-semibold">API reference</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
            The web API proxies the local processing service. The complete OpenAPI document is
            available at{" "}
            <a className="text-teal underline" href="http://127.0.0.1:8010/docs">
              127.0.0.1:8010/docs
            </a>
            .
          </p>
        </header>
        <div className="surface-panel overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b">
                <th className="p-4">Method</th>
                <th className="p-4">Path</th>
                <th className="p-4">Purpose</th>
              </tr>
            </thead>
            <tbody>
              {routes.map(([method, path, purpose]) => (
                <tr className="border-b last:border-0" key={path}>
                  <td className="p-4 font-semibold">{method}</td>
                  <td className="p-4 font-mono text-xs">{path}</td>
                  <td className="p-4">{purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </AppShell>
  );
}
