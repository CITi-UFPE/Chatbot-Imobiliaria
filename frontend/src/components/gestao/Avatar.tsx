// Círculo de iniciais — puramente apresentacional, espelha o Avatar do
// "GestãoImob Design System". Recebe o nome real (ex: inquilino_nome) e só
// deriva as iniciais pra exibição; não busca nem inventa nenhum dado.
export function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

  return (
    <div
      className="shrink-0 rounded-full bg-[var(--avatar-bg)] text-[var(--avatar-fg)] flex items-center justify-center font-semibold"
      style={{ height: size, width: size, fontSize: size * 0.38 }}
    >
      {initials}
    </div>
  );
}
