# CUSTOMER-DISCOVERY-01 - Jordan accountant demo and buyer-validation kit

**Status:** user-facing synthetic demo READY for facilitated sessions; real
financial production BLOCKED. This kit does not assert that any interview has
taken place, that any customer approved the product, or that any price, date, or
legal position is agreed.

**Baseline validated:** `main` merge `3cd5205aa4696925928f365a9576edecc3a4375a`
(PR #76). Post-merge CI run
[39557995322](https://github.com/tamerabuhalaweh/TaxPilot/actions/runs/39557995322)
is 7/7 success at that exact SHA.

**Purpose:** let the Product Owner (PO) run a consistent 10-minute walkthrough
with 2-3 Jordanian accountants, capture attributable consent-aware feedback, and
make an evidence-based decision about a paid pilot. The PO owns outreach,
consent, interviews, and the pilot decision. The AI agent must not conduct or
invent interviews.

**Companion material:** `docs/product/REC-UI-02-demo-script.md` (original
walkthrough), `docs/product/REC-FINDINGS-MEANINGS.md` (outcome wording),
`docs/product/REC-GL-01-boundary.md` (reconciliation boundary),
`docs/product/SEC-SOURCE-01-boundary.md` and
`docs/product/SEC-SOURCE-DEC-decision-dossier.md` (real-data gates),
`docs/engineering/BLOCKERS.md` (open blockers).

## 1. What is ready and what is not

| State | Evidence | Allowed claim |
|---|---|---|
| User-facing synthetic demo | Connected Playwright workflow, exports, EN/AR, desktop and 390 px checks pass at baseline | "You can run a synthetic Sales Register-to-GL reconciliation and inspect/export a labelled report." |
| Paid pilot with real files | **BLOCKED** by source-sample, storage, scanner, release, mapping, onboarding, and legal/DPA gates | "Real client files cannot be processed or stored in this build." |
| Production tax processing | **BLOCKED** | No filing, no official JoFotara verification, no tax conclusion, no approval workflow. |

Do not describe the demo as production, as a filing tool, or as proof that the
reconciliation rules are validated on Jordanian customer files. The built-in
scenario is synthetic engineering data.

## 2. Roles and session setup

- **Facilitator / PO:** runs the script, asks neutral questions, records consent.
- **Note taker (recommended):** captures behavior and verbatim answers; keeps
  the facilitator from leading the respondent.
- **Respondent:** Jordanian accountant or firm decision maker. Use a respondent
  ID (`R1`, `R2`, `R3`) in notes; keep names only in a separate access-controlled
  contact list if needed.
- **Observer (optional):** does not speak during the walkthrough.

Use one browser window and screen sharing. Close personal tabs, notifications,
and any real client records. Do not record audio or video without separate
explicit consent. Do not commit notes, recordings, screenshots, or respondent
identifiers to this repository.

## 3. Prerequisites

- Windows/macOS/Linux with Docker, Python 3.12, and Node 22.x.
- Repository checkout at the baseline SHA above and a clean working tree.
- Docker Postgres and Redis available. The local demo flag is development-only;
  production forces synthetic reconciliation off.
- A desktop browser (current Chrome or Edge) and ability to emulate a 390 x 844
  viewport.
- A local demo account only. Never use a real client's credentials, email
  content, or financial files.

## 4. Start the connected demo (recommended)

Run these from the repository root. Use PowerShell on Windows; the same
commands work in a POSIX shell with normal environment-variable syntax.

Terminal 1 - database and API:

```powershell
docker compose up -d postgres redis
$env:DATABASE_URL = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
$env:REDIS_URL = "redis://localhost:6379/0"
python db/migrate.py
$env:TAXPILOT_DEMO_RECON_ENABLED = "1"
$env:PYTHONPATH = "apps/api"
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

Confirm `http://127.0.0.1:8000/api/v1/health` returns `{"status":"ok",...}`.

Terminal 2 - web app:

```powershell
cd apps/web
npm ci
$env:API_INTERNAL_URL = "http://127.0.0.1:8000"
npm run build
npm start -- --port 3000
```

Open `http://127.0.0.1:3000`.

If the run button says synthetic reconciliation is disabled, the API was started
without `TAXPILOT_DEMO_RECON_ENABLED=1` or the environment is production. Do not
work around a production guard; restart the local API with the flag.

### Visual-preview fallback (no backend)

This build is browser-only: it shows the seeded visual workspace but cannot
register, create a review, run reconciliation, or export real bytes. Use it only
if the connected demo cannot run, and say clearly that it is a visual preview.

```powershell
cd apps/web
$env:NEXT_PUBLIC_PREVIEW_MODE = "demo"
npm run build
npm start -- --port 3001
```

Open `http://127.0.0.1:3001`. The persistent banner and disabled controls are
intentional. Do not claim exports or a completed run in this mode.

## 5. Create the demo account and review

1. Open `/login` and choose **Need an account? Register**.
2. Use a synthetic demo email and a password of at least 12 characters. Use a
   firm name such as `TaxPilot Demo Firm`. Never use a real client's email.
3. In local development the API returns a verification token and the UI
   completes verification automatically. The first registered user becomes the
   `owner` of the new firm; no separate admin seed is required. Do not claim
   that email delivery, password reset, or MFA are available; they are open
   blockers.
4. Open **Clients**, add a client named `Synthetic Demo Client`, and confirm it
   appears.
5. Open **Reviews -> New Review**, select the client, period
   `2026-01-01` to `2026-12-31`, and review type **Sales <-> GL reconciliation**.
6. Press **Start Review**. The workspace opens on **Documents**. The source
   cards are marked preview-only; uploads are deliberately disabled.
7. In the workspace, select the built-in `Synthetic sales <-> GL v1` scenario
   and press **Run reconciliation**.

Expected result:

- Status: `REVIEW_REQUIRED`.
- Conclusion: review required; 3 findings need a person; one currency differs
  beyond tolerance (JOD); USD coverage is incomplete.
- JOD: sales `3500.000`, GL `3400.000`, difference `100.000`.
- USD: `INCONCLUSIVE_COVERAGE` because rows were dropped as duplicates. It is
  **not** a match.
- 5 findings: 3 review-required and 2 informational.

The synthetic scenario period is `2026-01-01` to `2026-12-31`; do not confuse it
with the engagement period entered on the New Review form. Say which period you
are pointing at.

## 6. Ten-minute walkthrough

Schedule 30 minutes: about 10 minutes of demonstration and 15-20 minutes of
questions. Do not rush the feedback portion.

| Time | Action | Say / ask | Observe |
|---|---|---|---|
| 0:00-0:01 | Frame the session | "This is a synthetic prototype. It is not a filing and contains no client data. I want your reaction, including criticism." Confirm consent and whether quotes may be used. | Does the respondent understand the synthetic boundary? |
| 0:01-0:02 | Dashboard | Point out the persistent synthetic banner, measured counts, and recent reviews. | Does the respondent look for real client data or a compliance score? |
| 0:02-0:03 | Clients -> client -> Reviews | Open the seeded review. Show that navigation opens a real workspace. | Can the respondent tell where they are? |
| 0:03-0:05 | Run reconciliation | Select the synthetic scenario and run it. Read the conclusion aloud, then ask: "What is this screen telling you?" | Can they explain the conclusion without prompting? |
| 0:05-0:07 | Currency table and findings | Show JOD `100.000`; show USD `INCONCLUSIVE_COVERAGE`. Open the top finding, **What to check next**, and the evidence rows. Use the severity/kind filter. | Do they understand that equal totals are not proof of completeness? Which finding would they investigate first? |
| 0:07-0:08 | Reports | Open **Reports**. Explain run-bound exports and stale-export rejection. Export PDF and XLSX. Show the summary, findings, evidence, page numbers, and the synthetic footer. | Do the exports match what they hand to a client or reviewer? Is English-only a blocker? |
| 0:08-0:09 | Honest limits | Open **Documents** and **New Review**. State plainly: uploads are disabled; there is no official JoFotara import, no approval/e-signature, no filing, and no real-data processing. | Does the respondent test a missing control? Does the limitation change their interest? |
| 0:09-0:10 | Arabic and mobile | Toggle Arabic; show RTL labels and coverage reasons. Note that engine finding text stays English. At 390 px, show stacked evidence cards. | Is the Arabic sufficient for their team? Which terms must be translated next? |

Close by asking the feedback questions in section 9. Do not promise dates,
prices, legal conclusions, or production availability.

## 7. Demo-readiness checklist

### Before the call

- [ ] Checkout is at `3cd5205aa4696925928f365a9576edecc3a4375a`; `git status`
      is clean.
- [ ] Postgres and Redis are healthy; migrations report nothing pending.
- [ ] API health returns `ok`; the demo flag is set on the API process only.
- [ ] Web build is connected to `http://127.0.0.1:8000`; `/login` shows a form
      (not the demo-build disabled message).
- [ ] A local synthetic account, client, and review exist; the synthetic
      scenario runs.
- [ ] Browser zoom is 100%; desktop viewport is at least 1280 px wide.
- [ ] Notifications and personal tabs are closed; screen share shows the browser
      only.
- [ ] Fallback is ready: visual-preview build on port 3001, with the limitation
      stated if used.
- [ ] Consent script and response template are open in a separate private file.

### During the call

- [ ] The persistent synthetic banner and the visible `SYNTHETIC DEMO DATA`
      label are present before any figure is discussed.
- [ ] **Start Review**, **Run reconciliation**, tabs, filters, locale toggle,
      PDF export, and XLSX export all respond; no dead control is presented as
      working.
- [ ] The conclusion names the JOD difference and the USD coverage gap.
- [ ] The top finding shows **What to check next** and evidence.
- [ ] PDF begins with `%PDF-`; XLSX is a valid ZIP/XLSX file; both carry
      `SYNTHETIC DEMO DATA - NOT CUSTOMER RECORDS / NOT A TAX FILING`.
- [ ] The displayed run's reconciliation/findings fingerprints are the ones used
      for export; a stale tab is rejected rather than returning the wrong file.
- [ ] Arabic produces RTL chrome; engine text remains English and labelled as
      such; no horizontal overflow at 390 px.
- [ ] Uploads and filing are visibly unavailable, not merely omitted.
- [ ] No real client name, file, amount, or screenshot appears anywhere.

### After the call

- [ ] Save notes under the respondent ID in the approved private location.
- [ ] Record consent, quote permission, and any withdrawal request.
- [ ] Do not commit notes or screenshots.
- [ ] Separate observations (what happened) from interpretations (what it might
      mean).
- [ ] Enter the structured capture within 24 hours while memory is fresh, then
      delete audio if recording was allowed and no longer needed.

## 8. Facilitator observation checklist

Record observable behavior, not inferred enthusiasm. Use `Y`, `N`, `PARTIAL`,
or `NOT_OBSERVED`.

| ID | Observation | Result / evidence |
|---|---|---|
| O1 | Found the review workspace without help | |
| O2 | Noticed and read the synthetic banner | |
| O3 | Explained the conclusion in their own words | |
| O4 | Correctly explained why USD is inconclusive | |
| O5 | Found the highest-priority finding | |
| O6 | Used **What to check next** or evidence without prompting | |
| O7 | Understood that equal totals do not prove completeness | |
| O8 | Opened Reports and identified report contents/language | |
| O9 | Downloaded and opened both PDF and XLSX | |
| O10 | Tried an unavailable action (upload, approve, file) | |
| O11 | Noticed that engine text stays English in Arabic UI | |
| O12 | Reported a mobile/RTL layout problem | |
| O13 | Expressed a trust concern or data-handling concern | |
| O14 | Asked about price, onboarding, support, or integration | |
| O15 | Completed the core walkthrough without facilitation | |

Also record:

- Session date/time, duration, browser, viewport, and language.
- Time to explain the conclusion and time to find the top finding.
- Exact points of hesitation or confusion.
- Any statement that the demo is misleading or missing a control.
- Any request that would require real data; stop and record it rather than
  collecting data.

## 9. Structured answer capture

### 9.1 Answer status vocabulary

Every field must use one of these states. Never leave a blank that could be read
as a negative answer, and never infer an answer.

| Code | Meaning |
|---|---|
| `ANSWERED` | Respondent gave a substantive answer; record it verbatim or as a close paraphrase. |
| `DECLINED` | Respondent explicitly refused to answer. Do not pressure them. |
| `NOT_ASKED` | The question was skipped because of time or branching. |
| `UNKNOWN` | Respondent said they do not know or cannot estimate. |
| `NOT_APPLICABLE` | The question does not apply to this respondent. |
| `PARTIAL` | Some information was given; record exactly what is missing. |

"Do not know" is not zero, and "not asked" is not "no". Keep these distinct in
every summary.

### 9.2 Respondent profile and buyer segmentation

| Field | Capture |
|---|---|
| Respondent ID | `R1`, `R2`, `R3` |
| Consent to participate | `ANSWERED` / `DECLINED` |
| Consent to quote | `ANSWERED` / `DECLINED`; if declined, do not quote |
| Role | Partner / senior accountant / tax manager / bookkeeper / operations / IT / other |
| Decision role | Economic buyer / recommender / user / blocker |
| Firm segment | Solo / small firm (2-9) / mid firm (10-49) / large firm (50+) / other |
| Client profile | Number of SME clients; sectors; monthly or annual engagements |
| Reconciliation volume | Reviews per month; source rows per review; currencies |
| Current tools | Excel / accounting ERP / JoFotara portal / other; versions if known |
| Data readiness | Can they provide authorized sample exports? `ANSWERED` / `UNKNOWN` / `DECLINED` |
| Buyer segment | `A` small/mid compliance-heavy firm; `B` tax/audit practice with seasonal volume; `C` larger firm with dedicated ops/IT; `OTHER` |

Segment definitions are for analysis, not claims about the market. Do not infer
firm size or budget from appearance.

### 9.3 Current workflow and time

| Field | Capture |
|---|---|
| Workflow today | Step-by-step, in the respondent's words |
| Tools and handoffs | Who prepares, reviews, and signs off |
| Time per review | Value + unit (minutes/hours) + basis (last review, typical, estimate) |
| Time per month | Value + unit + basis |
| Rework frequency | How often reconciliation differences cause rework |
| Biggest current pain | Respondent's ranking, not the facilitator's |
| Cost of the pain | Only if volunteered; otherwise `UNKNOWN` or `NOT_ASKED` |

### 9.4 Comprehension and evidence usefulness

Ask the respondent to explain the screen before giving a rating. Score
comprehension from the explanation, not from confidence.

| Check | Score | Evidence / exact words |
|---|---|---|
| C1: What is the overall conclusion? | 0-3 | |
| C2: Why is USD not treated as matched? | 0-3 | |
| C3: What would you check first? | 0-3 | |
| C4: What does "equal totals are not proof of completeness" mean? | 0-3 | |
| C5: Which report would you send, and to whom? | 0-3 | |

Rubric: `0` cannot explain; `1` incorrect or major misconception; `2` correct
with a prompt; `3` correct and unprompted. A score of `0` or `1` on C1, C2, or
C4 is a comprehension failure to investigate, not a training problem.

| Field | Capture |
|---|---|
| Most useful evidence | Which row, finding, or report section |
| Least useful / missing evidence | What they could not verify |
| Trust concerns | Wrong number, unclear scope, missing source, stale export, other |
| Language | Was Arabic sufficient? Which engine terms must be translated? |
| Would this reduce review time? | `ANSWERED` / `UNKNOWN` / `DECLINED` + basis |

### 9.5 Reports

| Field | Capture |
|---|---|
| Opened PDF | `Y` / `N` / `NOT_OBSERVED` |
| Opened XLSX | `Y` / `N` / `NOT_OBSERVED` |
| Report matches client/reviewer handoff | `ANSWERED` / `DECLINED` / `UNKNOWN` |
| Missing sections or fields | Exact list |
| English-only acceptable | `ANSWERED` / `DECLINED` / `UNKNOWN` + conditions |
| Stale-export behavior understood | `Y` / `N` / `PARTIAL` |
| Would attach report to a client deliverable | `ANSWERED` / `DECLINED` / `UNKNOWN` + conditions |

### 9.6 Pilot, payment, and conditions

Ask about the decision process before asking about money. Do not propose a price
or anchor the respondent.

| Field | Capture |
|---|---|
| Willing to pilot | `NO` / `MAYBE` / `YES` + reason |
| Pilot timing | Only if volunteered; otherwise `UNKNOWN` or `NOT_ASKED` |
| Willing to pay | `NO` / `MAYBE` / `YES` + conditions |
| Price / budget | Only if volunteered; record currency and unit. Otherwise `NOT_ASKED`, `DECLINED`, or `UNKNOWN`. |
| Who approves spend | Role, not a name unless consent is recorded |
| Must-have conditions | Security, data location, DPA, support, accuracy, integration, training, other |
| Would provide authorized samples | `YES` / `NO` / `MAYBE` / `UNKNOWN` + conditions |
| Next step agreed | Concrete action, owner, and date only if actually agreed |

If asked "How much does it cost?", say: "A price is not set. I am collecting
what would make a paid pilot worth considering." Record the question as a buying
signal, not as a price.

### 9.7 Top three blockers

| Rank | Blocker in respondent's words | Severity (blocker / major / minor) | Frequency | Workaround today | Evidence |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

Do not merge different respondents' blockers in the raw capture. Keep the
respondent ID on each row.

### 9.8 Verbatim quote log

| Respondent | Quote consent | Original quote | Translation (if needed) | Context | Anonymization approved |
|---|---|---|---|---|---|
| | `Y` / `N` | | | | `Y` / `N` |

If quote consent is `N`, do not include the quote in summaries, slides, or the
PR. Use a paraphrase marked `PARAPHRASE - NOT A QUOTE`.

### 9.9 Session debrief

Write these immediately after the session, before comparing respondents:

- What did the respondent understand that surprised us?
- Where did the demo overstate or understate the product?
- Did any control, number, export, or label behave incorrectly?
- Which question was confusing or leading?
- What must we change before the next session?
- Was any real data exposed? If yes, stop and follow the incident/privacy path;
  do not copy it into notes.

## 10. Research ethics and feedback privacy

- Participation is voluntary. The respondent may skip any question, stop the
  demo, or withdraw feedback at any time.
- Disclose the purpose: product discovery, not sales close, tax advice, or a
  compliance audit.
- Use synthetic data only. Do not request, accept, open, or screen-share real
  client registers, GL files, JoFotara exports, invoices, or screenshots.
- Do not record audio or video without explicit consent. Store recordings only
  in the approved private location and delete them when the synthesis is done,
  unless the PO and legal owner require a defined retention period.
- Keep names and contact details separate from response notes. Use respondent
  IDs in analysis. Do not commit notes, transcripts, screenshots, or personal
  data to the repository.
- Do not collect special-category or unnecessary personal data. If it is
  volunteered, do not record it.
- Quote only with consent. Anonymize firm and client details unless the
  respondent explicitly agrees otherwise.
- Do not claim legal compliance, certification, data residency, DPA coverage, or
  security approval. Those decisions are open gates, not demo features.
- If a respondent asks for tax or legal advice, decline and redirect to their
  own adviser. The demo does not provide tax conclusions.

## 11. Pilot decision template

### 11.1 Two separate decisions

1. **User-facing demo ready?** Technical and facilitation readiness. This can be
   `YES` while real-data production remains blocked.
2. **Paid pilot with real files approved?** Requires interview evidence **and**
   every technical/security/source gate below. This is `NO` today regardless of
   demo enthusiasm.

### 11.2 Proposed evidence rule (PO approves before use)

This is a decision aid, not a finding and not a market claim. The PO may change
the thresholds before interviews and must record the change.

| Outcome | Proposed rule |
|---|---|
| `GO` | 2-3 consented interviews completed; at least 2/3 explain C1, C2, and C4 at score 2-3; at least 2/3 name the problem in their top three and say the workflow would materially reduce review effort; at least one economic buyer is willing to pilot within a stated window and can provide authorized samples; no unresolved severity-1 trust failure; all real-data gates approved. |
| `CONDITIONAL` | Clear interest, but samples, security/release, onboarding, or a fixable comprehension gap blocks a pilot. Record conditions, owners, and a re-review trigger. |
| `FIX DEMO` | Fewer than 2/3 understand the conclusion or coverage gap, or the value proposition is unclear, but respondents are willing to see a revised demo. |
| `NO-GO` | 2/3 see no material workflow value, or all qualified respondents refuse authorized data sharing, or any critical trust failure cannot be fixed. |

Do not count a polite "interesting" as a buying signal. Distinguish a user from
the person who can approve a pilot.

### 11.3 Minimum verified format samples before real files

No parser-accuracy or Jordanian-format claim is allowed before these exist and
are approved. Current blocker register entries B-01, B-02, and B-03 are OPEN.

- At least **2 authorized Sales Register exports** covering the layouts the
  pilot expects, with provenance, version markers, and mapping notes.
- At least **1 authorized JoFotara Excel export** per supported profile/version,
  with the profile owner and known limitations. Do not infer a schema from the
  synthetic scenario.
- At least **1 authorized General Ledger export** covering the pilot accounting
  system, account scope, measure, sign convention, tolerance, and currency/FX
  treatment.
- Written authorization to use each sample for engineering and pilot validation,
  plus a redaction/handling plan. Samples stay out of the public repository
  unless the repository classification decision allows them (B-09).
- Mapping approval for each source/client combination, with the approver and
  version recorded. Release does not imply mapping approval, and mapping
  approval does not imply production readiness.

If the pilot needs layouts beyond this minimum, add samples before claiming
support. Unsupported layouts must fail closed with actionable guidance.

### 11.4 Required approvals and implementations before real data

Record each as `APPROVED`, `REJECTED`, `OPEN`, or `NOT_APPLICABLE`, with an
evidence link and owner.

| Gate | Current state | Required evidence |
|---|---|---|
| Private object storage, encryption/KMS, versioning, region, IAM | OPEN / not implemented | Approved DEC-S1 decision and working storage adapter |
| Malware scanner and trusted verdict ingestion | OPEN / not implemented | Approved DEC-S2 decision and fail-closed verdict evidence |
| Retention, deletion, backup, restore | OPEN | Approved decision, tested lifecycle, restore drill |
| Release authority, separation of duties, TTL, revocation | OPEN | Approved DEC-S3/DEC-06-style policy and append-only evidence |
| JoFotara profile | OPEN | Authorized sample, approved profile/version, mapping |
| GL comparison policy | OPEN | Approved account scope, measure, sign, tolerance, FX treatment |
| Sales Register mappings | OPEN | Per-layout profiles and approved mappings |
| Production onboarding (email delivery, reset, MFA) | OPEN / dev-token only | Implemented and tested, or a written pilot exception |
| Worker durability / production processing | OPEN | Approved durability gate and operational runbook |
| Legal/DPA, data residency, subprocessors | OPEN | PO/legal approval; no claim before approval |
| UAT and support/incident plan | NOT STARTED | Signed UAT evidence, named support owner, incident path |

A demo-ready checkbox never substitutes for any row above.

### 11.5 Decision record

| Field | Entry |
|---|---|
| Decision owner | PO |
| Decision date | |
| Baseline SHA | `3cd5205aa4696925928f365a9576edecc3a4375a` |
| Respondents reviewed | `R1`, `R2`, `R3` |
| Evidence files (private) | |
| Demo ready? | `YES` / `NO` + evidence |
| Real-data pilot decision | `GO` / `CONDITIONAL` / `FIX DEMO` / `NO-GO` |
| Conditions / missing gates | |
| Top three changes | Link to section 11.6 |
| Re-review trigger | For example: samples obtained; security decision approved; demo revised |
| Next owner and action | |

Do not fill this table until the interviews actually happen.

### 11.6 Top three prioritized changes

Rank only after interviews. "Buyer impact" means the respondent's stated
workflow value, not the facilitator's preference.

| Rank | Change requested | Respondents | Buyer impact (critical/high/medium/low) | Frequency | Risk if unchanged | Effort (S/M/L) | Dependencies | Decision |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

Rank by buyer impact first and use implementation effort as the tie-breaker.
Use the engineering owner's S/M/L estimate; the facilitator must not estimate
cost. Known demo limitations are inputs to the discussion, not pre-ranked buyer
priorities. Do not present an engineering preference as a customer finding.

## 12. Known limitations to state plainly

- Synthetic `synthetic-sales-gl-v1` data only; no customer file intake, storage,
  scanning, mapping approval, or real reconciliation.
- One deterministic rule set for Sales Register to GL (REC-005). This is not a
  full tax engine and does not verify JoFotara filings.
- No official JoFotara import, government API, portal credentials, or filing.
- No approval workflow, e-signature, review-decision persistence, or filing
  export.
- PDF and XLSX are English-only. Engine finding text stays English inside the
  Arabic UI and is marked as such.
- No email delivery, password reset, or MFA in this build; onboarding is a dev
  flow and B-11 remains open.
- The queue is development-only; production processing is blocked.
- The demo is verified on a current desktop browser and a 390 px viewport, not
  on every device or browser.
- Nothing here is tax, legal, or accounting advice.

## 13. Validation evidence

### 13.1 Baseline CI

- Merge commit: `3cd5205aa4696925928f365a9576edecc3a4375a`.
- Post-merge run: https://github.com/tamerabuhalaweh/TaxPilot/actions/runs/39557995322
- Result: 7/7 jobs success (`backend`, `browser`, `browser-demo`, `docs`,
  `frontend`, `integration`, `security`) at the exact SHA.

### 13.2 Local browser validation on the exact baseline

| Check | Command | Result |
|---|---|---|
| Connected suite (auth, reviews, proxy, REC-UI-01, REC-UI-02) | `npx playwright test --grep-invert "demo"` | 16/16 passed |
| Demo build smoke (no backend) | `E2E_BASE_URL=http://127.0.0.1:3001 npx playwright test e2e/demo.spec.ts` | 12/12 passed |
| Export bytes | Playwright checks PDF starts `%PDF-` and XLSX opens as a ZIP | passed |
| Run binding | Playwright checks exports reject a stale displayed run | passed |
| Desktop and 390 px | REC-UI-02 responsive assertion; no horizontal overflow | passed |
| EN/AR | RTL chrome, translated conclusion/coverage, English engine text labelled | passed |

Local validation note: the first cold-start connected run had three 5-second
navigation timeouts immediately after registration. The API had already returned
201/200 and the page navigated after the assertion timeout. An isolated rerun of
9/9 and a full rerun of 16/16 passed, and the baseline CI is green. No
application defect was reproduced; treat this as a cold-start test-timing
observation, not as evidence that the demo is broken. If it recurs during a
session, wait for the redirect rather than re-submitting the form.

### 13.3 What the evidence does not prove

- It does not prove that the synthetic rules are correct for a real client or a
  real JoFotara export.
- It does not prove storage, scanning, release, residency, or legal readiness.
- It does not prove buyer demand, willingness to pay, or time savings.
- It does not prove that any interview occurred.

## 14. What the PO must arrange next

1. Recruit 2-3 Jordanian accountants, including at least one person who can
   influence a pilot decision. Do not promise a price or a date.
2. Send a short consent and scope note before the session: synthetic demo, no
   real files, voluntary, quote permission, and privacy handling.
3. Run each session with this kit; capture behavior and verbatim answers under a
   respondent ID.
4. Ask for authorized representative format samples only after the session and
   only through the approved path. Do not accept files in chat or email as part
   of the demo.
5. Complete the decision record and the top-three change table.
6. Bring genuine findings back for prioritization. Do not ask the developer to
   invent customer quotes, market size, legal approvals, prices, or dates.

## 15. Related blockers

- B-01/B-02/B-03: no authorized representative JoFotara, Sales Register, or GL
  samples. Real import support and parser-accuracy claims are blocked.
- B-04: tax-domain expert and rule approval.
- B-05/B-06: hosting/residency and AI-provider decisions.
- B-07: pilot firms (open).
- B-08: tax-return formats.
- B-09: repository classification for samples and docs.
- B-11: email delivery, reset, and MFA.
- Production storage, scanner, release authority, retention, and legal/DPA
  approvals remain open as described in the SEC-SOURCE documents.

This kit is documentation and demo validation only. It does not approve real
financial data processing, production deployment, or any merge.
