import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { AppSidebar } from "@/components/gestao/AppSidebar";
import { ContratosSection } from "@/components/gestao/ContratosSection";
import { CobrancasSection } from "@/components/gestao/CobrancasSection";
import { AguaSection } from "@/components/gestao/AguaSection";
import { ManutencaoSection } from "@/components/gestao/ManutencaoSection";
import { ReajustesSection } from "@/components/gestao/ReajustesSection";
import { RenovacaoSection } from "@/components/gestao/RenovacaoSection";
import { LoginScreen } from "@/components/gestao/LoginScreen";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "GestãoImob — Sistema de Gestão Imobiliária e de Contratos" },
      {
        name: "description",
        content:
          "Gerencie contratos, cobranças, consumo de água, manutenção, reajustes e renovações em um único painel moderno e integrado.",
      },
      { property: "og:title", content: "GestãoImob — Gestão Imobiliária" },
      {
        property: "og:description",
        content:
          "Painel completo para administradoras: contratos, negociações, água, manutenção, reajustes e renovações.",
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
  | "reajustes"
  | "renovacao";

function Index() {
  const [section, setSection] = useState<SectionKey>("contratos");
  const [user, setUser] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user.email ?? null);
      setHydrated(true);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user.email ?? null);
      setHydrated(true);
    });

    return () => subscription.unsubscribe();
  }, []);

  const handleLogout = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) {
      toast.error(error.message || "Não foi possível encerrar a sessão.");
      return;
    }
    toast.success("Sessão encerrada");
  };

  if (!hydrated) return null;

  if (!user) {
    return (
      <>
        <LoginScreen />
        <Toaster richColors position="top-right" />
      </>
    );
  }

  return (
    <div className="flex min-h-screen w-full bg-muted/30">
      <AppSidebar current={section} onChange={setSection} />
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-10">
          <div className="flex items-center justify-end mb-4 gap-3">
            <span className="text-sm text-muted-foreground hidden sm:inline">{user}</span>
            <Button variant="outline" size="sm" onClick={handleLogout}>
              <LogOut className="h-4 w-4 mr-2" />
              Sair
            </Button>
          </div>
          {section === "contratos" && <ContratosSection />}
          {section === "cobrancas" && <CobrancasSection />}
          {section === "agua" && <AguaSection />}
          {section === "manutencao" && <ManutencaoSection />}
          {section === "reajustes" && <ReajustesSection />}
          {section === "renovacao" && <RenovacaoSection />}
        </div>
      </main>
      <Toaster richColors position="top-right" />
    </div>
  );
}