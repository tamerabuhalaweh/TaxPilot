"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DemoBanner, PreviewOnly } from "../../components/Preview";
import { LocaleControls } from "../../components/LocaleControls";
import { Nav } from "../../components/Nav";
import { t, type Locale } from "../../lib/i18n";
import { dirOf } from "../../lib/i18n";

/** Reviews index: honest placeholder until engagements land (EP-03 scope). */
export default function ReviewsPage() {
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
      <h1>{t(locale, "nav.reviews")}</h1>
      <PreviewOnly locale={locale}>
        <p>
          <Link href="/reviews/new" className="tp-primary">
            {t(locale, "dashboard.newReview")}
          </Link>
        </p>
      </PreviewOnly>
    </main>
  );
}
