"use client";

import { useEffect, useState } from "react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { StatusPill } from "../components/StatusPill";
import { fetchHealth } from "../lib/api";
import { dirOf, t, type Locale } from "../lib/i18n";

/** Dashboard stub: one primary action, backend connectivity, EN/AR + RTL. No mock reviews. */
export default function DashboardPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [backend, setBackend] = useState<"checking" | "up" | "down">("checking");

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dirOf(locale);
  }, [locale]);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchHealth(ctrl.signal)
      .then(() => setBackend("up"))
      .catch(() => setBackend("down"));
    return () => ctrl.abort();
  }, []);

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
      <div className="tp-actions">
        {backend === "checking" && <StatusPill label={t(locale, "health.checking")} />}
        {backend === "up" && <StatusPill label={t(locale, "health.backendUp")} />}
        {backend === "down" && <Alert message={t(locale, "health.backendDown")} />}
      </div>
      <div className="tp-actions">
        <EmptyState title={t(locale, "dashboard.newReview")} hint={t(locale, "dashboard.empty")} />
      </div>
      <div className="tp-actions">
        <Button>{t(locale, "dashboard.newReview")}</Button>
      </div>
    </main>
  );
}
