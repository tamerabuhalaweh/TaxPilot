export function StatusPill({ label }: { label: string }) {
  return (
    <span className="tp-pill" role="status">
      {label}
    </span>
  );
}
