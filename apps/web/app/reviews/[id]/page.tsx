"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../../components/Preview";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import { Tabs } from "../../../components/Tabs";
import { dirOf, t, type Locale } from "../../../lib/i18n";

/** Review workspace: tabbed sections, honestly marked until the engine lands. */
export default function ReviewWorkspacePage() {
  const [locale, setLocale] = useState<Locale>("en");
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dirOf(locale);
  }, [locale]);
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
        <Link href="/reviews">← {t(locale, "nav.reviews")}</Link>
      </p>
      <h1>{t(locale, "dashboard.newReview")}</h1>
      <Tabs
        tabs={[
          { id: "documents", label: t(locale, "workspace.documents"), content: <PreviewOnly locale={locale} /> },
          { id: "mapping", label: t(locale, "workspace.mapping"), content: <PreviewOnly locale={locale} /> },
          {
            id: "reconciliation",
            label: t(locale, "workspace.reconciliation"),
            content: <PreviewOnly locale={locale} />
          },
          { id: "findings", label: t(locale, "workspace.findings"), content: <PreviewOnly locale={locale} /> },
          { id: "reports", label: t(locale, "workspace.reports"), content: <PreviewOnly locale={locale} /> }
        ]}
      />
    </main>
  );
}
