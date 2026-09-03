import { AppShell } from "@/components/app-shell";
import { GraphicsWorkbench } from "@/components/graphics-workbench";

export default async function GraphicsPage({
  searchParams,
}: {
  searchParams: Promise<{ run?: string }>;
}) {
  const params = await searchParams;
  const initialRunId =
    params.run && /^[a-zA-Z0-9-]+$/.test(params.run) ? params.run : "example-organ-stops-v1";
  return (
    <AppShell active="Workspace">
      <GraphicsWorkbench initialRunId={initialRunId} />
    </AppShell>
  );
}
