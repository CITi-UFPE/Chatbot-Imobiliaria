import { useState } from "react";
import { Building2, Eye, EyeOff, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";

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
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="voce@empresa.com"
              />
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
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="pr-10"
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

      {/* Painel decorativo — só imagem/tagline de marca, sem nenhum dado ou
          funcionalidade real por trás (nada aqui reflete o banco). Some no
          mobile (md:grid-cols acima já reserva essa coluna só a partir de md). */}
      <div className="hidden md:block relative overflow-hidden bg-primary">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage:
              "url('https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1400&q=80')",
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 to-black/60" />
        <div className="absolute left-10 right-10 bottom-10">
          <p className="font-serif text-2xl font-medium text-white leading-tight max-w-sm">
            Simplifique a gestão dos seus imóveis.
          </p>
          <p className="text-sm text-white/80 mt-2 max-w-xs">
            Contratos, cobranças, manutenção e reajustes — tudo centralizado em um só painel.
          </p>
        </div>
      </div>
    </div>
  );
}
