"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { Alert } from "../../../components/Alert";
import { Button } from "../../../components/Button";
import { EmptyState } from "../../../components/EmptyState";
import { DemoBanner, PreviewOnly } from "../../../components/Preview";
import { StatusPill } from "../../../components/StatusPill";
import { Tabs } from "../../../components/Tabs";
import { useLocale } from "../../../components/LocaleProvider";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import {
  ApiRequestError,
  downloadDemoReport,
  getEngagement,
  listDemoFixtures,
  runDemoRecon,
  type DemoFinding,
  type DemoFixturePayload,
  type DemoMoney,
  type DemoRunPayload,
  type EngagementPayload
} from "../../../lib/api";
import { t } from "../../../lib/i18n";

/** The synthetic marker is a fixed English contract string, repeated on screen
 * and in every export so it can never be mistaken for a processed result. */
const SYNTHETIC_LABEL = "SYNTHETIC DEMO DATA — NOT CUSTOMER RECORDS / NOT A TAX FILING";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; engagement: EngagementPayload }
  | { kind: "not-found" }
  | { kind: "denied" }
  | { kind: "unreachable" };

function money(value: DemoMoney): string {
  return `${value.amount} ${value.currency}`;
}

function statusLabel(locale: "en" | "ar", status: string): string {
  const key = `review.status.${status.toLowerCase()}`;
  return t(locale, key);
}

/** Review workspace: run the restricted synthetic demo and inspect findings. */
export default function ReviewWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [fixtures, setFixtures] = useState<DemoFixturePayload[]>([]);
  const [fixturesDisabled, setFixturesDisabled] = useState(false);
  const [fixtureId, setFixtureId] = useState("");
  const [run, setRun] = useState<DemoRunPayload | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"pdf" | "xlsx" | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getEngagement(id)
      .then((engagement) => setState({ kind: "ready", engagement }))
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.status === 404) setState({ kind: "not-found" });
        else if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
          setState({ kind: "denied" });
        } else setState({ kind: "unreachable" });
      });
    return () => ctrl.abort();
  }, [id]);

  useEffect(() => {
    listDemoFixtures()
      .then((all) => {
        setFixtures(all);
        setFixtureId((prev) => prev || all[0]?.fixture_id || "");
      })
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.code === "DEMO_NOT_ENABLED") setFixturesDisabled(true);
        else setFixturesDisabled(true);
      });
  }, []);

  async function onRun(): Promise<void> {
    if (state.kind !== "ready" || !fixtureId) return;
    setRunError(null);
    setExportError(null);
    setRunning(true);
    try {
      setRun(await runDemoRecon(state.engagement.id, fixtureId));
    } catch (err: unknown) {
      if (err instanceof ApiRequestError && err.code === "DEMO_NOT_ENABLED") setFixturesDisabled(true);
      else setRunError(t(locale, "review.runFailed"));
    } finally {
      setRunning(false);
    }
  }

  async function onExport(format: "pdf" | "xlsx"): Promise<void> {
    if (state.kind !== "ready" || !fixtureId) return;
    setExportError(null);
    setExporting(format);
    try {
      await downloadDemoReport(state.engagement.id, fixtureId, format);
    } catch {
      setExportError(t(locale, "review.exportFailed"));
    } finally {
      setExporting(null);
    }
  }

  function renderFinding(finding: DemoFinding) {
    return (
      <div key={finding.finding_id} className="tp-card tp-finding">
        <div className="tp-finding-head">
          <span className={`tp-sev tp-sev-${finding.severity.toLowerCase()}`}>{finding.severity}</span>
          <strong>{finding.title}</strong>
        </div>
        <p className="tp-muted">{finding.difference}</p>
        <p className="tp-muted">{finding.why}</p>
        {finding.delta ? (
          <p className="tp-muted">
            {t(locale, "review.delta")}: <span className="tp-num">{`${finding.delta} ${finding.delta_currency ?? ""}`.trim()}</span>
          </p>
        ) : null}
        {!finding.review_required ? <StatusPill label={t(locale, "review.informational")} /> : null}
        {finding.evidence.length > 0 ? (
          <div className="tp-table-wrap">
            <table className="tp-table">
              <caption className="tp-muted">{t(locale, "review.evidence")}</caption>
              <thead>
                <tr>
                  <th>{t(locale, "review.evidenceRole")}</th>
                  <th>{t(locale, "review.evidenceDataset")}</th>
                  <th>{t(locale, "review.evidenceRow")}</th>
                  <th>{t(locale, "review.evidenceReference")}</th>
                </tr>
              </thead>
              <tbody>
                {finding.evidence.map((ref, index) => (
                  <tr key={`${finding.finding_id}-${index}`}>
                    <td>{ref.role === "gl" ? t(locale, "review.sourceGL") : t(locale, "review.sourceSales")}</td>
                    <td className="tp-num">{ref.dataset_id}</td>
                    <td className="tp-num">{ref.row_number}</td>
                    <td className="tp-num">{ref.raw_reference}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    );
  }

  function reconciliationTab() {
    if (fixturesDisabled) {
      return <Alert message={t(locale, "review.demoDisabled")} />;
    }
    const total = run ? Number(run.summary.total ?? run.findings.length) : 0;
    const reviewRequired = run ? Number(run.summary.review_required ?? 0) : 0;
    const informational = run ? Number(run.summary.informational ?? 0) : 0;
    const difference = run?.findings.find((f) => f.outcome_kind === "DIFFERENCE");
    return (
      <div>
        <div className="tp-field">
          <label htmlFor="rv-fixture">{t(locale, "review.selectFixture")}</label>
          <select id="rv-fixture" value={fixtureId} onChange={(e) => setFixtureId(e.target.value)}>
            {fixtures.map((f) => (
              <option key={f.fixture_id} value={f.fixture_id}>
                {f.title}
              </option>
            ))}
          </select>
        </div>
        <div className="tp-actions">
          <Button type="button" onClick={onRun} disabled={running || !fixtureId}>
            {running ? t(locale, "review.running") : t(locale, "review.run")}
          </Button>
        </div>
        {runError ? <Alert message={runError} /> : null}
        <div className="tp-synth" role="note">
          {SYNTHETIC_LABEL}
        </div>
        {run ? (
          <div className="tp-card">
            <h3>{t(locale, "review.summary")}</h3>
            <div className="tp-stats">
              <div className="tp-stat">
                <div className="tp-stat-value">{total}</div>
                <div className="tp-stat-label">{t(locale, "review.findingsCount")}</div>
              </div>
              <div className="tp-stat">
                <div className="tp-stat-value">{reviewRequired}</div>
                <div className="tp-stat-label">{t(locale, "review.reviewRequired")}</div>
              </div>
              <div className="tp-stat">
                <div className="tp-stat-value">{informational}</div>
                <div className="tp-stat-label">{t(locale, "review.informational")}</div>
              </div>
              <div className="tp-stat">
                <div className="tp-stat-value">{run.inconclusive ? "1" : "0"}</div>
                <div className="tp-stat-label">{t(locale, "review.inconclusive")}</div>
              </div>
            </div>
            {difference && difference.sales.length > 0 && difference.gl.length > 0 ? (
              <p className="tp-muted">
                {t(locale, "review.salesTotal")}: <span className="tp-num">{money(difference.sales[0])}</span>
                {" · "}
                {t(locale, "review.glTotal")}: <span className="tp-num">{money(difference.gl[0])}</span>
                {" · "}
                {t(locale, "review.delta")}:{" "}
                <span className="tp-num">{`${difference.delta} ${difference.delta_currency ?? ""}`.trim()}</span>
              </p>
            ) : null}
            <p className="tp-muted tp-num">
              {t(locale, "review.fingerprint")}: {run.findings_fingerprint.slice(0, 12)}
            </p>
          </div>
        ) : (
          <EmptyState title={t(locale, "review.noRunTitle")} hint={t(locale, "review.noRun")} />
        )}
      </div>
    );
  }

  function findingsTab() {
    if (fixturesDisabled) return <Alert message={t(locale, "review.demoDisabled")} />;
    if (!run) return <EmptyState title={t(locale, "review.noRunTitle")} hint={t(locale, "review.runFirst")} />;
    return <div>{run.findings.map(renderFinding)}</div>;
  }

  function reportsTab() {
    if (fixturesDisabled) return <Alert message={t(locale, "review.demoDisabled")} />;
    if (!run) return <EmptyState title={t(locale, "review.noRunTitle")} hint={t(locale, "review.runFirst")} />;
    return (
      <div>
        <div className="tp-synth" role="note">
          {SYNTHETIC_LABEL}
        </div>
        <p className="tp-muted">{t(locale, "review.reportsHint")}</p>
        <div className="tp-actions">
          <Button type="button" onClick={() => onExport("pdf")} disabled={exporting !== null}>
            {exporting === "pdf" ? t(locale, "review.exporting") : t(locale, "review.reportPdf")}
          </Button>
          <Button type="button" onClick={() => onExport("xlsx")} disabled={exporting !== null}>
            {exporting === "xlsx" ? t(locale, "review.exporting") : t(locale, "review.reportXlsx")}
          </Button>
        </div>
        {exportError ? <Alert message={exportError} /> : null}
      </div>
    );
  }

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
      <p>
        <Link href="/reviews">← {t(locale, "nav.reviews")}</Link>
      </p>
      {state.kind === "not-found" ? (
        <EmptyState title={t(locale, "review.notFound")} hint={t(locale, "review.notFoundHint")} />
      ) : state.kind === "denied" ? (
        <div className="tp-actions">
          <EmptyState title={t(locale, "dashboard.signinRequired")} hint={t(locale, "dashboard.signinRequiredHint")} />
          <Link href="/login" className="tp-primary">
            {t(locale, "dashboard.signin")}
          </Link>
        </div>
      ) : state.kind === "unreachable" ? (
        <Alert message={t(locale, "review.loadError")} />
      ) : state.kind === "ready" ? (
        <>
          <h1>{t(locale, "review.workspaceTitle")}</h1>
          <p className="tp-muted">
            {t(locale, "review.periodStart")}: <span className="tp-num">{state.engagement.period_start}</span>
            {" – "}
            <span className="tp-num">{state.engagement.period_end}</span>
            {" · "}
            {t(locale, "review.statusLabel")}: {statusLabel(locale, state.engagement.status)}
          </p>
          <Tabs
            tabs={[
              { id: "reconciliation", label: t(locale, "workspace.reconciliation"), content: reconciliationTab() },
              { id: "findings", label: t(locale, "workspace.findings"), content: findingsTab() },
              { id: "reports", label: t(locale, "workspace.reports"), content: reportsTab() },
              { id: "documents", label: t(locale, "workspace.documents"), content: <PreviewOnly locale={locale} /> }
            ]}
          />
        </>
      ) : (
        <p className="tp-muted">{t(locale, "review.loading")}</p>
      )}
    </main>
  );
}
