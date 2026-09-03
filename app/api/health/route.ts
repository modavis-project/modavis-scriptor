export async function GET() {
  return Response.json(
    {
      ok: true,
      service: "modavis-scriptor-web",
      version: "0.1.0",
    },
    { headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } },
  );
}
