"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./Icon";
import { t, type Locale } from "../lib/i18n";

const ITEMS: { href: string; key: string; icon: IconName }[] = [
  { href: "/", key: "nav.dashboard", icon: "dashboard" },
  { href: "/clients", key: "nav.clients", icon: "clients" },
  { href: "/reviews", key: "nav.reviews", icon: "reviews" },
  { href: "/reports", key: "nav.reports", icon: "reports" },
  { href: "/settings", key: "nav.settings", icon: "settings" }
];

/** Primary navigation. Nested routes highlight their section parent (e.g.
/clients/123 highlights Clients); the dashboard is active at "/" only. */
export function Nav({ locale }: { locale: Locale }) {
  const pathname = usePathname();
  const isActive = (href: string): boolean =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");
  return (
    <nav className="tp-nav" aria-label="primary">
      {ITEMS.map((item) => {
        const active = isActive(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={active ? "tp-nav-active" : undefined}
          >
            <Icon name={item.icon} />
            <span>{t(locale, item.key)}</span>
          </Link>
        );
      })}
    </nav>
  );
}
