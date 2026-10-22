type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export function StatusPill({ label, tone = "info" }: { label: string; tone?: Tone }) {
  return (
    <span className={`tp-pill tp-pill-${tone}`} role="status">
      {label}
    </span>
  );
}
