"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { DemoBanner } from "../../components/Preview";
import { ApiRequestError, login, register, verifyAccount } from "../../lib/api";
import { dirOf, t, type Locale } from "../../lib/i18n";
import { isDemoMode } from "../../lib/preview";

/** Sign-in / registration. One primary action per mode; server errors shown plainly. */
export default function LoginPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firm, setFirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dirOf(locale);
  }, [locale]);

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
    <main>
      <p>
        <Link href="/">← {t(locale, "auth.back")}</Link>
      </p>
      <h1>{mode === "login" ? t(locale, "auth.signin") : t(locale, "auth.createAccount")}</h1>
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
      ) : null}
      <div className="tp-actions" role="group" aria-label="locale">
        <Button onClick={() => setLocale("en")} disabled={locale === "en"}>
          English
        </Button>
        <Button onClick={() => setLocale("ar")} disabled={locale === "ar"}>
          العربية
        </Button>
      </div>
      {error ? <Alert message={error} /> : null}
      {notice ? (
        <div className="tp-card" role="status">
          {notice}
        </div>
      ) : null}
      <form onSubmit={submit}>
        <p>
          <label>
            {t(locale, "auth.email")}
            <br />
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
        </p>
        <p>
          <label>
            {t(locale, "auth.password")}
            <br />
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        </p>
        {mode === "register" ? (
          <p>
            <label>
              {t(locale, "auth.firmName")}
              <br />
              <input required value={firm} onChange={(e) => setFirm(e.target.value)} />
            </label>
          </p>
        ) : null}
        <div className="tp-actions">
          <Button type="submit" disabled={busy}>
            {mode === "login" ? t(locale, "auth.signin") : t(locale, "auth.createAccount")}
          </Button>
        </div>
      </form>
      <div className="tp-actions">
        <Button type="button" disabled={busy} onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? t(locale, "auth.needAccount") : t(locale, "auth.haveAccount")}
        </Button>
      </div>
    </main>
  );
}
