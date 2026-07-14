// Client Supabase único do frontend — usa a Publishable key (equivalente
// segura da antiga "anon key"): RLS continua valendo do mesmo jeito, é
// seguro expor no bundle do client.
//
// A sessão de autenticação (login da gestora/staff) é responsabilidade da
// tela de login feita no Lovable — este client só assume que, quando existir
// uma sessão válida, o Supabase Auth já injeta o JWT em todas as chamadas
// automaticamente. As políticas de RLS (staff_full_access, via is_staff())
// cuidam do resto: sem sessão de staff válida, as queries abaixo retornam
// vazio em vez de erro — não confie em "veio vazio" como "não existe".
import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseKey) {
  throw new Error(
    "VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY precisam estar definidas no .env " +
      "(copie frontend/.env.example para frontend/.env e preencha com os valores do projeto Supabase).",
  );
}

export const supabase = createClient(supabaseUrl, supabaseKey);

// Só em modo dev (eliminado do build de produção pelo Vite): expõe o client
// no console do navegador pra dar login de teste sem depender da tela de
// login de verdade (feita separadamente no Lovable). Uso:
//   await supabase.auth.signInWithPassword({ email: "...", password: "..." })
if (import.meta.env.DEV && typeof window !== "undefined") {
  (window as unknown as { supabase: typeof supabase }).supabase = supabase;
}
