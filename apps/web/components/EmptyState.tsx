import { Icon, type IconName } from "./Icon";

export function EmptyState({
  title,
  hint,
  icon = "file",
  action
}: {
  title: string;
  hint?: string;
  icon?: IconName;
  action?: React.ReactNode;
}) {
  return (
    <div className="tp-empty" role="status" aria-live="polite">
      <span className="tp-empty-icon">
        <Icon name={icon} size={24} />
      </span>
      <div>
        <h2>{title}</h2>
        {hint ? <p>{hint}</p> : null}
        {action ? <div className="tp-actions">{action}</div> : null}
      </div>
    </div>
  );
}
