import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Toaster } from "@/components/ui/sonner";
import { AppSidebar } from "@/components/gestao/AppSidebar";
import { ContratosSection } from "@/components/gestao/ContratosSection";
import { CobrancasSection } from "@/components/gestao/CobrancasSection";
import { AguaSection } from "@/components/gestao/AguaSection";
import { ManutencaoSection } from "@/components/gestao/ManutencaoSection";
import { RenovacoesSection } from "@/components/gestao/RenovacoesSection";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "GestãoImob — Sistema de Gestão Imobiliária e de Contratos" },
      {
        name: "description",
        content:
          "Gerencie contratos, cobranças, consumo de água, manutenção e renovações em um único painel moderno e integrado.",
      },
      { property: "og:title", content: "GestãoImob — Gestão Imobiliária" },
      {
        property: "og:description",
        content:
          "Painel completo para administradoras: contratos, negociações, água, manutenção e renovações.",
      },
    ],
  }),
  component: Index,
});

export type SectionKey =
  | "contratos"
  | "cobrancas"
  | "agua"
  | "manutencao"
  | "renovacoes";

function Index() {
  const [section, setSection] = useState<SectionKey>("contratos");

  return (
    <div className="flex min-h-screen w-full bg-muted/30">
      <AppSidebar current={section} onChange={setSection} />
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-10">
          {section === "contratos" && <ContratosSection />}
          {section === "cobrancas" && <CobrancasSection />}
          {section === "agua" && <AguaSection />}
          {section === "manutencao" && <ManutencaoSection />}
          {section === "renovacoes" && <RenovacoesSection />}
        </div>
      </main>
      <Toaster richColors position="top-right" />
    </div>
  );
}
