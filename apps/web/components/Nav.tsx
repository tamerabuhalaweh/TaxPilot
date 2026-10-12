"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { t, type Locale } from "../lib/i18n";

const ITEMS = [
  { href: "/", key: "nav.dashboard" },
  { href: "/clients", key: "nav.clients" },
  { href: "/reviews", key: "nav.reviews" },
  { href: "/reports", key: "nav.reports" },
  { href: "/settings", key: "nav.settings" }
] as const;

/** Primary navigation. Reviews/Reports/Settings have no backend yet and land on
 * honest preview-only screens rather than dead links. */
export function Nav({ locale }: { locale: Locale }) {
  const pathname = usePathname();
  return (
    <nav className="tp-nav" aria-label="primary">
      {ITEMS.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={active ? "tp-nav-active" : undefined}
          >
            {t(locale, item.key)}
          </Link>
        );
      })}
    </nav>
  );
}
