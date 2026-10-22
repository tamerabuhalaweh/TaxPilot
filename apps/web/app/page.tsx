"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Icon, type IconName } from "../components/Icon";
import { DemoBanner } from "../components/Preview";
import { PageHeader } from "../components/PageHeader";
import { useLocale } from "../components/LocaleProvider";
import { LocaleControls } from "../components/LocaleControls";
import { Nav } from "../components/Nav";
import { StatCard } from "../components/StatCard";
import { StatusPill } from "../components/StatusPill";
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
import { initials } from "../lib/format";
import { t, type Locale } from "../lib/i18n";
import { isDemoMode } from "../lib/preview";

type LoadState = "checking" | "down" | "signed-out" | "ready";
type Tone = "neutral" | "info" | "success" | "warning" | "danger";

interface DashboardStat {
  label: string;
  value: string;
  icon: IconName;
}

function statusTone(status: string): Tone {
  switch (status.toLowerCase()) {
    case "approved":
    case "closed":
      return "success";
    case "in_progress":
    case "active":
      return "info";
    case "ready_for_approval":
      return "warning";
    default:
      return "neutral";
  }
}

function statusLabel(locale: Locale, status: string): string {
  return t(locale, `review.status.${status.toLowerCase()}`);
}

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

  const stats: DashboardStat[] = demo
    ? [
        { label: t(locale, "dashboard.activeReviews"), value: String(activeReviews), icon: "reviews" },
        { label: t(locale, "dashboard.awaitingAction"), value: "1", icon: "clock" },
        { label: t(locale, "dashboard.highPriority"), value: "0", icon: "alert" },
        { label: t(locale, "dashboard.recentlyCompleted"), value: String(doneReviews), icon: "check" }
      ]
    : [
        { label: t(locale, "dashboard.clients"), value: String(activeClients), icon: "clients" },
        { label: t(locale, "dashboard.totalReviews"), value: String(engagements.length), icon: "reviews" },
        { label: t(locale, "dashboard.openReviews"), value: String(openReviews), icon: "clock" },
        { label: t(locale, "dashboard.completedReviews"), value: String(closedReviews), icon: "check" }
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
  const recentReviews = [...engagements].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 6);

  const demoReviewRows = DEMO_REVIEWS.map((review) => ({
    id: review.id,
    clientName: locale === "ar" ? review.clientNameAr : review.clientName,
    period: review.period,
    type: locale === "ar" ? review.typeAr : review.type,
    status: review.status,
    openable: false
  }));

  const reviewRows = demo
    ? demoReviewRows
    : recentReviews.map((review) => ({
        id: review.id,
        clientName: clientNames.get(review.client_id) ?? "—",
        period: `${review.period_start} — ${review.period_end}`,
        type:
          review.review_type === "JOFO"
            ? t(locale, "review.typeJofotara")
            : t(locale, "review.typeSalesGl"),
        status: review.status.toLowerCase(),
        openable: true
      }));

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
      <PageHeader
        title={t(locale, "dashboard.title")}
        description={t(locale, "app.tagline")}
        actions={
          <Link href="/reviews/new" className="tp-primary">
            <Icon name="plus" size={16} />
            {t(locale, "dashboard.newReview")}
          </Link>
        }
      />

      {state === "checking" && <StatusPill label={t(locale, "health.checking")} tone="neutral" />}
      {state === "down" && <Alert message={t(locale, "health.backendDown")} />}
      {state === "signed-out" && !demo && (
        <EmptyState
          title={t(locale, "dashboard.signinRequired")}
          hint={t(locale, "dashboard.signinRequiredHint")}
          icon="shield"
          action={
            <Link href="/login" className="tp-primary">
              {t(locale, "dashboard.signin")}
            </Link>
          }
        />
      )}

      {(state === "ready" || (demo && state !== "down")) && (
        <>
          <section className="tp-workspace-strip">
            <div>
              {firmName ? <h2>{firmName}</h2> : null}
              <p>{t(locale, "dashboard.workspace")}</p>
            </div>
            <div className="tp-actions">
              <Link href="/clients" className="tp-button tp-button-secondary">
                <Icon name="clients" size={16} />
                {t(locale, "dashboard.viewAllClients")}
              </Link>
              <Link href="/reviews/new" className="tp-button tp-button-primary">
                <Icon name="plus" size={16} />
                {t(locale, "dashboard.newReview")}
              </Link>
            </div>
          </section>

          <div className="tp-stats">
            {stats.map((stat) => (
              <StatCard key={stat.label} label={stat.label} value={stat.value} icon={stat.icon} />
            ))}
          </div>

          <div className="tp-dashboard-grid">
            <section className="tp-panel">
              <div className="tp-panel-head">
                <h2>{t(locale, "dashboard.clientsOverview")}</h2>
                <Link href="/clients">{t(locale, "common.viewAll")}</Link>
              </div>
              {shownClients.length === 0 ? (
                <EmptyState
                  title={t(locale, "dashboard.clients")}
                  hint={t(locale, "dashboard.noClients")}
                  icon="clients"
                />
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
                      {shownClients.map((client) => (
                        <tr key={client.id}>
                          <td>
                            <div className="tp-person">
                              <span className="tp-avatar" aria-hidden="true">
                                {initials(client.name)}
                              </span>
                              <div className="tp-person-copy">
                                <Link href={`/clients/${client.id}`} className="tp-person-name">
                                  {client.name}
                                </Link>
                                <span className="tp-person-meta">{client.detail}</span>
                              </div>
                            </div>
                          </td>
                          <td>{client.detail}</td>
                          <td className="tp-num">{client.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <aside className="tp-panel">
              <div className="tp-panel-head">
                <h2>{t(locale, "dashboard.workspaceStatus")}</h2>
                <StatusPill
                  label={demo ? t(locale, "preview.only") : t(locale, "health.backendUp")}
                  tone={demo ? "warning" : "success"}
                />
              </div>
              <div className="tp-status-list">
                <div className="tp-status-item">
                  <span className="tp-status-label">{t(locale, "dashboard.workspace")}</span>
                  <span className="tp-status-value">{firmName ?? "—"}</span>
                </div>
                <div className="tp-status-item">
                  <span className="tp-status-label">{t(locale, "auth.email")}</span>
                  <span className="tp-status-value">{demo ? t(locale, "preview.only") : (me?.email ?? "—")}</span>
                </div>
                <div className="tp-status-item">
                  <span className="tp-status-label">{t(locale, "dashboard.role")}</span>
                  <span className="tp-status-value">
                    {demo ? t(locale, "preview.only") : (activeMembership?.role ?? "—")}
                  </span>
                </div>
                <div className="tp-status-item">
                  <span className="tp-status-label">{t(locale, "dashboard.clients")}</span>
                  <span className="tp-status-value tp-num">{demo ? DEMO_CLIENTS.length : clients.length}</span>
                </div>
              </div>
              {!demo ? (
                <div className="tp-inline-actions">
                  <Button type="button" variant="secondary" onClick={signOut}>
                    <Icon name="logout" size={15} />
                    {t(locale, "dashboard.signout")}
                  </Button>
                </div>
              ) : null}
            </aside>
          </div>

          <section className="tp-panel">
            <div className="tp-panel-head">
              <div>
                <h2>{t(locale, "dashboard.reviewsTitle")}</h2>
                <p className="tp-muted">{t(locale, "dashboard.activityHint")}</p>
              </div>
              <Link href="/reviews">{t(locale, "common.viewAll")}</Link>
            </div>
            {reviewRows.length === 0 ? (
              <EmptyState
                title={t(locale, "dashboard.reviewsTitle")}
                hint={t(locale, "dashboard.noReviews")}
                icon="reviews"
              />
            ) : (
              <div className="tp-table-wrap">
                <table className="tp-table">
                  <thead>
                    <tr>
                      <th>{t(locale, "clients.name")}</th>
                      <th>{t(locale, "reviews.period")}</th>
                      <th>{t(locale, "reviews.type")}</th>
                      <th>{t(locale, "clients.status")}</th>
                      {reviewRows.some((row) => row.openable) ? <th aria-label="actions" /> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {reviewRows.map((review) => (
                      <tr key={review.id}>
                        <td>
                          <span className="tp-person-name">{review.clientName}</span>
                        </td>
                        <td className="tp-num" dir="ltr">
                          {review.period}
                        </td>
                        <td>{review.type}</td>
                        <td>
                          <StatusPill
                            label={statusLabel(locale, review.status)}
                            tone={statusTone(review.status)}
                          />
                        </td>
                        {review.openable ? (
                          <td>
                            <Link href={`/reviews/${review.id}`} className="tp-row-link">
                              {t(locale, "common.open")}
                              <Icon name="arrow" size={14} />
                            </Link>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
