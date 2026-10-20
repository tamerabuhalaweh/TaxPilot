"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "../../components/Alert";
import { DemoBanner } from "../../components/Preview";
import { EmptyState } from "../../components/EmptyState";
import { useLocale } from "../../components/LocaleProvider";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import {
  ApiRequestError,
  listClients,
  listEngagements,
  type ClientPayload,
  type EngagementPayload
} from "../../lib/api";
import { DEMO_REVIEWS } from "../../lib/demo-data";
import { t } from "../../lib/i18n";
import { isDemoMode } from "../../lib/preview";

interface ReviewRow {
  engagement: EngagementPayload;
  clientName: string;
}

type LoadState = "loading" | "ready" | "denied" | "error";

function statusLabel(locale: "en" | "ar", status: string): string {
  return t(locale, `review.status.${status.toLowerCase()}`);
}

function typeLabel(locale: "en" | "ar", reviewType: string): string {
  return reviewType === "JOFO" ? t(locale, "review.typeJofotara") : t(locale, "review.typeSalesGl");
}

/** Reviews index: connected workspaces list real engagements; demo builds keep
 * their explicitly synthetic illustration. Every row opens the workspace. */
export default function ReviewsPage() {
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<LoadState>("loading");
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const demo = isDemoMode();

  useEffect(() => {
    if (demo) {
      setState("ready");
      return;
    }
    const ctrl = new AbortController();
    (async () => {
      try {
        const [engagements, clients] = await Promise.all([
          listEngagements(),
          listClients("all").catch(() => [] as ClientPayload[])
        ]);
        const names = new Map(clients.map((client) => [client.id, client.name]));
        setRows(
          engagements.map((engagement) => ({
            engagement,
            clientName: names.get(engagement.client_id) ?? "—"
          }))
        );
        setState("ready");
      } catch (err) {
        setState(err instanceof ApiRequestError && (err.status === 401 || err.status === 403) ? "denied" : "error");
      }
    })();
    return () => ctrl.abort();
  }, [demo]);

  const newReview = (
    <Link href="/reviews/new" className="tp-primary">
      {t(locale, "dashboard.newReview")}
    </Link>
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
      <h1>{t(locale, "nav.reviews")}</h1>
      <p className="tp-muted">{t(locale, "reviews.subtitle")}</p>
      <div className="tp-actions">{newReview}</div>

      {state === "loading" ? <p className="tp-muted">{t(locale, "review.loading")}</p> : null}
      {state === "error" ? <Alert message={t(locale, "reviews.loadError")} /> : null}
      {state === "denied" ? (
        <div className="tp-actions">
          <EmptyState title={t(locale, "dashboard.signinRequired")} hint={t(locale, "dashboard.signinRequiredHint")} />
          <Link href="/login" className="tp-primary">
            {t(locale, "dashboard.signin")}
          </Link>
        </div>
      ) : null}

      {state === "ready" && demo ? (
        <div className="tp-table-wrap">
          <table className="tp-table">
            <thead>
              <tr>
                <th>{t(locale, "clients.name")}</th>
                <th>{t(locale, "reviews.period")}</th>
                <th>{t(locale, "reviews.type")}</th>
                <th>{t(locale, "clients.status")}</th>
              </tr>
            </thead>
            <tbody>
              {DEMO_REVIEWS.map((review) => (
                <tr key={review.id}>
                  <td>{locale === "ar" ? review.clientNameAr : review.clientName}</td>
                  <td className="tp-num">{review.period}</td>
                  <td>{locale === "ar" ? review.typeAr : review.type}</td>
                  <td>{t(locale, `review.status.${review.status}`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {state === "ready" && demo ? (
        <p className="tp-muted">{t(locale, "reviews.demoNote")}</p>
      ) : null}

      {state === "ready" && !demo && rows.length === 0 ? (
        <EmptyState title={t(locale, "reviews.emptyTitle")} hint={t(locale, "reviews.emptyHint")} />
      ) : null}

      {state === "ready" && !demo && rows.length > 0 ? (
        <div className="tp-table-wrap">
          <table className="tp-table">
            <thead>
              <tr>
                <th>{t(locale, "clients.name")}</th>
                <th>{t(locale, "reviews.period")}</th>
                <th>{t(locale, "reviews.type")}</th>
                <th>{t(locale, "clients.status")}</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ engagement, clientName }) => (
                <tr key={engagement.id}>
                  <td>
                    <Link href={`/clients/${engagement.client_id}`}>{clientName}</Link>
                  </td>
                  <td className="tp-num" dir="ltr">
                    {engagement.period_start} – {engagement.period_end}
                  </td>
                  <td>{typeLabel(locale, engagement.review_type)}</td>
                  <td>{statusLabel(locale, engagement.status)}</td>
                  <td>
                    <Link href={`/reviews/${engagement.id}`}>{t(locale, "clients.open")}</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  );
}
