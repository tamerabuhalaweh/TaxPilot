"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { LocaleControls } from "../../components/LocaleControls";
import { DemoBanner } from "../../components/Preview";
import { ApiRequestError, login, register, verifyAccount } from "../../lib/api";
import { t } from "../../lib/i18n";
import { isDemoMode } from "../../lib/preview";
import { useLocale } from "../../components/LocaleProvider";

/** Sign-in / registration. One primary action per mode; server errors shown plainly. */
export default function LoginPage() {
  const { locale, setLocale } = useLocale();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firm, setFirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(ev: React.FormEvent): Promise<void> {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "login") {
        await login(email, password);
        window.location.href = "/";
      } else {
        const res = (await register(email, password, firm)) as { verification_token?: string | null };
        if (res.verification_token) {
          // Development builds return the verification token (production never
          // does — email delivery is a follow-up). Complete it transparently.
          await verifyAccount(res.verification_token);
          await login(email, password);
          window.location.href = "/";
        } else {
          setNotice(t(locale, "auth.createdCheckEmail"));
        }
        setMode("login");
      }
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="tp-auth">
      <aside className="tp-auth-brand">
        <Link href="/" className="tp-brand">
          TaxPilot
        </Link>
        <div className="tp-auth-copy">
          <h1>{t(locale, "auth.brandLine")}</h1>
          <p>{t(locale, "auth.brandHint")}</p>
        </div>
        <ul className="tp-auth-features">
          <li>
            <Icon name="shield" size={18} />
            {t(locale, "auth.featureEvidence")}
          </li>
          <li>
            <Icon name="globe" size={18} />
            {t(locale, "auth.featureBilingual")}
          </li>
          <li>
            <Icon name="file" size={18} />
            {t(locale, "auth.featureSynthetic")}
          </li>
        </ul>
      </aside>

      <section className="tp-auth-panel">
        <div className="tp-auth-card">
          <div className="tp-auth-topline">
            <Link href="/" className="tp-back">
              <span aria-hidden="true">←</span>
              {t(locale, "auth.back")}
            </Link>
            <LocaleControls locale={locale} onChange={setLocale} />
          </div>

          <h1>{mode === "login" ? t(locale, "auth.signin") : t(locale, "auth.createAccount")}</h1>
          <p className="tp-auth-lead">
            {mode === "login" ? t(locale, "auth.signinLead") : t(locale, "auth.registerLead")}
          </p>
          <DemoBanner locale={locale} />

          {isDemoMode() ? (
            <div className="tp-card" role="status">
              <p>{t(locale, "demo.authDisabled")}</p>
              <div className="tp-actions">
                <Link href="/" className="tp-primary">
                  {t(locale, "demo.explore")}
                </Link>
              </div>
            </div>
          ) : (
            <>
              {error ? <Alert message={error} /> : null}
              {notice ? (
                <div className="tp-card tp-auth-notice" role="status">
                  {notice}
                </div>
              ) : null}
              <form onSubmit={submit}>
                <div className="tp-field">
                  <label htmlFor="auth-email">{t(locale, "auth.email")}</label>
                  <input
                    id="auth-email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                <div className="tp-field">
                  <label htmlFor="auth-password">{t(locale, "auth.password")}</label>
                  <input
                    id="auth-password"
                    type="password"
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    required
                    minLength={12}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                {mode === "register" ? (
                  <div className="tp-field">
                    <label htmlFor="auth-firm">{t(locale, "auth.firmName")}</label>
                    <input
                      id="auth-firm"
                      required
                      maxLength={200}
                      value={firm}
                      onChange={(e) => setFirm(e.target.value)}
                    />
                  </div>
                ) : null}
                <div className="tp-actions">
                  <Button type="submit" disabled={busy}>
                    {mode === "login" ? t(locale, "auth.signin") : t(locale, "auth.createAccount")}
                  </Button>
                </div>
              </form>
              <div className="tp-auth-switch">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => setMode(mode === "login" ? "register" : "login")}
                >
                  {mode === "login" ? t(locale, "auth.needAccount") : t(locale, "auth.haveAccount")}
                </Button>
              </div>
            </>
          )}
          <p className="tp-auth-note">{t(locale, "auth.securityNote")}</p>
        </div>
      </section>
    </main>
  );
}
