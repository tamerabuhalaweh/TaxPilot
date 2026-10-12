"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
import { DemoBanner } from "../../../components/Preview";
import { useLocale } from "../../../components/LocaleProvider";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import { StatusPill } from "../../../components/StatusPill";
import { listClients, type ClientPayload } from "../../../lib/api";
import { DEMO_CLIENTS } from "../../../lib/demo-data";
import { t } from "../../../lib/i18n";
import { isDemoMode } from "../../../lib/preview";

/** New Review: client, period, type, and the three source types. The
 * reconciliation run itself is honestly marked as coming soon. */
export default function NewReviewPage() {
  const { locale, setLocale } = useLocale();
  const [clients, setClients] = useState<{ id: string; name: string }[]>([]);
  const [clientId, setClientId] = useState("");
  const [start, setStart] = useState("2026-01-01");
  const [end, setEnd] = useState("2026-09-30");
  const demo = isDemoMode();

  useEffect(() => {
    if (demo) {
      const list = DEMO_CLIENTS.filter((c) => c.status === "active").map((c) => ({
        id: c.id,
        name: locale === "ar" ? c.nameAr : c.name
      }));
      setClients(list);
      setClientId((prev) => prev || list[0]?.id || "");
      return;
    }
    listClients()
      .then((all: ClientPayload[]) =>
        setClients(all.filter((c) => c.status === "active").map((c) => ({ id: c.id, name: c.name })))
      )
      .catch(() => setClients([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

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
          <select id="nr-type">
            <option>{t(locale, "review.typeJofotara")}</option>
          </select>
        </div>
        <div className="tp-field">
          <label htmlFor="nr-start">{t(locale, "review.periodStart")}</label>
          <input id="nr-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div className="tp-field">
          <label htmlFor="nr-end">{t(locale, "review.periodEnd")}</label>
          <input id="nr-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
      </div>
      <h2>{t(locale, "workspace.documents")}</h2>
      {sources.map((s) => (
        <div key={s.title} className="tp-card tp-source-card">
          <h3>
            {s.title} <StatusPill label={t(locale, "preview.only")} />
          </h3>
          <p className="tp-muted">{s.hint}</p>
          <p className="tp-muted">{t(locale, "preview.comingSoon")}</p>
        </div>
      ))}
      <div className="tp-actions">
        <Button type="button" disabled title={t(locale, "review.notAvailable")}>
          {t(locale, "review.start")}
        </Button>
      </div>
      <p className="tp-muted">{t(locale, "review.notAvailable")}</p>
    </main>
  );
}




