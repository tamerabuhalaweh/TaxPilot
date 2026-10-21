"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../../components/Preview";
import { Alert } from "../../../components/Alert";
import { useLocale } from "../../../components/LocaleProvider";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import { Tabs } from "../../../components/Tabs";
import { EmptyState } from "../../../components/EmptyState";
import {
  ApiRequestError,
  getClient,
  listEngagements,
  type ClientPayload,
  type EngagementPayload
} from "../../../lib/api";
import { DEMO_CLIENTS, DEMO_REVIEWS } from "../../../lib/demo-data";
import { t } from "../../../lib/i18n";
import { isDemoMode } from "../../../lib/preview";

interface ReviewRow {
  id: string;
  period: string;
  type: string;
  status: string;
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

function toRow(locale: "en" | "ar", engagement: EngagementPayload): ReviewRow {
  return {
    id: engagement.id,
    period: `${engagement.period_start} – ${engagement.period_end}`,
    type: typeLabel(locale, engagement.review_type),
    status: statusLabel(locale, engagement.status),
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

  const reviewsTab = (
    <div>
      <h2>{t(locale, "client.reviewsTitle")}</h2>
      <p className="tp-muted">{t(locale, "client.reviewsHint")}</p>
      {rows.length === 0 ? (
        <EmptyState title={t(locale, "client.reviewsTitle")} hint={t(locale, "client.noReviews")} />
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
                  <td>{row.status}</td>
                  {row.openable ? (
                    <td>
                      <Link href={`/reviews/${row.id}`}>{t(locale, "clients.open")}</Link>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="tp-actions">
        <Link href={`/reviews/new?client=${encodeURIComponent(id)}`} className="tp-primary">
          {t(locale, "dashboard.newReview")}
        </Link>
      </div>
    </div>
  );

  const profileTab = (
    <div className="tp-card">
      <dl className="tp-kv">
        <div>
          <dt>{t(locale, "clients.name")}</dt>
          <dd>{client?.name}</dd>
        </div>
        <div>
          <dt>{t(locale, "clients.status")}</dt>
          <dd>{client?.status === "active" ? t(locale, "clients.active") : t(locale, "clients.archived")}</dd>
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
      <p>
        <Link href="/clients">← {t(locale, "client.back")}</Link>
      </p>
      {state.kind === "not-found" ? (
        <EmptyState title={t(locale, "client.notFound")} hint={t(locale, "clients.noResults")} />
      ) : state.kind === "denied" ? (
        <div className="tp-actions">
          <EmptyState title={t(locale, "dashboard.signinRequired")} hint={t(locale, "dashboard.signinRequiredHint")} />
          <Link href="/login" className="tp-primary">
            {t(locale, "dashboard.signin")}
          </Link>
        </div>
      ) : state.kind === "unreachable" ? (
        <div className="tp-actions">
          <Alert message={t(locale, "client.loadError")} />
        </div>
      ) : state.kind === "ready" ? (
        <>
          <h1>{client?.name}</h1>
          <p className="tp-muted">
            {t(locale, "clients.sector")}: {client?.sector ?? "—"} · {t(locale, "clients.status")}:{" "}
            {client?.status === "active" ? t(locale, "clients.active") : t(locale, "clients.archived")}
          </p>
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
                  <div className="tp-card">
                    <h2>{t(locale, "client.documents")}</h2>
                    <p className="tp-muted">{t(locale, "client.documentsHint")}</p>
                  </div>
                )
              },
              {
                id: "findings",
                label: t(locale, "client.findings"),
                content: demo ? (
                  <PreviewOnly locale={locale} />
                ) : (
                  <div className="tp-card">
                    <h2>{t(locale, "client.findings")}</h2>
                    <p className="tp-muted">{t(locale, "client.findingsHint")}</p>
                  </div>
                )
              },
              {
                id: "reports",
                label: t(locale, "client.reports"),
                content: demo ? (
                  <PreviewOnly locale={locale} />
                ) : (
                  <div className="tp-card">
                    <h2>{t(locale, "client.reports")}</h2>
                    <p className="tp-muted">{t(locale, "client.reportsHint")}</p>
                  </div>
                )
              }
            ]}
          />
        </>
      ) : null}
    </main>
  );
}
