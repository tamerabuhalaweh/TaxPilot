export function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="tp-card tp-stat">
      <div className="tp-stat-value">{value}</div>
      <div className="tp-stat-label">{label}</div>
      {hint ? <div className="tp-muted">{hint}</div> : null}
    </div>
  );
}
