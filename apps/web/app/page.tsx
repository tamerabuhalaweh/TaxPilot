"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { DemoBanner } from "../components/Preview";
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
  listEngagements,
  logout,
  type ClientPayload,
  type EngagementPayload,
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
  const [engagements, setEngagements] = useState<EngagementPayload[]>([]);

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
        const [clientList, engagementList] = await Promise.all([
          listClients(),
          listEngagements().catch(() => [] as EngagementPayload[])
        ]);
        setClients(clientList);
        setEngagements(engagementList);
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
  const activeMembership =
    me?.memberships.find((membership) => membership.tenant_id === me.active_tenant_id) ?? me?.memberships[0];
  const firmName = demo
    ? locale === "ar"
      ? DEMO_FIRM.nameAr
      : DEMO_FIRM.name
    : (activeMembership?.tenant_name ?? undefined);
  const activeReviews = demo ? DEMO_REVIEWS.filter((r) => r.status === "in_progress").length : 0;
  const doneReviews = demo ? DEMO_REVIEWS.filter((r) => r.status === "approved").length : 0;
  const openReviews = engagements.filter((e) => e.status === "DRAFT" || e.status === "ACTIVE").length;
  const closedReviews = engagements.filter((e) => e.status === "CLOSED").length;
  const activeClients = clients.filter((c) => c.status === "active").length;
  const stats = demo
    ? [
        { label: t(locale, "dashboard.activeReviews"), value: String(activeReviews) },
        { label: t(locale, "dashboard.awaitingAction"), value: "1" },
        { label: t(locale, "dashboard.highPriority"), value: "0" },
        { label: t(locale, "dashboard.recentlyCompleted"), value: String(doneReviews) }
      ]
    : [
        { label: t(locale, "dashboard.clients"), value: String(activeClients) },
        { label: t(locale, "dashboard.totalReviews"), value: String(engagements.length) },
        { label: t(locale, "dashboard.openReviews"), value: String(openReviews) },
        { label: t(locale, "dashboard.completedReviews"), value: String(closedReviews) }
      ];
  interface ClientRow {
    id: string;
    name: string;
    detail: string;
    count: string;
  }
  const openByClient = new Map<string, number>();
  for (const engagement of engagements) {
    if (engagement.status !== "DRAFT" && engagement.status !== "ACTIVE") continue;
    openByClient.set(engagement.client_id, (openByClient.get(engagement.client_id) ?? 0) + 1);
  }
  const shownClients: ClientRow[] = demo
    ? DEMO_CLIENTS.filter((c) => c.status === "active").map((c) => ({
        id: c.id,
        name: locale === "ar" ? c.nameAr : c.name,
        detail: locale === "ar" ? c.sectorAr : c.sector,
        count: String(c.activeReviews)
      }))
    : clients
        .filter((c) => c.status === "active")
        .map((c) => ({
          id: c.id,
          name: c.name,
          detail: c.sector ?? "—",
          count: String(openByClient.get(c.id) ?? 0)
        }));
  const clientNames = new Map(clients.map((client) => [client.id, client.name]));
  const recentReviews = [...engagements]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5);

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
              <StatCard key={s.label} label={s.label} value={s.value} />
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
                      <td>
                        <Link href={`/clients/${c.id}`}>{c.name}</Link>
                      </td>
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
          ) : recentReviews.length === 0 ? (
            <EmptyState title={t(locale, "dashboard.reviewsTitle")} hint={t(locale, "dashboard.noReviews")} />
          ) : (
            <>
              <p className="tp-muted">{t(locale, "dashboard.recentHint")}</p>
              <div className="tp-table-wrap">
                <table className="tp-table">
                  <thead>
                    <tr>
                      <th>{t(locale, "clients.name")}</th>
                      <th>{t(locale, "reviews.period")}</th>
                      <th>{t(locale, "clients.status")}</th>
                      <th aria-label="actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {recentReviews.map((review) => (
                      <tr key={review.id}>
                        <td>
                          <Link href={`/clients/${review.client_id}`}>
                            {clientNames.get(review.client_id) ?? "—"}
                          </Link>
                        </td>
                        <td className="tp-num" dir="ltr">
                          {review.period_start} – {review.period_end}
                        </td>
                        <td>
                          <StatusPill label={t(locale, `review.status.${review.status.toLowerCase()}`)} />
                        </td>
                        <td>
                          <Link href={`/reviews/${review.id}`}>{t(locale, "clients.open")}</Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}


