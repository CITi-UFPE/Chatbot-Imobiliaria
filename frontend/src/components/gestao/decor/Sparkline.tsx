// Squiggle decorativo pros StatTile — puramente estético, o traçado é
// estático (não plota nenhuma série real). Cor herda de currentColor pra
// combinar com o tom (tone) do tile que o usa.
export function Sparkline({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 20"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M1 14 C 8 14, 8 6, 15 6 S 22 16, 29 16 S 36 4, 43 4 S 50 12, 57 10"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
      <circle cx="57" cy="10" r="2.5" fill="currentColor" opacity="0.8" />
    </svg>
  );
}
