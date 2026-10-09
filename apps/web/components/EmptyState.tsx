export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="tp-card" role="status" aria-live="polite">
      <h2>{title}</h2>
      {hint ? <p className="tp-muted">{hint}</p> : null}
    </div>
  );
}
