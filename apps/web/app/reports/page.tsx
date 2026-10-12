"use client";

import Link from "next/link";

import { DemoBanner, PreviewOnly } from "../../components/Preview";
import { useLocale } from "../../components/LocaleProvider";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { t } from "../../lib/i18n";

function SimplePlaceholder({ titleKey }: { titleKey: string }) {
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
      <h1>{t(locale, titleKey)}</h1>
      <PreviewOnly locale={locale} />
    </main>
  );
}

/** Reports index: honest placeholder until versioned exports land (EP-11 scope). */
export default function ReportsPage() {
  return <SimplePlaceholder titleKey="nav.reports" />;
}




