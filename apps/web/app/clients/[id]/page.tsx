"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../../components/Preview";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import { Tabs } from "../../../components/Tabs";
import { EmptyState } from "../../../components/EmptyState";
import { ApiRequestError, type ClientPayload } from "../../../lib/api";
import { DEMO_CLIENTS } from "../../../lib/demo-data";
import { dirOf, t, type Locale } from "../../../lib/i18n";
import { isDemoMode } from "../../../lib/preview";

async function fetchClient(id: string): Promise<ClientPayload> {
  const res = await fetch(`/api/v1/clients/${encodeURIComponent(id)}`);
  if (!res.ok) throw new ApiRequestError(`HTTP_${res.status}`, "Client not found.", res.status);
  return (await res.json()) as ClientPayload;
}

/** Client detail workspace: profile summary plus review/document/finding/report areas. */
export default function ClientDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [locale, setLocale] = useState<Locale>("en");
  const [client, setClient] = useState<{ name: string; sector: string; status: string } | null>(null);
  const [missing, setMissing] = useState(false);
  const demo = isDemoMode();

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dirOf(locale);
  }, [locale]);

  useEffect(() => {
    if (demo) {
      const found = DEMO_CLIENTS.find((c) => c.id === id);
      if (!found) {
        setMissing(true);
        return;
      }
      setClient({
        name: locale === "ar" ? found.nameAr : found.name,
        sector: locale === "ar" ? found.sectorAr : found.sector,
        status: found.status
      });
      return;
    }
    const ctrl = new AbortController();
    fetchClient(id)
      .then((c) => setClient({ name: c.name, sector: c.sector ?? "—", status: c.status }))
      .catch(() => setMissing(true));
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, locale]);

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
      {missing ? (
        <EmptyState title={t(locale, "clients.title")} hint={t(locale, "clients.noResults")} />
      ) : client ? (
        <>
          <h1>{client.name}</h1>
          <p className="tp-muted">
            {t(locale, "clients.sector")}: {client.sector} · {t(locale, "clients.status")}:{" "}
            {client.status === "active" ? t(locale, "clients.active") : t(locale, "clients.archived")}
          </p>
          <Tabs
            tabs={[
              { id: "profile", label: t(locale, "client.profile"), content: <PreviewOnly locale={locale} /> },
              { id: "reviews", label: t(locale, "client.engagements"), content: <PreviewOnly locale={locale} /> },
              { id: "documents", label: t(locale, "client.documents"), content: <PreviewOnly locale={locale} /> },
              { id: "findings", label: t(locale, "client.findings"), content: <PreviewOnly locale={locale} /> },
              { id: "reports", label: t(locale, "client.reports"), content: <PreviewOnly locale={locale} /> }
            ]}
          />
        </>
      ) : null}
    </main>
  );
}
