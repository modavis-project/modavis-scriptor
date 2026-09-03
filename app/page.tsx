import { AppShell } from "@/components/app-shell";
import { GraphicsWorkbench } from "@/components/graphics-workbench";

export default function Home() {
  return (
    <AppShell active="Workspace">
      <GraphicsWorkbench initialRunId="example-organ-stops-v1" />
    </AppShell>
  );
}
