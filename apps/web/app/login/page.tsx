"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { ApiRequestError, login, register, verifyAccount } from "../../lib/api";

/** Sign-in / registration. One primary action per mode; server errors shown plainly. */
export default function LoginPage() {
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
          setNotice("Account created. Check your email to verify, then sign in.");
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
        <Link href="/">← Back</Link>
      </p>
      <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
      {error ? <Alert message={error} /> : null}
      {notice ? (
        <div className="tp-card" role="status">
          {notice}
        </div>
      ) : null}
      <form onSubmit={submit}>
        <p>
          <label>
            Email
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
            Password
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
              Firm name
              <br />
              <input required value={firm} onChange={(e) => setFirm(e.target.value)} />
            </label>
          </p>
        ) : null}
        <div className="tp-actions">
          <Button type="submit" disabled={busy}>
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </div>
      </form>
      <div className="tp-actions">
        <Button type="button" disabled={busy} onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
        </Button>
      </div>
    </main>
  );
}
