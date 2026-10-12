"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { DemoBanner, PreviewOnly } from "../components/Preview";
import { useLocale } from "../components/LocaleProvider";
import { LocaleControls } from "../components/LocaleControls";
import { Nav } from "../components/Nav";
import { StatCard } from "../components/StatCard";
import { StatusPill } from "../components/StatusPill";
import { EmptyState } from "../components/EmptyState";
import {
  ApiRequestError,
  fetchHealth,
  fetchMe,
  listClients,
  logout,
  type ClientPayload,
  type MePayload
} from "../lib/api";
import { DEMO_CLIENTS, DEMO_FIRM, DEMO_REVIEWS } from "../lib/demo-data";
import { t } from "../lib/i18n";
import { isDemoMode } from "../lib/preview";

type LoadState = "checking" | "down" | "signed-out" | "ready";

/** Firm dashboard: navigation, firm overview, clients, and review status. */
export default function DashboardPage() {
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<LoadState>("checking");
  const [me, setMe] = useState<MePayload | null>(null);
  const [clients, setClients] = useState<ClientPayload[]>([]);

  useEffect(() => {
    if (isDemoMode()) {
      setState("ready");
      return;
    }
    const ctrl = new AbortController();
    (async () => {
      try {
        await fetchHealth(ctrl.signal);
      } catch {
        setState("down");
        return;
      }
      try {
        const profile = await fetchMe(ctrl.signal);
        setMe(profile);
        setClients(await listClients());
        setState("ready");
      } catch (err) {
        setState(err instanceof ApiRequestError && err.status === 401 ? "signed-out" : "down");
      }
    })();
    return () => ctrl.abort();
  }, []);

  async function signOut(): Promise<void> {
    await logout();
    window.location.href = "/login";
  }

  const demo = isDemoMode();
  const firmName = demo ? (locale === "ar" ? DEMO_FIRM.nameAr : DEMO_FIRM.name) : me?.email.split("@")[0];
  const activeReviews = demo ? DEMO_REVIEWS.filter((r) => r.status === "in_progress").length : 0;
  const doneReviews = demo ? DEMO_REVIEWS.filter((r) => r.status === "approved").length : 0;
  // Connected mode has no review engine yet: metrics are honestly unavailable,
  // never a measured zero. Demo fixtures are explicitly synthetic (see banner).
  const stats = demo
    ? [
        { label: t(locale, "dashboard.activeReviews"), value: String(activeReviews) },
        { label: t(locale, "dashboard.awaitingAction"), value: "1" },
        { label: t(locale, "dashboard.highPriority"), value: "0" },
        { label: t(locale, "dashboard.recentlyCompleted"), value: String(doneReviews) }
      ]
    : [
        { label: t(locale, "dashboard.activeReviews"), value: "—", hint: t(locale, "dashboard.comingSoon") },
        { label: t(locale, "dashboard.awaitingAction"), value: "—", hint: t(locale, "dashboard.comingSoon") },
        { label: t(locale, "dashboard.highPriority"), value: "—", hint: t(locale, "dashboard.comingSoon") },
        {
          label: t(locale, "dashboard.recentlyCompleted"),
          value: "—",
          hint: t(locale, "dashboard.comingSoon")
        }
      ];
  interface ClientRow {
    id: string;
    name: string;
    detail: string;
    count: number;
  }
  const shownClients: ClientRow[] = demo
    ? DEMO_CLIENTS.filter((c) => c.status === "active").map((c) => ({
        id: c.id,
        name: locale === "ar" ? c.nameAr : c.name,
        detail: locale === "ar" ? c.sectorAr : c.sector,
        count: c.activeReviews
      }))
    : clients
        .filter((c) => c.status === "active")
        .map((c) => ({ id: c.id, name: c.name, detail: c.sector ?? "—", count: 0 }));

  return (
    <main>
      <div className="tp-topbar">
        <Link href="/" className="tp-brand">
          TaxPilot
        </Link>
        <Nav locale={locale} />
        <LocaleControls locale={locale} onChange={setLocale} />
      </div>
      <DemoBanner locale={locale} />
      <p className="tp-muted">{t(locale, "app.tagline")}</p>
      <h1>{t(locale, "dashboard.title")}</h1>

      {state === "checking" && <StatusPill label={t(locale, "health.checking")} />}
      {state === "down" && <Alert message={t(locale, "health.backendDown")} />}
      {state === "signed-out" && !demo && (
        <div className="tp-actions">
          <EmptyState title={t(locale, "dashboard.signinRequired")} hint={t(locale, "dashboard.signinRequiredHint")} />
          <Link href="/login" className="tp-primary">
            {t(locale, "dashboard.signin")}
          </Link>
        </div>
      )}

      {(state === "ready" || (demo && state !== "down")) && (
        <>
          {firmName ? <h2>{firmName}</h2> : null}
          <div className="tp-actions">
            <StatusPill label={demo ? t(locale, "preview.only") : t(locale, "health.backendUp")} />
            {!demo && me ? <StatusPill label={`${me.email} · ${me.memberships[0]?.role ?? "member"}`} /> : null}
          </div>

          <div className="tp-stats">
            {stats.map((s) => (
              <StatCard key={s.label} label={s.label} value={s.value} hint={"hint" in s ? s.hint : undefined} />
            ))}
          </div>

          <h2>{t(locale, "dashboard.clientsOverview")}</h2>
          {shownClients.length === 0 ? (
            <EmptyState title={t(locale, "dashboard.clients")} hint={t(locale, "dashboard.noClients")} />
          ) : (
            <div className="tp-table-wrap">
              <table className="tp-table">
                <thead>
                  <tr>
                    <th>{t(locale, "clients.name")}</th>
                    <th>{t(locale, "clients.sector")}</th>
                    <th>{t(locale, "dashboard.activeReviews")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shownClients.map((c) => (
                    <tr key={c.id}>
                      <td>{c.name}</td>
                      <td>{c.detail}</td>
                      <td className="tp-num">{c.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="tp-actions">
            <Link href="/clients" className="tp-primary">
              {t(locale, "dashboard.viewAllClients")}
            </Link>
            <Link href="/reviews/new" className="tp-primary">
              {t(locale, "dashboard.newReview")}
            </Link>
            {!demo ? (
              <Button type="button" onClick={signOut}>
                {t(locale, "dashboard.signout")}
              </Button>
            ) : null}
          </div>

          <h2>{t(locale, "dashboard.reviewsTitle")}</h2>
          {demo ? (
            <div className="tp-table-wrap">
              <table className="tp-table">
                <thead>
                  <tr>
                    <th>{t(locale, "clients.name")}</th>
                    <th>{t(locale, "review.periodStart")} – {t(locale, "review.periodEnd")}</th>
                    <th>{t(locale, "clients.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {DEMO_REVIEWS.map((r) => (
                    <tr key={r.id}>
                      <td>{locale === "ar" ? r.clientNameAr : r.clientName}</td>
                      <td className="tp-num">{r.period}</td>
                      <td>
                        <StatusPill label={locale === "ar" ? r.typeAr : r.type} />{" "}
                        {t(locale, `review.status.${r.status}`)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <PreviewOnly locale={locale} />
          )}
        </>
      )}
    </main>
  );
}


