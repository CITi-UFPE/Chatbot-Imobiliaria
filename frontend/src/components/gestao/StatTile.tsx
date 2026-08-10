import type { ReactNode } from "react";
import { Sparkline } from "@/components/gestao/decor/Sparkline";

// Puramente apresentacional (sem estado, sem fetch) — espelha o StatCard do
// "GestãoImob Design System" (Claude Design). Quem chama decide o valor;
// este componente só formata. Nunca inventar número aqui dentro.
const TONE_CLASSES: Record<"a" | "b" | "c" | "d", string> = {
  a: "bg-[var(--tile-a-bg)] text-[var(--tile-a-fg)]",
  b: "bg-[var(--tile-b-bg)] text-[var(--tile-b-fg)]",
  c: "bg-[var(--tile-c-bg)] text-[var(--tile-c-fg)]",
  d: "bg-[var(--tile-d-bg)] text-[var(--tile-d-fg)]",
};

export function StatTile({
  icon,
  label,
  value,
  sublabel,
  tone = "a",
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
  sublabel?: string;
  tone?: "a" | "b" | "c" | "d";
}) {
  return (
    <div className="flex flex-col gap-3 bg-card border rounded-xl shadow-sm p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-medium text-muted-foreground">{label}</div>
        <div
          className={`h-10 w-10 shrink-0 rounded-lg flex items-center justify-center ${TONE_CLASSES[tone]}`}
        >
          {icon}
        </div>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="text-2xl font-bold tracking-tight tnum">{value}</div>
          {sublabel && <div className="text-xs text-muted-foreground mt-0.5">{sublabel}</div>}
        </div>
        {/* Decorativo — não reflete série histórica real, só reforça a
            leitura visual do tile (mesmo tom do ícone). */}
        <Sparkline className={`h-5 w-14 shrink-0 mb-0.5 ${TONE_CLASSES[tone].split(" ")[1]}`} />
      </div>
    </div>
  );
}
