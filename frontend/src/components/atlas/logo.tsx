/**
 * ATLAS brand mark — a three-candle uptrend. Uses currentColor so it adapts
 * to the active theme (sidebar: text-primary; auth panels: text-primary-foreground).
 */

export function AtlasMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" role="img" aria-label="ATLAS" className={className}>
      <line x1="6" y1="4" x2="6" y2="20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <rect x="4.5" y="9" width="3" height="7" rx="1" fill="currentColor" />
      <line x1="12" y1="3" x2="12" y2="21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <rect x="10.5" y="7" width="3" height="9" rx="1" fill="currentColor" />
      <line x1="18" y1="2" x2="18" y2="19" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <rect x="16.5" y="5" width="3" height="10" rx="1" fill="currentColor" />
    </svg>
  );
}
