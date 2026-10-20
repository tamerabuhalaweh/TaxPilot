"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "../../components/Alert";
import { DemoBanner, PreviewOnly } from "../../components/Preview";
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
import { t } from "../../lib/i18n";
import { isDemoMode } from "../../lib/preview";

type LoadState = "loading" | "ready" | "denied" | "error";

/** Reports index: exports live inside a review (bound to that run), so this
 * page routes reviewers to the exact workspace instead of faking a file list. */
export default function ReportsPage() {
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<LoadState>("loading");
  const [rows, setRows] = useState<{ engagement: EngagementPayload; clientName: string }[]>([]);
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
      <h1>{t(locale, "nav.reports")}</h1>
      <p className="tp-muted">{t(locale, "reports.subtitle")}</p>

      {state === "loading" ? <p className="tp-muted">{t(locale, "review.loading")}</p> : null}
      {state === "error" ? <Alert message={t(locale, "reports.loadError")} /> : null}
      {state === "denied" ? (
        <div className="tp-actions">
          <EmptyState title={t(locale, "dashboard.signinRequired")} hint={t(locale, "dashboard.signinRequiredHint")} />
          <Link href="/login" className="tp-primary">
            {t(locale, "dashboard.signin")}
          </Link>
        </div>
      ) : null}

      {state === "ready" && demo ? <PreviewOnly locale={locale} /> : null}

      {state === "ready" && !demo && rows.length === 0 ? (
        <EmptyState title={t(locale, "reports.emptyTitle")} hint={t(locale, "reports.emptyHint")} />
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
                  <td>
                    {engagement.review_type === "JOFO"
                      ? t(locale, "review.typeJofotara")
                      : t(locale, "review.typeSalesGl")}
                  </td>
                  <td>{t(locale, `review.status.${engagement.status.toLowerCase()}`)}</td>
                  <td>
                    <Link href={`/reviews/${engagement.id}`}>{t(locale, "reports.openReview")}</Link>
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
