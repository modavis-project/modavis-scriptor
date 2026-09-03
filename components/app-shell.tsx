import type { ReactNode } from "react";
import { BookOpenText, CircleHelp, Image as ImageIcon, SlidersHorizontal } from "lucide-react";

const primary = [
  { label: "Workspace", href: "/", icon: ImageIcon },
  { label: "API", href: "/api/docs", icon: SlidersHorizontal },
];

export function AppShell({ children, active }: { children: ReactNode; active: string }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 flex h-16 items-center border-b border-border/80 bg-background/92 px-4 backdrop-blur-xl lg:px-7">
        <div className="w-60 shrink-0">
          <WordMark />
        </div>
        <div className="hidden flex-1 md:block" />
        <div className="ml-auto flex w-60 items-center justify-end gap-2">
          <a
            aria-label="Help"
            href="/api/docs"
            className="grid size-9 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <CircleHelp className="size-[18px]" />
          </a>
          <span className="flex items-center gap-2 rounded-lg px-2 py-1.5">
            <span className="grid size-8 place-items-center rounded-full bg-coral-soft text-xs font-bold text-coral">
              DR
            </span>
            <span className="hidden text-left text-xs leading-tight xl:block">
              <span className="block font-semibold">Researcher</span>
              <span className="text-muted-foreground">Lokaler Arbeitsbereich</span>
            </span>
          </span>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1680px] grid-cols-1 lg:grid-cols-[252px_minmax(0,1fr)]">
        <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] border-r border-border/80 px-4 py-6 lg:flex lg:flex-col">
          <nav aria-label="Primary navigation" className="space-y-1">
            {primary.map((item) => (
              <NavLink key={item.label} {...item} active={active === item.label} />
            ))}
          </nav>
          <div className="mt-auto space-y-1 border-t border-border pt-5">
            <NavLink
              label="API reference"
              href="/api/docs"
              icon={SlidersHorizontal}
              active={active === "API reference"}
            />
          </div>
        </aside>
        <main className="min-w-0 px-4 py-7 pb-24 sm:px-7 lg:px-10 lg:py-9">{children}</main>
      </div>

      <nav className="fixed inset-x-3 bottom-3 z-40 flex items-center justify-around rounded-2xl border border-border bg-background/95 p-2 shadow-xl backdrop-blur lg:hidden">
        {primary.map((item) => (
          <a
            key={item.label}
            href={item.href}
            aria-label={item.label}
            className={`grid size-10 place-items-center rounded-xl ${active === item.label ? "bg-ink text-paper" : "text-muted-foreground"}`}
          >
            <item.icon className="size-[18px]" />
          </a>
        ))}
      </nav>
    </div>
  );
}

function WordMark() {
  return (
    <a className="flex items-center gap-3" href="/" aria-label="MODAVIS Scriptor home">
      <span className="grid size-9 place-items-center rounded-[10px] bg-ink text-paper shadow-sm">
        <BookOpenText className="size-[18px]" strokeWidth={1.7} />
      </span>
      <span>
        <span className="block font-serif text-[19px] font-semibold leading-none tracking-[-0.02em]">
          MODAVIS Scriptor
        </span>
        <span className="mt-1 block text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Research transcription
        </span>
      </span>
    </a>
  );
}

function NavLink({
  label,
  href,
  icon: Icon,
  active,
}: {
  label: string;
  href: string;
  icon: typeof ImageIcon;
  active: boolean;
}) {
  return (
    <a
      href={href}
      className={`flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition ${
        active
          ? "bg-ink text-paper shadow-sm"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      <Icon className="size-[17px]" strokeWidth={1.8} />
      {label}
    </a>
  );
}
