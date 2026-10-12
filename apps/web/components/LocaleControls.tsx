"use client";

import Link from "next/link";
import { Button } from "./Button";
import type { Locale } from "../lib/i18n";

export function LocaleControls({
  locale,
  onChange
}: {
  locale: Locale;
  onChange: (next: Locale) => void;
}) {
  return (
    <div className="tp-actions" role="group" aria-label="locale">
      <Button onClick={() => onChange("en")} disabled={locale === "en"}>
        English
      </Button>
      <Button onClick={() => onChange("ar")} disabled={locale === "ar"}>
        العربية
      </Button>
    </div>
  );
}
