"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
import { Alert } from "../../../components/Alert";
import { DemoBanner } from "../../../components/Preview";
import { useLocale } from "../../../components/LocaleProvider";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import { StatusPill } from "../../../components/StatusPill";
import {
  ApiRequestError,
  createEngagement,
  listClients,
  type ClientPayload
} from "../../../lib/api";
import { DEMO_CLIENTS } from "../../../lib/demo-data";
import { t } from "../../../lib/i18n";
import { isDemoMode } from "../../../lib/preview";

/** New Review: create an engagement (review) for a client and period. Source
 * files stay honestly marked preview-only here; the synthetic walkthrough is
 * selected inside the review workspace. */
export default function NewReviewPage() {
  const { locale, setLocale } = useLocale();
  const router = useRouter();
  const [clients, setClients] = useState<{ id: string; name: string }[]>([]);
  const [clientId, setClientId] = useState("");
  const [reviewType, setReviewType] = useState("SALES_GL");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const demo = isDemoMode();
  // Demo keeps illustrative prefill; connected mode requires explicit user
  // input (SRS: future real context must never inherit synthetic dates).
  const [start, setStart] = useState(demo ? "2026-01-01" : "");
  const [end, setEnd] = useState(demo ? "2026-09-30" : "");
  const periodInvalid = !demo && start !== "" && end !== "" && start > end;

  useEffect(() => {
    const requested =
      typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("client");
    const pick = (list: { id: string }[]): string =>
      requested && list.some((c) => c.id === requested) ? requested : list[0]?.id || "";
    if (demo) {
      const list = DEMO_CLIENTS.filter((c) => c.status === "active").map((c) => ({
        id: c.id,
        name: locale === "ar" ? c.nameAr : c.name
      }));
      setClients(list);
      setClientId((prev) => prev || pick(list));
      return;
    }
    listClients()
      .then((all: ClientPayload[]) => {
        const list = all.filter((c) => c.status === "active").map((c) => ({ id: c.id, name: c.name }));
        setClients(list);
        setClientId((prev) => prev || pick(list));
      })
      .catch(() => setClients([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  async function startReview(): Promise<void> {
    setError(null);
    if (!clientId) {
      setError(t(locale, "review.clientRequired"));
      return;
    }
    if (!start || !end || periodInvalid) {
      setError(periodInvalid ? t(locale, "review.periodInvalid") : t(locale, "review.periodRequired"));
      return;
    }
    setSubmitting(true);
    try {
      const engagement = await createEngagement({
        client_id: clientId,
        review_type: reviewType,
        period_start: start,
        period_end: end
      });
      router.push(`/reviews/${engagement.id}`);
    } catch (err: unknown) {
      if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
        setError(t(locale, "dashboard.signinRequired"));
      } else {
        setError(t(locale, "review.createFailed"));
      }
      setSubmitting(false);
    }
  }

  const sources = [
    { title: t(locale, "review.sourceSales"), hint: t(locale, "review.sourceSalesHint") },
    { title: t(locale, "review.sourceJofotara"), hint: t(locale, "review.sourceJofotaraHint") },
    { title: t(locale, "review.sourceGL"), hint: t(locale, "review.sourceGLHint") }
  ];

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
      <h1>{t(locale, "review.newTitle")}</h1>
      <div className="tp-grid-2">
        <div className="tp-field">
          <label htmlFor="nr-client">{t(locale, "review.selectClient")}</label>
          <select id="nr-client" value={clientId} onChange={(e) => setClientId(e.target.value)}>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="tp-field">
          <label htmlFor="nr-type">{t(locale, "review.reviewType")}</label>
          <select id="nr-type" value={reviewType} onChange={(e) => setReviewType(e.target.value)}>
            <option value="SALES_GL">{t(locale, "review.typeSalesGl")}</option>
            <option value="JOFO">{t(locale, "review.typeJofotara")}</option>
          </select>
        </div>
        <div className="tp-field">
          <label htmlFor="nr-start">{t(locale, "review.periodStart")}</label>
          <input
            id="nr-start"
            type="date"
            required={!demo}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="tp-field">
          <label htmlFor="nr-end">{t(locale, "review.periodEnd")}</label>
          <input
            id="nr-end"
            type="date"
            required={!demo}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
      </div>
      {error ? <Alert message={error} /> : null}
      <h2>{t(locale, "workspace.documents")}</h2>
      <p className="tp-muted">{t(locale, "review.sourcesDisabled")}</p>
      {sources.map((s) => (
        <div key={s.title} className="tp-card tp-source-card">
          <h3>
            {s.title} <StatusPill label={t(locale, "preview.only")} />
          </h3>
          <p className="tp-muted">{s.hint}</p>
        </div>
      ))}
      <div className="tp-actions">
        <Button
          type="button"
          onClick={startReview}
          disabled={demo || submitting || !clientId || !start || !end || periodInvalid}
          title={demo ? t(locale, "review.notAvailable") : undefined}
        >
          {submitting ? t(locale, "review.starting") : t(locale, "review.start")}
        </Button>
      </div>
      <p className="tp-muted">{demo ? t(locale, "review.notAvailable") : t(locale, "review.startHint")}</p>
    </main>
  );
}
