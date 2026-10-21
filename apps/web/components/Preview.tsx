import { Icon } from "./Icon";
import { isDemoMode } from "../lib/preview";
import { t, type Locale } from "../lib/i18n";

/** Persistent banner marking demo builds. Rendered on every demo page so
 * synthetic content can never be mistaken for real data or results. */
export function DemoBanner({ locale }: { locale: Locale }) {
  if (!isDemoMode()) return null;
  return (
    <div className="tp-demo-banner" role="note">
      <span className="tp-demo-icon">
        <Icon name="spark" size={18} />
      </span>
      <span>
        <strong>{t(locale, "preview.only")}: </strong>
        {t(locale, "demo.banner")}
      </span>
    </div>
  );
}

/** Inline marker for individual preview-only sections. */
export function PreviewOnly({ locale, children }: { locale: Locale; children?: React.ReactNode }) {
  return (
    <div className="tp-preview-only">
      <span className="tp-pill tp-pill-warning">{t(locale, "preview.only")}</span>
      <p>{t(locale, "preview.comingSoon")}</p>
      {children}
    </div>
  );
}
