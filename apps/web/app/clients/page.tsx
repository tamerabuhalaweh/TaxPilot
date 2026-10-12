"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { DemoBanner } from "../../components/Preview";
import { useLocale } from "../../components/LocaleProvider";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { EmptyState } from "../../components/EmptyState";
import {
  ApiRequestError,
  createClient,
  fetchMe,
  listClients,
  type ClientPayload
} from "../../lib/api";
import { DEMO_CLIENTS, type DemoClient } from "../../lib/demo-data";
import { t } from "../../lib/i18n";
import { isDemoMode } from "../../lib/preview";

interface Row {
  id: string;
  name: string;
  sector: string;
  status: string;
  meta: string;
}

/** Clients: searchable table with status filter, create flow, detail links. */
export default function ClientsPage() {
  const { locale, setLocale } = useLocale();
  const [rows, setRows] = useState<Row[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"active" | "archived" | "all">("active");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  const demo = isDemoMode();

  function toRow(c: ClientPayload | DemoClient): Row {
    if ("nameAr" in c) {
      return {
        id: c.id,
        name: locale === "ar" ? c.nameAr : c.name,
        sector: locale === "ar" ? c.sectorAr : c.sector,
        status: c.status,
        meta: String(c.activeReviews)
      };
    }
    return {
      id: c.id,
      name: c.name,
      sector: c.sector ?? "—",
      status: c.status,
      meta: "—"
    };
  }

  useEffect(() => {
    if (demo) {
      setRows(
        DEMO_CLIENTS.filter((c) => filter === "all" || c.status === filter).map(toRow)
      );
      return;
    }
    const ctrl = new AbortController();
    (async () => {
      try {
        const [profile, all] = await Promise.all([
          fetchMe(ctrl.signal),
          listClients(filter).catch((err: unknown) => {
            if (err instanceof ApiRequestError && err.status === 401) {
              setDenied(true);
              return [] as ClientPayload[];
            }
            throw err;
          })
        ]);
        void profile;
        setRows(all.map(toRow));
      } catch {
        setError(t(locale, "health.backendDown"));
      }
    })();
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, filter]);

  const visible = rows.filter((r) =>
    r.name.toLowerCase().includes(query.trim().toLowerCase())
  );

  async function addClient(ev: React.FormEvent): Promise<void> {
    ev.preventDefault();
    if (demo) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createClient(name.trim());
      setRows((prev) => [...prev, toRow(created)]);
      setName("");
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not create client.");
    } finally {
      setBusy(false);
    }
  }

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
      <h1>{t(locale, "clients.title")}</h1>
      {denied && !demo ? (
        <div className="tp-actions">
          <EmptyState title={t(locale, "dashboard.signinRequired")} hint={t(locale, "dashboard.signinRequiredHint")} />
          <Link href="/login" className="tp-primary">
            {t(locale, "dashboard.signin")}
          </Link>
        </div>
      ) : (
        <>
          {error ? <Alert message={error} /> : null}
          <div className="tp-actions" role="group" aria-label={t(locale, "clients.status")}>
            {(
              [
                { value: "active", label: t(locale, "clients.filterActive") },
                { value: "archived", label: t(locale, "clients.filterArchived") },
                { value: "all", label: t(locale, "clients.filterAll") }
              ] as const
            ).map((option) => (
              <Button key={option.value} type="button" disabled={filter === option.value} onClick={() => setFilter(option.value)}>
                {option.label}
              </Button>
            ))}
          </div>
          <div className="tp-field">
            <label htmlFor="client-search">{t(locale, "clients.search")}</label>
            <input
              id="client-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {visible.length === 0 ? (
            <EmptyState title={t(locale, "clients.title")} hint={t(locale, "clients.noResults")} />
          ) : (
            <div className="tp-table-wrap">
              <table className="tp-table">
                <thead>
                  <tr>
                    <th>{t(locale, "clients.name")}</th>
                    <th>{t(locale, "clients.sector")}</th>
                    <th>{t(locale, "clients.activeReviews")}</th>
                    <th>{t(locale, "clients.status")}</th>
                    <th aria-label="actions" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.id}>
                      <td>{r.name}</td>
                      <td>{r.sector}</td>
                      <td className="tp-num">{r.meta}</td>
                      <td>{r.status === "active" ? t(locale, "clients.active") : t(locale, "clients.archived")}</td>
                      <td>
                        <Link href={`/clients/${r.id}`}>{t(locale, "clients.open")}</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!demo ? (
            <form onSubmit={addClient}>
              <div className="tp-field">
                <label htmlFor="new-client">{t(locale, "dashboard.newClientName")}</label>
                <input
                  id="new-client"
                  required
                  maxLength={200}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="tp-actions">
                <Button type="submit" disabled={busy || name.trim() === ""}>
                  {t(locale, "dashboard.addClient")}
                </Button>
              </div>
            </form>
          ) : null}
        </>
      )}
    </main>
  );
}



