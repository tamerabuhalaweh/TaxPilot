import Link from "next/link";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
  back
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  back?: { href: string; label: string; ariaLabel?: string };
}) {
  return (
    <header className="tp-page-head">
      <div className="tp-page-head-copy">
        {back ? (
          <Link className="tp-back" href={back.href} aria-label={back.ariaLabel}>
            <span aria-hidden="true">←</span>
            {back.label}
          </Link>
        ) : null}
        <h1>{title}</h1>
        {description ? <p className="tp-page-description">{description}</p> : null}
      </div>
      {actions ? <div className="tp-page-actions">{actions}</div> : null}
    </header>
  );
}
