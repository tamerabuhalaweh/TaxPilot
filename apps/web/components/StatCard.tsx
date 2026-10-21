import { Icon, type IconName } from "./Icon";

export function StatCard({
  label,
  value,
  hint,
  icon
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: IconName;
}) {
  return (
    <div className="tp-card tp-stat">
      {icon ? (
        <span className="tp-stat-icon">
          <Icon name={icon} />
        </span>
      ) : null}
      <div className="tp-stat-copy">
        <div className="tp-stat-value">{value}</div>
        <div className="tp-stat-label">{label}</div>
        {hint ? <div className="tp-stat-hint">{hint}</div> : null}
      </div>
    </div>
  );
}
