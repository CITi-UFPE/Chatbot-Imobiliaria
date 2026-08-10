import { useState } from "react";
import { Building2, Eye, EyeOff, Loader2, Mail, Lock, LayoutGrid, Wallet, FileCheck2, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";
import predioImg from "@/assets/predio-ilustracao.jpg";

// Só decorativo — texto e ícones de apoio visual no painel do login, sem
// link/ação nenhuma por trás (não são funcionalidades reais do produto).
const FEATURE_HIGHLIGHTS = [
  { icon: LayoutGrid, label: "Visão completa dos imóveis" },
  { icon: Wallet, label: "Controle financeiro inteligente" },
  { icon: FileCheck2, label: "Contratos e documentos organizados" },
  { icon: Wrench, label: "Manutenção sob controle" },
];

export function LoginScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      toast.error("Preencha e-mail e senha");
      return;
    }
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) {
      toast.error(error.message || "Não foi possível autenticar. Verifique suas credenciais.");
      return;
    }
    // O App reage via supabase.auth.onAuthStateChange — não precisamos
    // navegar/setar estado manualmente aqui.
    toast.success("Login efetuado com sucesso");
  };

  return (
    <div className="min-h-screen w-full grid md:grid-cols-[minmax(0,26rem)_1fr] bg-background">
      <div className="flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="h-14 w-14 rounded-2xl bg-primary flex items-center justify-center shadow-sm">
            <Building2 className="h-7 w-7 text-primary-foreground" />
          </div>
          <h1 className="mt-4 text-2xl font-serif font-medium">GestãoImob</h1>
          <p className="text-sm text-muted-foreground">Painel Administrativo</p>
        </div>

        <div className="bg-background border rounded-xl shadow-sm p-6 md:p-8">
          <h2 className="text-lg font-semibold">Entrar na sua conta</h2>
          <p className="text-sm text-muted-foreground mb-6">
            Acesse com suas credenciais de administrador.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">E-mail</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="voce@empresa.com"
                  className="pl-9"
                />
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Senha</Label>
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => toast.info("Contate o administrador para redefinir a senha.")}
                >
                  Esqueceu a senha?
                </button>
              </div>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="pl-9 pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Entrar"}
            </Button>
          </form>
        </div>

        <p className="text-center text-xs text-muted-foreground mt-6">
          v1.0 · Acesso restrito à equipe autorizada
        </p>
      </div>
      </div>

      {/* Painel decorativo — só ilustração/tagline de marca, sem nenhum dado
          ou funcionalidade real por trás (nada aqui reflete o banco). Some
          no mobile (md:grid-cols acima já reserva essa coluna só a partir de
          md). Imagem enviada pelo Davi (frontend/src/assets/predio-ilustracao.jpg)
          cobrindo o painel inteiro, com um degradê por cima só onde tem
          texto, pra manter a leitura. */}
      <div className="hidden md:flex flex-col relative overflow-hidden bg-warm-gradient-strong px-12 py-10">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${predioImg})` }}
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, var(--ink-50) 0%, color-mix(in oklab, var(--ink-50) 65%, transparent) 32%, transparent 55%), linear-gradient(to top, var(--ink-50) 0%, color-mix(in oklab, var(--ink-50) 75%, transparent) 22%, transparent 45%)",
          }}
        />

        <div className="relative max-w-md">
          <p className="font-serif text-3xl font-medium text-foreground leading-tight">
            Simplifique a gestão{" "}
            <span style={{ color: "var(--brand)" }}>dos seus imóveis.</span>
          </p>
          <p className="text-sm text-muted-foreground mt-3 max-w-sm">
            Contratos, cobranças, manutenção e reajustes — tudo centralizado em um só painel.
          </p>
        </div>

        <div className="relative flex flex-wrap gap-x-8 gap-y-4 mt-auto">
          {FEATURE_HIGHLIGHTS.map(({ icon: Icon, label }) => (
            <div key={label} className="flex items-center gap-2.5">
              <div
                className="h-9 w-9 shrink-0 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: "var(--brand-soft)", color: "var(--brand-strong)" }}
              >
                <Icon className="h-4 w-4" />
              </div>
              <span className="text-xs font-medium text-foreground/80 leading-tight">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
