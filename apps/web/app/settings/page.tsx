"use client";

import Link from "next/link";

import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
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
      <PageHeader title={t(locale, "nav.settings")} description={t(locale, "settings.workspace")} />
      <section className="tp-panel">
        <EmptyState
          title={t(locale, "settings.workspace")}
          hint={t(locale, "settings.unavailable")}
          icon="settings"
        />
        <PreviewOnly locale={locale} />
      </section>
    </main>
  );
}
