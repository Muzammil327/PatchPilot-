interface BrandMarkProps {
  className?: string;
}

/** PatchPilot's logo: a patch (rounded square) with a check, in the accent colour. */
export function BrandMark({ className = "size-8" }: BrandMarkProps) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect x="1" y="1" width="30" height="30" rx="8" className="fill-accent-soft stroke-accent" strokeWidth="1.5" />
      <path
        d="M10 16.5l4 4 8-9"
        fill="none"
        className="stroke-accent"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
