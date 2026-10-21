"use client";

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";

import { Alert } from "../../../components/Alert";
import { Button } from "../../../components/Button";
import { EmptyState } from "../../../components/EmptyState";
import { DemoBanner } from "../../../components/Preview";
import { StatusPill } from "../../../components/StatusPill";
import { Tabs } from "../../../components/Tabs";
import { useLocale } from "../../../components/LocaleProvider";
import { LocaleControls } from "../../../components/LocaleControls";
import { Nav } from "../../../components/Nav";
import {
  ApiRequestError,
  downloadDemoReport,
  getClient,
  getEngagement,
  listDemoFixtures,
  runDemoRecon,
  type DemoFinding,
  type DemoFixturePayload,
  type DemoMoney,
  type DemoRunPayload,
  type EngagementPayload
} from "../../../lib/api";
import { t, type Locale } from "../../../lib/i18n";

/** The synthetic marker is a fixed English contract string, repeated on screen
 * and in every export so it can never be mistaken for a processed result. */
const SYNTHETIC_LABEL = "SYNTHETIC DEMO DATA — NOT CUSTOMER RECORDS / NOT A TAX FILING";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; engagement: EngagementPayload }
  | { kind: "not-found" }
  | { kind: "denied" }
  | { kind: "unreachable" };

type FindingFilter = "all" | "review" | "info";

const SEVERITY_RANK: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

function money(value: DemoMoney): string {
  return `${value.amount} ${value.currency}`;
}

function statusLabel(locale: Locale, status: string): string {
  return t(locale, `review.status.${status.toLowerCase()}`);
}

const OUTCOME_LABEL_KEYS: Record<string, string> = {
  RECONCILED: "review.reconciledOutcome",
  DIFFERENCE: "review.differenceOutcome",
  MISSING_GL: "review.missingGlOutcome",
  MISSING_SALES: "review.missingSalesOutcome",
  INCONCLUSIVE_COVERAGE: "review.inconclusiveOutcome"
};

function outcomeLabel(locale: Locale, outcome: string): string {
  return t(locale, OUTCOME_LABEL_KEYS[outcome] ?? "review.inconclusiveOutcome");
}

function typeLabel(locale: Locale, reviewType: string): string {
  return reviewType === "JOFO" ? t(locale, "review.typeJofotara") : t(locale, "review.typeSalesGl");
}

function label(locale: Locale, key: string, fallback: string): string {
  const text = t(locale, key);
  return text === key ? fallback : text;
}

function orderedFindings(findings: DemoFinding[]): DemoFinding[] {
  return [...findings].sort((a, b) => {
    if (a.review_required !== b.review_required) return a.review_required ? -1 : 1;
    const delta = (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3);
    return delta !== 0 ? delta : 0;
  });
}

function conclusionDetail(run: DemoRunPayload, locale: Locale): string {
  const conclusion = run.conclusion;
  if (conclusion.status === "BLOCKED") return t(locale, "review.conclusionBlockedHint");
  if (conclusion.status === "NO_REVIEW_ITEMS") return t(locale, "review.conclusionNoItemsHint");
  const parts: string[] = [];
  const differing = conclusion.currency_results
    .filter((result) => result.outcome === "DIFFERENCE")
    .map((result) => result.currency);
  if (differing.length > 0) {
    const key = differing.length === 1 ? "review.diffCurrenciesOne" : "review.diffCurrenciesMany";
    parts.push(
      t(locale, key)
        .replace("{currencies}", differing.join(", "))
        .replace("{count}", String(differing.length))
    );
  }
  const incomplete = conclusion.coverage;
  if (incomplete.scope === "CURRENCIES") {
    const key = incomplete.currencies.length === 1 ? "review.coverageIncompleteOne" : "review.coverageIncompleteMany";
    parts.push(t(locale, key).replace("{currencies}", incomplete.currencies.join(", ")));
  } else if (incomplete.scope === "WHOLE_RUN") {
    parts.push(t(locale, "review.coverageIncompleteWhole"));
  }
  return parts.length > 0 ? parts.join(" ") : t(locale, "review.conclusionReviewRequiredHint");
}

function datasetName(locale: Locale, datasetId: string): string {
  if (datasetId.startsWith("SYNTHETIC-SALES")) return t(locale, "review.datasetSales");
  if (datasetId.startsWith("SYNTHETIC-GL")) return t(locale, "review.datasetGL");
  return datasetId;
}

/** Review workspace: run the restricted synthetic demo and inspect findings.
 *
 * REC-UI-01 F1: the displayed run and the exported document are one unit. A
 * selection change invalidates the run, an in-flight response from a previous
 * selection is discarded, and exports always use the run's own fixture and
 * fingerprints (never the live selection).
 *
 * REC-UI-02: the workspace states the client, review type and conclusion in
 * plain language, orders findings review-first, exposes the engine's "what to
 * check next" guidance, and labels English engine text honestly in Arabic. */
export default function ReviewWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { locale, setLocale } = useLocale();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [clientName, setClientName] = useState<string | null>(null);
  const [fixtures, setFixtures] = useState<DemoFixturePayload[]>([]);
  const [fixturesDisabled, setFixturesDisabled] = useState(false);
  const [fixtureId, setFixtureId] = useState("");
  const [run, setRun] = useState<DemoRunPayload | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"pdf" | "xlsx" | null>(null);
  const [filter, setFilter] = useState<FindingFilter>("all");
  const runGeneration = useRef(0);

  const selectedFixture = fixtures.find((fixture) => fixture.fixture_id === fixtureId) ?? null;

  useEffect(() => {
    getEngagement(id)
      .then((engagement) => {
        setState({ kind: "ready", engagement });
        getClient(engagement.client_id)
          .then((client) => setClientName(client.name))
          .catch(() => setClientName(null));
      })
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.status === 404) setState({ kind: "not-found" });
        else if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
          setState({ kind: "denied" });
        } else setState({ kind: "unreachable" });
      });
  }, [id]);

  useEffect(() => {
    listDemoFixtures()
      .then((all) => {
        setFixtures(all);
        setFixtureId((prev) => prev || all[0]?.fixture_id || "");
      })
      .catch(() => setFixturesDisabled(true));
  }, []);

  function onFixtureChange(next: string): void {
    // Invalidate any displayed result and any response still in flight: the
    // next run must be for the newly selected fixture.
    runGeneration.current += 1;
    setFixtureId(next);
    setRun(null);
    setRunning(false);
    setRunError(null);
    setExportError(null);
    setFilter("all");
  }

  async function onRun(): Promise<void> {
    if (state.kind !== "ready" || !fixtureId) return;
    const requestedFixture = fixtureId;
    const generation = ++runGeneration.current;
    setRun(null);
    setRunError(null);
    setExportError(null);
    setFilter("all");
    setRunning(true);
    try {
      const payload = await runDemoRecon(state.engagement.id, requestedFixture);
      // Ignore a stale response if the selection changed while it was running.
      if (generation !== runGeneration.current || payload.fixture_id !== requestedFixture) return;
      setRun(payload);
    } catch (err: unknown) {
      if (generation !== runGeneration.current) return;
      if (err instanceof ApiRequestError && err.code === "DEMO_NOT_ENABLED") setFixturesDisabled(true);
      else setRunError(t(locale, "review.runFailed"));
    } finally {
      if (generation === runGeneration.current) setRunning(false);
    }
  }

  async function onExport(format: "pdf" | "xlsx"): Promise<void> {
    if (state.kind !== "ready" || !run) return;
    setExportError(null);
    setExporting(format);
    try {
      // Always export the displayed run, not whatever is selected now.
      await downloadDemoReport(
        state.engagement.id,
        {
          fixtureId: run.fixture_id,
          reconFingerprint: run.recon_fingerprint,
          findingsFingerprint: run.findings_fingerprint
        },
        format
      );
    } catch (err: unknown) {
      if (err instanceof ApiRequestError && err.code === "STATE_CONFLICT") {
        setExportError(t(locale, "review.exportMismatch"));
      } else {
        setExportError(t(locale, "review.exportFailed"));
      }
    } finally {
      setExporting(null);
    }
  }

  function severityLabel(value: string): string {
    const key = `review.severity.${value.toLowerCase()}`;
    return label(locale, key, value);
  }

  function renderFinding(finding: DemoFinding) {
    return (
      <div key={finding.finding_id} className="tp-card tp-finding">
        <div className="tp-finding-head">
          <span className={`tp-sev tp-sev-${finding.severity.toLowerCase()}`}>{severityLabel(finding.severity)}</span>
          <span className="tp-pill">{label(locale, `review.kind.${finding.outcome_kind}`, finding.outcome_kind)}</span>
          <span className="tp-pill">
            {label(locale, `review.category.${finding.category}`, finding.category)}
          </span>
          {finding.review_required ? (
            <StatusPill label={t(locale, "review.reviewRequired")} />
          ) : null}
        </div>
        <h3 className="tp-engine" lang="en" dir="ltr">
          {finding.title}
        </h3>
        <p className="tp-muted">
          <span className="tp-pill tp-code">{t(locale, "review.engineText")}</span>
        </p>
        <dl className="tp-finding-fields">
          <div>
            <dt>{t(locale, "review.whatCompared")}</dt>
            <dd lang="en" dir="ltr">
              {finding.compared}
            </dd>
          </div>
          <div>
            <dt>{t(locale, "review.whatFound")}</dt>
            <dd lang="en" dir="ltr">
              {finding.difference}
            </dd>
          </div>
          <div>
            <dt>{t(locale, "review.whyMatters")}</dt>
            <dd lang="en" dir="ltr">
              {finding.why}
            </dd>
          </div>
          <div className="tp-guidance">
            <dt>{t(locale, "review.checkNext")}</dt>
            <dd lang="en" dir="ltr">
              {finding.guidance}
            </dd>
          </div>
        </dl>
        {finding.delta ? (
          <p className="tp-muted">
            {t(locale, "review.delta")}:{" "}
            <span className="tp-num">{`${finding.delta} ${finding.delta_currency ?? ""}`.trim()}</span>
          </p>
        ) : null}
        {finding.evidence.length > 0 ? (
          <div className="tp-table-wrap">
            <table className="tp-table tp-evidence">
              <caption>
                {t(locale, "review.evidence")} · {t(locale, "review.syntheticEvidenceNote")}
              </caption>
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
                    <td data-label={t(locale, "review.evidenceRole")}>
                      {ref.role === "gl" ? t(locale, "review.sourceGL") : t(locale, "review.sourceSales")}
                    </td>
                    <td data-label={t(locale, "review.evidenceDataset")}>
                      <span>{datasetName(locale, ref.dataset_id)}</span>{" "}
                      <span className="tp-num tp-code">{ref.dataset_id}</span>
                    </td>
                    <td data-label={t(locale, "review.evidenceRow")} className="tp-num">
                      {ref.row_number}
                    </td>
                    <td data-label={t(locale, "review.evidenceReference")} className="tp-num">
                      {ref.raw_reference}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <details className="tp-technical">
          <summary>{t(locale, "review.technical")}</summary>
          <dl className="tp-kv">
            <div>
              <dt>{t(locale, "review.rule")}</dt>
              <dd className="tp-num">{finding.rule}</dd>
            </div>
            <div>
              <dt>{t(locale, "review.kind")}</dt>
              <dd>
                {label(locale, `review.kind.${finding.outcome_kind}`, finding.outcome_kind)}{" "}
                <span className="tp-num tp-code">{finding.outcome_kind}</span>
              </dd>
            </div>
            <div>
              <dt>{t(locale, "review.category")}</dt>
              <dd className="tp-num">{finding.category}</dd>
            </div>
            <div>
              <dt>{t(locale, "review.findingId")}</dt>
              <dd className="tp-num">{finding.finding_id}</dd>
            </div>
            {run ? (
              <>
                <div>
                  <dt>{t(locale, "review.policy")}</dt>
                  <dd className="tp-num">
                    {run.policy_id ?? "—"}
                    {run.policy_version ? ` · v${run.policy_version}` : ""}
                  </dd>
                </div>
                <div>
                  <dt>{t(locale, "review.rulesVersion")}</dt>
                  <dd className="tp-num">{run.rules_version}</dd>
                </div>
              </>
            ) : null}
            {finding.rationale.length > 0 ? (
              <div>
                <dt>{t(locale, "review.rationale")}</dt>
                <dd className="tp-num">{finding.rationale.join(", ")}</dd>
              </div>
            ) : null}
            {finding.flags.length > 0 ? (
              <div>
                <dt>{t(locale, "review.flags")}</dt>
                <dd className="tp-num">{finding.flags.join(", ")}</dd>
              </div>
            ) : null}
          </dl>
        </details>
      </div>
    );
  }

  function reconciliationTab() {
    if (fixturesDisabled) {
      return <Alert message={t(locale, "review.demoDisabled")} />;
    }
    const engagement = state.kind === "ready" ? state.engagement : null;
    const total = run ? Number(run.summary.total ?? run.findings.length) : 0;
    const reviewRequired = run ? Number(run.summary.review_required ?? 0) : 0;
    const informational = run ? Number(run.summary.informational ?? 0) : 0;
    const difference = run?.findings.find((f) => f.outcome_kind === "DIFFERENCE");
    const fixturePeriod = selectedFixture
      ? `${selectedFixture.period_start} – ${selectedFixture.period_end}`
      : "—";
    const periodMismatch =
      engagement !== null &&
      selectedFixture !== null &&
      (selectedFixture.period_start !== engagement.period_start ||
        selectedFixture.period_end !== engagement.period_end);
    const conclusion = run?.conclusion ?? null;
    const conclusionHeadline = conclusion
      ? conclusion.status === "BLOCKED"
        ? t(locale, "review.conclusionBlocked")
        : conclusion.status === "NO_REVIEW_ITEMS"
          ? t(locale, "review.conclusionNoItems")
          : t(locale, "review.conclusionReviewRequired")
      : "";
    const coverage = conclusion?.coverage;
    const inconclusiveCount =
      !coverage || coverage.scope === "COMPLETE"
        ? "0"
        : coverage.scope === "CURRENCIES"
          ? String(coverage.currencies.length)
          : "—";
    const coverageMessage = !coverage
      ? ""
      : coverage.scope === "COMPLETE"
        ? t(locale, "review.coverageComplete")
        : coverage.scope === "BLOCKED"
          ? t(locale, "review.coverageBlocked")
          : coverage.scope === "WHOLE_RUN"
            ? t(locale, "review.coverageIncompleteWhole")
            : t(
                locale,
                coverage.currencies.length === 1
                  ? "review.coverageIncompleteOne"
                  : "review.coverageIncompleteMany"
              ).replace("{currencies}", coverage.currencies.join(", "));
    return (
      <div>
        <div className="tp-field">
          <label htmlFor="rv-fixture">{t(locale, "review.selectFixture")}</label>
          <select id="rv-fixture" value={fixtureId} onChange={(e) => onFixtureChange(e.target.value)}>
            {fixtures.map((f) => (
              <option key={f.fixture_id} value={f.fixture_id}>
                {f.title}
              </option>
            ))}
          </select>
        </div>
        <p className="tp-muted">
          {t(locale, "review.fixturePeriod")}:{" "}
          <span className="tp-num" dir="ltr">
            {fixturePeriod}
          </span>
        </p>
        {periodMismatch ? <p className="tp-muted">{t(locale, "review.periodMismatch")}</p> : null}
        <div className="tp-actions">
          <Button type="button" onClick={onRun} disabled={running || !fixtureId}>
            {running ? t(locale, "review.running") : t(locale, "review.run")}
          </Button>
        </div>
        {runError ? <Alert message={runError} /> : null}
        <div className="tp-synth" role="note">
          {SYNTHETIC_LABEL}
        </div>
        <p className="tp-muted">{t(locale, "review.syntheticDataNote")}</p>
        {run ? (
          <div className="tp-card">
            <h3>{t(locale, "review.summary")}</h3>
            <p className="tp-muted">
              {t(locale, "review.engagementPeriod")}:{" "}
              <span className="tp-num" dir="ltr">
                {engagement?.period_start} – {engagement?.period_end}
              </span>
            </p>
            <p className="tp-muted">
              {t(locale, "review.fixturePeriod")}:{" "}
              <span className="tp-num" dir="ltr">
                {run.period_start} – {run.period_end}
              </span>
            </p>
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
                <div className="tp-stat-value">{inconclusiveCount}</div>
                <div className="tp-stat-label">{t(locale, "review.inconclusive")}</div>
              </div>
            </div>

            <div className={`tp-conclusion tp-conclusion-${run.conclusion.status.toLowerCase()}`} role="status">
              <strong>{conclusionHeadline}</strong>
              <p>{conclusionDetail(run, locale)}</p>
            </div>

            <h4>{t(locale, "review.currencyResults")}</h4>
            {run.conclusion.currency_results.length === 0 ? (
              <p className="tp-muted">{t(locale, "review.noCurrencyResults")}</p>
            ) : (
              <div className="tp-table-wrap">
                <table className="tp-table tp-currency">
                  <thead>
                    <tr>
                      <th>{t(locale, "review.currency")}</th>
                      <th>{t(locale, "review.salesTotal")}</th>
                      <th>{t(locale, "review.glTotal")}</th>
                      <th>{t(locale, "review.delta")}</th>
                      <th>{t(locale, "review.tolerance")}</th>
                      <th>{t(locale, "review.outcome")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.conclusion.currency_results.map((result) => (
                      <tr key={`${result.currency}-${result.outcome}`}>
                        <td className="tp-num" data-label={t(locale, "review.currency")}>
                          {result.currency}
                        </td>
                        <td className="tp-num" data-label={t(locale, "review.salesTotal")}>
                          {result.sales_total ?? "—"}
                        </td>
                        <td className="tp-num" data-label={t(locale, "review.glTotal")}>
                          {result.gl_total ?? "—"}
                        </td>
                        <td className="tp-num" data-label={t(locale, "review.delta")}>
                          {result.delta ?? "—"}
                        </td>
                        <td className="tp-num" data-label={t(locale, "review.tolerance")}>
                          {run.tolerance ?? "—"}
                        </td>
                        <td data-label={t(locale, "review.outcome")}>
                          {outcomeLabel(locale, result.outcome)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
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

            <div className="tp-coverage">
              <h4>{t(locale, "review.coverage")}</h4>
              {run.conclusion.coverage.scope === "COMPLETE" ? (
                <p className="tp-muted">{t(locale, "review.coverageComplete")}</p>
              ) : (
                <>
                  <p>{coverageMessage}</p>
                  {run.conclusion.coverage.reasons.length > 0 ? (
                    <>
                      <h5>{t(locale, "review.coverageReasons")}</h5>
                      <ul>
                        {run.conclusion.coverage.reasons.map((reason, index) => (
                          <li key={reason}>
                            {label(
                              locale,
                              `review.reason.${reason}`,
                              run.conclusion.coverage.explanations[index] ?? reason
                            )}{" "}
                            <span className="tp-num tp-code">{reason}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </>
              )}
            </div>

            <div className="tp-caution" role="note">
              <strong>{t(locale, "review.cautionTitle")}</strong>
              <p>{t(locale, "review.caution")}</p>
            </div>

            <p className="tp-muted">
              {t(locale, "review.runFixture")}: <span className="tp-num">{run.fixture_id}</span>
            </p>
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
    const ordered = orderedFindings(run.findings);
    const counts = {
      all: ordered.length,
      review: ordered.filter((finding) => finding.review_required).length,
      info: ordered.filter((finding) => !finding.review_required).length
    };
    const visible = ordered.filter((finding) => {
      if (filter === "review") return finding.review_required;
      if (filter === "info") return !finding.review_required;
      return true;
    });
    const options: { id: FindingFilter; label: string }[] = [
      { id: "all", label: `${t(locale, "review.filterAll")} (${counts.all})` },
      { id: "review", label: `${t(locale, "review.filterReview")} (${counts.review})` },
      { id: "info", label: `${t(locale, "review.filterInfo")} (${counts.info})` }
    ];
    return (
      <div>
        <div className="tp-filterbar" role="group" aria-label={t(locale, "review.filters")}>
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              className={filter === option.id ? "tp-chip tp-chip-active" : "tp-chip"}
              aria-pressed={filter === option.id}
              onClick={() => setFilter(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="tp-muted">{t(locale, "review.sortNote")}</p>
        {visible.length === 0 ? (
          <EmptyState title={t(locale, "review.filterAll")} hint={t(locale, "review.noReviewItems")} />
        ) : (
          visible.map(renderFinding)
        )}
      </div>
    );
  }

  function reportsTab() {
    if (fixturesDisabled) {
      return <Alert message={t(locale, "review.demoDisabled")} />;
    }
    if (!run) return <EmptyState title={t(locale, "review.noRunTitle")} hint={t(locale, "review.runFirst")} />;
    return (
      <div>
        <div className="tp-synth" role="note">
          {SYNTHETIC_LABEL}
        </div>
        <p className="tp-muted">{t(locale, "review.reportsHint")}</p>
        <div className="tp-card">
          <h3>{t(locale, "review.reportsContents")}</h3>
          <ul>
            <li>{t(locale, "review.reportIncludesConclusion")}</li>
            <li>{t(locale, "review.reportIncludesFindings")}</li>
            <li>{t(locale, "review.reportIncludesTrace")}</li>
          </ul>
          <p className="tp-muted">{t(locale, "review.reportOrderNote")}</p>
          <h3>{t(locale, "review.reportLanguage")}</h3>
          <p className="tp-muted">{t(locale, "review.reportLanguageNote")}</p>
        </div>
        <p className="tp-muted">
          {t(locale, "review.exportBinding")}:{" "}
          <span className="tp-num">
            {run.fixture_id} · {run.findings_fingerprint.slice(0, 12)}
          </span>
        </p>
        <p className="tp-muted">{t(locale, "review.exportReady")}</p>
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
          <p className="tp-workspace-meta">
            <span>
              {t(locale, "review.clientLabel")}:{" "}
              <Link href={`/clients/${state.engagement.client_id}`}>{clientName ?? "—"}</Link>
            </span>
            <span>{t(locale, "review.reviewTypeLabel")}: {typeLabel(locale, state.engagement.review_type)}</span>
            <StatusPill label={statusLabel(locale, state.engagement.status)} />
            <span className="tp-pill">{t(locale, "review.syntheticTag")}</span>
          </p>
          <p className="tp-muted">
            {t(locale, "review.engagementPeriod")}:{" "}
            <span className="tp-num" dir="ltr">
              {state.engagement.period_start} – {state.engagement.period_end}
            </span>
          </p>
          <p className="tp-muted">{t(locale, "review.workspaceHint")}</p>
          <Tabs
            tabs={[
              { id: "reconciliation", label: t(locale, "workspace.reconciliation"), content: reconciliationTab() },
              { id: "findings", label: t(locale, "workspace.findings"), content: findingsTab() },
              { id: "reports", label: t(locale, "workspace.reports"), content: reportsTab() },
              {
                id: "documents",
                label: t(locale, "workspace.documents"),
                content: (
                  <div className="tp-card">
                    <h2>{t(locale, "review.documentsUnavailable")}</h2>
                    <p className="tp-muted">{t(locale, "review.documentsHint")}</p>
                  </div>
                )
              }
            ]}
          />
        </>
      ) : (
        <p className="tp-muted">{t(locale, "review.loading")}</p>
      )}
    </main>
  );
}
