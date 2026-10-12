import { isDemoMode } from "../lib/preview";
import { t, type Locale } from "../lib/i18n";

/** Persistent banner marking demo builds. Rendered on every demo page so
 * synthetic content can never be mistaken for real data or results. */
export function DemoBanner({ locale }: { locale: Locale }) {
  if (!isDemoMode()) return null;
  return (
    <div className="tp-demo-banner" role="note">
      <strong>{t(locale, "preview.only")}: </strong>
      {t(locale, "demo.banner")}
    </div>
  );
}

/** Inline marker for individual preview-only sections. */
export function PreviewOnly({ locale, children }: { locale: Locale; children?: React.ReactNode }) {
  return (
    <div className="tp-preview-only">
      <span className="tp-pill">{t(locale, "preview.only")}</span>
      <p className="tp-muted">{t(locale, "preview.comingSoon")}</p>
      {children}
    </div>
  );
}
