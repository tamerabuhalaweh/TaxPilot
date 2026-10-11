"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { StatusPill } from "../components/StatusPill";
import { ApiRequestError, createClient, fetchHealth, fetchMe, listClients, logout, type ClientPayload, type MePayload } from "../lib/api";
import { dirOf, t, type Locale } from "../lib/i18n";

type LoadState = "checking" | "down" | "signed-out" | "ready";

/** Dashboard: backend status, session gate, clients slice. No mock data anywhere. */
export default function DashboardPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [state, setState] = useState<LoadState>("checking");
  const [me, setMe] = useState<MePayload | null>(null);
  const [clients, setClients] = useState<ClientPayload[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dirOf(locale);
  }, [locale]);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        await fetchHealth(ctrl.signal);
      } catch {
        setState("down");
        return;
      }
      try {
        const profile = await fetchMe(ctrl.signal);
        setMe(profile);
        setClients(await listClients());
        setState("ready");
      } catch (err) {
        setState(err instanceof ApiRequestError && err.status === 401 ? "signed-out" : "down");
      }
    })();
    return () => ctrl.abort();
  }, []);

  async function addClient(ev: React.FormEvent): Promise<void> {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await createClient(name.trim());
      setClients((prev) => [...prev, created]);
      setName("");
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not create client.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut(): Promise<void> {
    await logout();
    window.location.href = "/login";
  }

  return (
    <main>
      <p className="tp-muted">{t(locale, "app.tagline")}</p>
      <h1>{t(locale, "dashboard.title")}</h1>
      <div className="tp-actions" role="group" aria-label="locale">
        <Button onClick={() => setLocale("en")} disabled={locale === "en"}>
          English
        </Button>
        <Button onClick={() => setLocale("ar")} disabled={locale === "ar"}>
          العربية
        </Button>
      </div>

      {state === "checking" && (
        <div className="tp-actions">
          <StatusPill label={t(locale, "health.checking")} />
        </div>
      )}
      {state === "down" && (
        <div className="tp-actions">
          <Alert message={t(locale, "health.backendDown")} />
        </div>
      )}
      {state === "signed-out" && (
        <div className="tp-actions">
          <EmptyState title="Sign in required" hint="Sign in to see your workspace and clients." />
          <Link href="/login" className="tp-primary">
            Sign in
          </Link>
        </div>
      )}
      {state === "ready" && me ? (
        <>
          <div className="tp-actions">
            <StatusPill label={t(locale, "health.backendUp")} />
            <StatusPill label={`${me.email} · ${me.memberships[0]?.role ?? "member"}`} />
          </div>
          <h2>Clients</h2>
          {error ? <Alert message={error} /> : null}
          {clients.length === 0 ? (
            <EmptyState title={t(locale, "dashboard.newReview")} hint={t(locale, "dashboard.empty")} />
          ) : (
            <ul>
              {clients.map((c) => (
                <li key={c.id}>
                  {c.name} <span className="tp-muted">({c.status})</span>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={addClient}>
            <p>
              <label>
                New client name
                <br />
                <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
              </label>
            </p>
            <div className="tp-actions">
              <Button type="submit" disabled={busy || name.trim() === ""}>
                Add Client
              </Button>
            </div>
          </form>
          <div className="tp-actions">
            <Link href="/reviews/new" className="tp-primary">
              {t(locale, "dashboard.newReview")}
            </Link>
            <Button type="button" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </>
      ) : null}
    </main>
  );
}
