"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../components/Preview";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { dirOf, t, type Locale } from "../../lib/i18n";

/** Settings index: honest placeholder until firm/workspace settings land. */
export default function SettingsPage() {
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
      <h1>{t(locale, "nav.settings")}</h1>
      <PreviewOnly locale={locale} />
    </main>
  );
}
