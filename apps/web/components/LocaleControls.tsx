"use client";

import type { Locale } from "../lib/i18n";

export function LocaleControls({
  locale,
  onChange
}: {
  locale: Locale;
  onChange: (next: Locale) => void;
}) {
  return (
    <div className="tp-locale" role="group" aria-label="locale">
      <button
        type="button"
        className={locale === "en" ? "tp-locale-active" : undefined}
        aria-label="English"
        aria-pressed={locale === "en"}
        onClick={() => onChange("en")}
      >
        EN
      </button>
      <button
        type="button"
        className={locale === "ar" ? "tp-locale-active" : undefined}
        aria-label="العربية"
        aria-pressed={locale === "ar"}
        onClick={() => onChange("ar")}
      >
        عربي
      </button>
    </div>
  );
}
