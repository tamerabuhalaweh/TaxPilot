"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { DemoBanner } from "../../components/Preview";
import { useLocale } from "../../components/LocaleProvider";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { StatusPill } from "../../components/StatusPill";
import {
  ApiRequestError,
  createClient,
  fetchMe,
  listClients,
  type ClientPayload
} from "../../lib/api";
import { DEMO_CLIENTS, type DemoClient } from "../../lib/demo-data";
import { initials } from "../../lib/format";
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
      setRows(DEMO_CLIENTS.filter((c) => filter === "all" || c.status === filter).map(toRow));
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

  const visible = rows.filter((r) => r.name.toLowerCase().includes(query.trim().toLowerCase()));

  async function addClient(ev: React.FormEvent): Promise<void> {
    ev.preventDefault();
    if (demo) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createClient(name.trim());
      setFilter("active");
      setRows((prev) => [...prev.filter((r) => r.id !== created.id), toRow(created)]);
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
      <PageHeader
        title={t(locale, "clients.title")}
        description={t(locale, "clients.subtitle")}
        actions={
          !demo && !denied ? (
            <a href="#add-client" className="tp-primary">
              <Icon name="plus" size={16} />
              {t(locale, "dashboard.addClient")}
            </a>
          ) : null
        }
      />

      {denied && !demo ? (
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
      ) : (
        <>
          {error ? <Alert message={error} /> : null}

          <section className="tp-panel">
            <div className="tp-toolbar">
              <div className="tp-toolbar-search tp-field">
                <label htmlFor="client-search">{t(locale, "clients.search")}</label>
                <div className="tp-input-icon">
                  <Icon name="search" size={16} />
                  <input
                    id="client-search"
                    type="search"
                    value={query}
                    placeholder={t(locale, "clients.search")}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
              </div>
              <div className="tp-segmented" role="group" aria-label={t(locale, "clients.status")}>
                {(
                  [
                    { value: "active", label: t(locale, "clients.filterActive") },
                    { value: "archived", label: t(locale, "clients.filterArchived") },
                    { value: "all", label: t(locale, "clients.filterAll") }
                  ] as const
                ).map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    variant={filter === option.value ? "primary" : "ghost"}
                    disabled={filter === option.value}
                    onClick={() => setFilter(option.value)}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </div>

            {visible.length === 0 ? (
              <EmptyState
                title={t(locale, "clients.title")}
                hint={t(locale, "clients.noResults")}
                icon="clients"
              />
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
                        <td>
                          <div className="tp-person">
                            <span className="tp-avatar" aria-hidden="true">
                              {initials(r.name)}
                            </span>
                            <div className="tp-person-copy">
                              <Link href={`/clients/${r.id}`} className="tp-person-name">
                                {r.name}
                              </Link>
                              <span className="tp-person-meta">{r.sector}</span>
                            </div>
                          </div>
                        </td>
                        <td>{r.sector}</td>
                        <td className="tp-num">{r.meta}</td>
                        <td>
                          <StatusPill
                            label={r.status === "active" ? t(locale, "clients.active") : t(locale, "clients.archived")}
                            tone={r.status === "active" ? "success" : "neutral"}
                          />
                        </td>
                        <td>
                          <Link href={`/clients/${r.id}`} className="tp-row-link">
                            {t(locale, "clients.open")}
                            <Icon name="arrow" size={14} />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {!demo ? (
            <section className="tp-panel tp-form-panel" id="add-client">
              <div className="tp-panel-head">
                <div>
                  <h2>{t(locale, "clients.newClientPanel")}</h2>
                  <p className="tp-muted">{t(locale, "clients.panelHint")}</p>
                </div>
              </div>
              <form onSubmit={addClient} className="tp-inline-form">
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
                <Button type="submit" disabled={busy || name.trim() === ""}>
                  <Icon name="plus" size={16} />
                  {t(locale, "dashboard.addClient")}
                </Button>
              </form>
            </section>
          ) : null}
        </>
      )}
    </main>
  );
}
