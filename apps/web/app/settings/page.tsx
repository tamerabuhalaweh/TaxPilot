"use client";

import Link from "next/link";

import { DemoBanner, PreviewOnly } from "../../components/Preview";
import { useLocale } from "../../components/LocaleProvider";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { t } from "../../lib/i18n";

/** Settings index: honest placeholder until firm/workspace settings land. */
export default function SettingsPage() {
  const { locale, setLocale } = useLocale();
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




