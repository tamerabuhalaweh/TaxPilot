"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../../components/Preview";
import { Alert } from "../../../components/Alert";
import { EmptyState } from "../../../components/EmptyState";
import { Icon } from "../../../components/Icon";
import { PageHeader } from "../../../components/PageHeader";
import { useLocale } from "../../../components/LocaleProvider";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import { StatusPill } from "../../../components/StatusPill";
import { Tabs } from "../../../components/Tabs";
import {
  ApiRequestError,
  getClient,
  listEngagements,
  type ClientPayload,
  type EngagementPayload
} from "../../../lib/api";
import { DEMO_CLIENTS, DEMO_REVIEWS } from "../../../lib/demo-data";
import { initials } from "../../../lib/format";
import { t } from "../../../lib/i18n";
import { isDemoMode } from "../../../lib/preview";

interface ReviewRow {
  id: string;
  period: string;
  type: string;
  status: string;
  tone: "neutral" | "info" | "success" | "warning";
  openable: boolean;
}

type DetailState =
  | { kind: "loading" }
  | { kind: "ready"; client: ClientPayload }
  | { kind: "not-found" }
  | { kind: "denied" }
  | { kind: "unreachable" };

function typeLabel(locale: "en" | "ar", reviewType: string): string {
  return reviewType === "JOFO" ? t(locale, "review.typeJofotara") : t(locale, "review.typeSalesGl");
}

function statusLabel(locale: "en" | "ar", status: string): string {
  return t(locale, `review.status.${status.toLowerCase()}`);
}

function statusTone(status: string): "neutral" | "info" | "success" | "warning" {
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

function toRow(locale: "en" | "ar", engagement: EngagementPayload): ReviewRow {
  return {
    id: engagement.id,
    period: `${engagement.period_start} – ${engagement.period_end}`,
    type: typeLabel(locale, engagement.review_type),
    status: statusLabel(locale, engagement.status),
    tone: statusTone(engagement.status),
    openable: true
  };
}

/** Client detail: real profile and engagement list in connected builds; the
 * demo keeps its explicitly illustrative content. */
export default function ClientDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<DetailState>({ kind: "loading" });
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const demo = isDemoMode();

  useEffect(() => {
    if (demo) {
      const found = DEMO_CLIENTS.find((c) => c.id === id);
      if (!found) {
        setState({ kind: "not-found" });
        return;
      }
      setState({
        kind: "ready",
        client: {
          id: found.id,
          name: locale === "ar" ? found.nameAr : found.name,
          sector: locale === "ar" ? found.sectorAr : found.sector,
          status: found.status
        }
      });
      setRows(
        DEMO_REVIEWS.filter((review) => review.clientName === found.name).map((review) => ({
          id: review.id,
          period: review.period,
          type: locale === "ar" ? review.typeAr : review.type,
          status: t(locale, `review.status.${review.status}`),
          tone: statusTone(review.status),
          openable: false
        }))
      );
      return;
    }
    const ctrl = new AbortController();
    (async () => {
      try {
        const client = await getClient(id);
        const engagements = await listEngagements(id).catch(() => [] as EngagementPayload[]);
        setState({ kind: "ready", client });
        setRows(engagements.map((engagement) => toRow(locale, engagement)));
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof ApiRequestError && err.status === 404) setState({ kind: "not-found" });
        else if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
          setState({ kind: "denied" });
        } else setState({ kind: "unreachable" });
      }
    })();
    return () => ctrl.abort();
  }, [id, locale, demo]);

  const client = state.kind === "ready" ? state.client : null;
  const active = client?.status === "active";

  const reviewsTab = (
    <section className="tp-panel">
      <div className="tp-panel-head">
        <div>
          <h2>{t(locale, "client.reviewsTitle")}</h2>
          <p className="tp-muted">{t(locale, "client.reviewsHint")}</p>
        </div>
        <Link href={`/reviews/new?client=${encodeURIComponent(id)}`} className="tp-button tp-button-primary">
          <Icon name="plus" size={16} />
          {t(locale, "dashboard.newReview")}
        </Link>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          title={t(locale, "client.reviewsTitle")}
          hint={t(locale, "client.noReviews")}
          icon="reviews"
        />
      ) : (
        <div className="tp-table-wrap">
          <table className="tp-table">
            <thead>
              <tr>
                <th>{t(locale, "reviews.period")}</th>
                <th>{t(locale, "reviews.type")}</th>
                <th>{t(locale, "clients.status")}</th>
                {rows.some((row) => row.openable) ? <th aria-label="actions" /> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="tp-num" dir="ltr">
                    {row.period}
                  </td>
                  <td>{row.type}</td>
                  <td>
                    <StatusPill label={row.status} tone={row.tone} />
                  </td>
                  {row.openable ? (
                    <td>
                      <Link href={`/reviews/${row.id}`} className="tp-row-link">
                        {t(locale, "clients.open")}
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
  );

  const profileTab = (
    <div className="tp-detail-grid">
      <section className="tp-panel">
        <div className="tp-panel-head">
          <h2>{t(locale, "client.profile")}</h2>
          <StatusPill
            label={active ? t(locale, "clients.active") : t(locale, "clients.archived")}
            tone={active ? "success" : "neutral"}
          />
        </div>
        <dl className="tp-kv">
          <div>
            <dt>{t(locale, "clients.name")}</dt>
            <dd>{client?.name}</dd>
          </div>
          <div>
            <dt>{t(locale, "clients.status")}</dt>
            <dd>{active ? t(locale, "clients.active") : t(locale, "clients.archived")}</dd>
          </div>
          <div>
            <dt>{t(locale, "clients.sector")}</dt>
            <dd>{client?.sector ?? "—"}</dd>
          </div>
          <div>
            <dt>{t(locale, "client.reviewsCount")}</dt>
            <dd className="tp-num">{rows.length}</dd>
          </div>
        </dl>
        <p className="tp-muted">{t(locale, "client.profileHint")}</p>
      </section>
      <aside className="tp-panel">
        <div className="tp-panel-head">
          <h2>{t(locale, "client.engagements")}</h2>
        </div>
        <div className="tp-status-list">
          <div className="tp-status-item">
            <span className="tp-status-label">{t(locale, "client.reviewsCount")}</span>
            <span className="tp-status-value tp-num">{rows.length}</span>
          </div>
          <div className="tp-status-item">
            <span className="tp-status-label">{t(locale, "clients.status")}</span>
            <span className="tp-status-value">
              {active ? t(locale, "clients.active") : t(locale, "clients.archived")}
            </span>
          </div>
        </div>
        <div className="tp-inline-actions">
          <Link href={`/reviews/new?client=${encodeURIComponent(id)}`} className="tp-button tp-button-primary">
            <Icon name="plus" size={16} />
            {t(locale, "dashboard.newReview")}
          </Link>
        </div>
      </aside>
    </div>
  );

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
      {state.kind === "not-found" ? (
        <>
          <PageHeader title={t(locale, "client.notFound")} back={{ href: "/clients", label: t(locale, "client.back") }} />
          <EmptyState title={t(locale, "client.notFound")} hint={t(locale, "clients.noResults")} icon="clients" />
        </>
      ) : state.kind === "denied" ? (
        <>
          <PageHeader title={t(locale, "clients.title")} back={{ href: "/clients", label: t(locale, "client.back") }} />
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
        </>
      ) : state.kind === "unreachable" ? (
        <>
          <PageHeader title={t(locale, "clients.title")} back={{ href: "/clients", label: t(locale, "client.back") }} />
          <Alert message={t(locale, "client.loadError")} />
        </>
      ) : state.kind === "ready" ? (
        <>
          <PageHeader
            back={{ href: "/clients", label: t(locale, "client.back") }}
            title={client?.name ?? t(locale, "clients.title")}
            description={`${t(locale, "clients.sector")}: ${client?.sector ?? "—"} · ${
              active ? t(locale, "clients.active") : t(locale, "clients.archived")
            }`}
            actions={
              <Link href={`/reviews/new?client=${encodeURIComponent(id)}`} className="tp-primary">
                <Icon name="plus" size={16} />
                {t(locale, "dashboard.newReview")}
              </Link>
            }
          />
          <section className="tp-client-hero">
            <span className="tp-avatar tp-avatar-lg" aria-hidden="true">
              {initials(client?.name ?? "")}
            </span>
            <div>
              <p className="tp-client-name">{client?.name}</p>
              <p className="tp-muted">
                {client?.sector ?? "—"} · {rows.length} {t(locale, "client.engagements")}
              </p>
            </div>
            <StatusPill
              label={active ? t(locale, "clients.active") : t(locale, "clients.archived")}
              tone={active ? "success" : "neutral"}
            />
          </section>
          <Tabs
            tabs={[
              { id: "profile", label: t(locale, "client.profile"), content: profileTab },
              { id: "reviews", label: t(locale, "client.engagements"), content: reviewsTab },
              {
                id: "documents",
                label: t(locale, "client.documents"),
                content: demo ? (
                  <PreviewOnly locale={locale} />
                ) : (
                  <section className="tp-panel">
                    <h2>{t(locale, "client.documents")}</h2>
                    <p className="tp-muted">{t(locale, "client.documentsHint")}</p>
                  </section>
                )
              },
              {
                id: "findings",
                label: t(locale, "client.findings"),
                content: demo ? (
                  <PreviewOnly locale={locale} />
                ) : (
                  <section className="tp-panel">
                    <h2>{t(locale, "client.findings")}</h2>
                    <p className="tp-muted">{t(locale, "client.findingsHint")}</p>
                  </section>
                )
              },
              {
                id: "reports",
                label: t(locale, "client.reports"),
                content: demo ? (
                  <PreviewOnly locale={locale} />
                ) : (
                  <section className="tp-panel">
                    <h2>{t(locale, "client.reports")}</h2>
                    <p className="tp-muted">{t(locale, "client.reportsHint")}</p>
                  </section>
                )
              }
            ]}
          />
        </>
      ) : (
        <PageHeader title={t(locale, "clients.title")} back={{ href: "/clients", label: t(locale, "client.back") }} />
      )}
    </main>
  );
}
