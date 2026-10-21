"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "../../components/Alert";
import { DemoBanner, PreviewOnly } from "../../components/Preview";
import { EmptyState } from "../../components/EmptyState";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { useLocale } from "../../components/LocaleProvider";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { StatusPill } from "../../components/StatusPill";
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
type Tone = "neutral" | "info" | "success" | "warning";

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
      <PageHeader title={t(locale, "nav.reports")} description={t(locale, "reports.subtitle")} />

      {state === "loading" ? <p className="tp-muted">{t(locale, "review.loading")}</p> : null}
      {state === "error" ? <Alert message={t(locale, "reports.loadError")} /> : null}
      {state === "denied" ? (
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
      ) : null}

      {state === "ready" && demo ? (
        <section className="tp-panel">
          <div className="tp-panel-head">
            <h2>{t(locale, "reports.reviewList")}</h2>
          </div>
          <PreviewOnly locale={locale} />
        </section>
      ) : null}

      {state === "ready" && !demo && rows.length === 0 ? (
        <EmptyState
          title={t(locale, "reports.emptyTitle")}
          hint={t(locale, "reports.emptyHint")}
          icon="reports"
        />
      ) : null}

      {state === "ready" && !demo && rows.length > 0 ? (
        <section className="tp-panel">
          <div className="tp-panel-head">
            <h2>{t(locale, "reports.reviewList")}</h2>
          </div>
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
                      <Link href={`/clients/${engagement.client_id}`} className="tp-person-name">
                        {clientName}
                      </Link>
                    </td>
                    <td className="tp-num" dir="ltr">
                      {engagement.period_start} – {engagement.period_end}
                    </td>
                    <td>
                      {engagement.review_type === "JOFO"
                        ? t(locale, "review.typeJofotara")
                        : t(locale, "review.typeSalesGl")}
                    </td>
                    <td>
                      <StatusPill
                        label={t(locale, `review.status.${engagement.status.toLowerCase()}`)}
                        tone={statusTone(engagement.status)}
                      />
                    </td>
                    <td>
                      <Link href={`/reviews/${engagement.id}`} className="tp-row-link">
                        {t(locale, "reports.openReview")}
                        <Icon name="arrow" size={14} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </main>
  );
}
