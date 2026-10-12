"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../components/Preview";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { dirOf, t, type Locale } from "../../lib/i18n";

function SimplePlaceholder({ titleKey }: { titleKey: string }) {
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
      <h1>{t(locale, titleKey)}</h1>
      <PreviewOnly locale={locale} />
    </main>
  );
}

/** Reports index: honest placeholder until versioned exports land (EP-11 scope). */
export default function ReportsPage() {
  return <SimplePlaceholder titleKey="nav.reports" />;
}
