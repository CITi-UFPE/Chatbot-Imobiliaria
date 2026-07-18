import { FileText, HandCoins, Droplets, Wrench, RefreshCw, Building2, Menu, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { SectionKey } from "@/routes/index";

const items: { key: SectionKey; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "contratos", label: "Contratos", icon: FileText },
  { key: "cobrancas", label: "Cobranças em Negociação", icon: HandCoins },
  { key: "agua", label: "Consumo de Água", icon: Droplets },
  { key: "manutencao", label: "Manutenção", icon: Wrench },
  { key: "renovacoes", label: "Renovações e Reajustes", icon: RefreshCw },
];

export function AppSidebar({
  current,
  onChange,
}: {
  current: SectionKey;
  onChange: (k: SectionKey) => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 inset-x-0 z-40 flex items-center justify-between bg-background border-b px-4 h-14">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
            <Building2 className="h-5 w-5 text-primary-foreground" />
          </div>
          <span className="font-serif font-medium">GestãoImob</span>
        </div>
        <button
          onClick={() => setMobileOpen((v) => !v)}
          className="p-2 rounded-md hover:bg-muted"
          aria-label="Abrir menu"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>
      <div className="md:hidden h-14" />

      {/* Sidebar */}
      <aside
        className={cn(
          "z-30 bg-background border-r flex-col w-64 shrink-0",
          "fixed md:sticky top-0 md:top-0 md:h-screen h-[calc(100vh-3.5rem)] mt-14 md:mt-0",
          "transition-transform md:transition-none",
          mobileOpen ? "flex translate-x-0" : "hidden md:flex -translate-x-full md:translate-x-0",
        )}
      >
        <div className="hidden md:flex items-center gap-2 px-6 h-16 border-b">
          <div className="h-9 w-9 rounded-lg bg-primary flex items-center justify-center">
            <Building2 className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <div className="font-serif font-medium leading-tight">GestãoImob</div>
            <div className="text-xs text-muted-foreground">Painel Administrativo</div>
          </div>
        </div>

        <nav className="p-3 space-y-1 flex-1 overflow-y-auto">
          {items.map((item) => {
            const active = current === item.key;
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                onClick={() => {
                  onChange(item.key);
                  setMobileOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="text-left">{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Cartão decorativo — só imagem/legenda genérica, não representa
            nenhum imóvel real do banco nem tem ação clicável. */}
        <div className="mx-3 mb-4 rounded-xl overflow-hidden border bg-card">
          <div
            className="h-24 w-full bg-cover bg-center bg-muted"
            style={{
              backgroundImage:
                "url('https://images.unsplash.com/photo-1560518883-ce09059eeffa?auto=format&fit=crop&w=600&q=80')",
            }}
          />
          <div className="px-3 py-2.5 text-xs text-muted-foreground">
            Gestão simplificada, em um só lugar.
          </div>
        </div>

        <div className="p-4 border-t text-xs text-muted-foreground">
          <div className="font-medium text-foreground">Admin Imobiliária</div>
          <div>v1.0 · Mock Data</div>
        </div>
      </aside>
    </>
  );
}
