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
import { ApiRequestError, type ClientPayload } from "../../../lib/api";
import { DEMO_CLIENTS } from "../../../lib/demo-data";
import { t } from "../../../lib/i18n";
import { isDemoMode } from "../../../lib/preview";

async function fetchClient(id: string, signal?: AbortSignal): Promise<ClientPayload> {
  const res = await fetch(`/api/v1/clients/${encodeURIComponent(id)}`, { signal });
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    try {
      code = ((await res.json()) as { error: { code: string } }).error.code;
    } catch {
      /* keep generic */
    }
    throw new ApiRequestError(code, "Client load failed.", res.status);
  }
  return (await res.json()) as ClientPayload;
}

type DetailState =
  | { kind: "loading" }
  | { kind: "ready"; client: { name: string; sector: string; status: string } }
  | { kind: "not-found" }
  | { kind: "denied" }
  | { kind: "unreachable" };

/** Client detail workspace: profile summary plus review/document/finding/report areas. */
export default function ClientDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<DetailState>({ kind: "loading" });
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
          name: locale === "ar" ? found.nameAr : found.name,
          sector: locale === "ar" ? found.sectorAr : found.sector,
          status: found.status
        }
      });
      return;
    }
    const ctrl = new AbortController();
    fetchClient(id, ctrl.signal)
      .then((c) =>
        setState({ kind: "ready", client: { name: c.name, sector: c.sector ?? "—", status: c.status } })
      )
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof ApiRequestError && err.status === 404) setState({ kind: "not-found" });
        else if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
          setState({ kind: "denied" });
        } else setState({ kind: "unreachable" });
      });
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
          <h1>{state.client.name}</h1>
          <p className="tp-muted">
            {t(locale, "clients.sector")}: {state.client.sector} · {t(locale, "clients.status")}:{" "}
            {state.client.status === "active" ? t(locale, "clients.active") : t(locale, "clients.archived")}
          </p>
          <Tabs
            tabs={[
              { id: "profile", label: t(locale, "client.profile"), content: <PreviewOnly locale={locale} /> },
              {
                id: "reviews",
                label: t(locale, "client.engagements"),
                content: (
                  <PreviewOnly locale={locale}>
                    <p>
                      <Link href={`/reviews/new?client=${encodeURIComponent(id)}`} className="tp-primary">
                        {t(locale, "dashboard.newReview")}
                      </Link>
                    </p>
                  </PreviewOnly>
                )
              },
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



