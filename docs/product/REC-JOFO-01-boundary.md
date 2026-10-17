# REC-JOFO-01 boundary (verified JoFotara Excel profile contracts — default-deny)

Scope: `apps/api/app/jofotara/profile.py`, `apps/api/app/jofotara/__init__.py`,
`apps/api/tests/test_jofotara_profile_contracts.py`, and this document. No
migration, no database, no HTTP, no file I/O, and no reconciliation wiring.

Authoritative spec: GitHub issue #65 (epic EP-15; SRS FR-JOF-001..006, EP-05/06).

## Discovery outcome: no grounded layout exists

JoFotara is file-based only; the SRS forbids a government-API integration and
forbids guessing any layout (FR-JOF-001/002). Discovery found:

- **Blocker B-01 OPEN** — no authorized JoFotara sample exports in the repo (or
  elsewhere); **DEC-10** (JoFotara profiles/versions) OPEN; **FR-JOF-001/002**
  NOT_STARTED and BLOCKED on authorized samples (DEC-10).
- No `.xls`/`.xlsx` sample files in the repository; no documented official
  worksheet/column specification with provenance was available for review.

Consequently this slice implements **no layout**: it delivers a pure, strict,
**default-deny** profile foundation and documents the missing samples/decisions.
Nothing here is (or claims to be) an official JoFotara format.

## What landed

### Versioned profile manifests (`JoFotaraProfile`)

An immutable manifest: `profile_id` + `profile_version`, declared
`worksheet_names`, recorded `header_fingerprint`, a canonical→source
`column_map` (canonical fields restricted to `KNOWN_JOFOTARA_FIELDS`),
`required_fields`, explicit `MoneySemantics` (decimal/grouping separators,
currency policy), an explicit `date_format`, `status` (`APPROVED`/`DRAFT`),
`approved_by`/`approved_at`, and declared `ProfileProvenance` (issuing source,
authority type `OFFICIAL`/`AUTHORIZED_SAMPLE`, extraction date, redistribution
permission, reference URL, notes). An `APPROVED` profile **cannot be constructed
without provenance and an approver**; a `DRAFT` profile is inert.

`JoFotaraProfileRegistry` is an immutable, de-duplicated set.
`DEFAULT_JOFOTARA_REGISTRY` is **empty** — the shipped state has no approved
profile, so every real layout is refused.

**Registry/approval trust is external, never self-granted (F2).** A
caller-constructed registry and the approval metadata on any profile
(`status = APPROVED`, `approved_by`, `ProfileProvenance`) are *declared claims*,
not proof, and must not be treated as authorization for production JoFotara
imports. Real approval requires a **trusted, independently verified profile
registry** populated only through the profile approval gate (accounting/tax
review + signed runtime profile). This pure module cannot confer trust, has no
global/ambient registry, and never consults caller-supplied metadata as
verified evidence.

### Strict recognition (`recognize_jofotara_profile`)

Fail-closed, first-failure-wins reasons:

| Order | Condition | Reason |
|---|---|---|
| 1 | No header row | `EMPTY_HEADERS` |
| 2 | Duplicate columns | `DUPLICATE_HEADER` |
| 3 | Registry has no approved profile | `NO_APPROVED_PROFILE` |
| 4 | No approved profile claims the worksheet | `UNSUPPORTED_WORKSHEET` |
| 5 | Only a draft profile matches the exact layout | `PROFILE_NOT_APPROVED` |
| 6 | Approved profile(s) claim it but headers differ | `HEADER_DRIFT` |
| 7 | More than one approved profile matches | `AMBIGUOUS_PROFILE_MATCH` |
| 8 | Otherwise | `RECOGNIZED` |

Recognition additionally runs full column validation before returning
`RECOGNIZED`, so a matched profile can never bypass strict column checks.

### Strict column validation (`validate_jofotara_profile`)

Rejects empty/duplicate headers, header drift from the profile fingerprint,
unknown canonical fields, declared columns absent from the worksheet, required
fields that do not resolve, and an approved profile lacking provenance.

### Exact value handling

- `parse_money` returns an exact `Decimal` under the profile's declared
  convention; it rejects non-text input (no float/int path), blanks
  (`MISSING_VALUE`, never zero), formula cells (`FORMULA_CELL`), external
  workbook references (`EXTERNAL_REFERENCE`), malformed text
  (`MALFORMED_NUMBER`), and non-finite values. Separator **structure is
  validated before any separator is removed**: the decimal separator may appear
  at most once with trailing fraction digits, and a declared grouping separator
  must delimit groups of exactly three digits (leading group one to three), so
  values like `1,23`, `12,34,567`, `1,2345.6`, `1,234,56`, undeclared separators,
  and internal whitespace are rejected — never silently corrected into a
  different number.
- `normalize_identifier` returns a **verbatim string** (leading zeros preserved;
  never coerced to a number); blanks and formula/external references are refused.
- `normalize_currency` returns an explicit upper-case 3-letter code; blank is
  `MISSING_CURRENCY` (currency is **never assumed JOD**) and unsupported codes are
  `UNKNOWN_CURRENCY`.

### Invoice semantics (defined only where verified — nowhere yet)

`JoFotaraInvoice` fixes the *shape* the future approved profile will populate:
issuer, invoice number, issue date, currency, exact net/tax/gross `Decimal`s
(missing stays `None`, never zero), credit-note flag plus explicit
`reference_number` (a linked record, never netted), and
`JoFotaraRowProvenance` anchors (dataset, worksheet, and a **genuine positive
integer** row number — booleans, floats, strings, zero, and negatives are
rejected, so evidence always points at a real data row). `build_jofotara_invoice`
**requires** a successful recognition from an approved profile (defense in
depth); with the empty registry it always refuses (`NOT_RECOGNIZED`). No
net/tax/gross/credit-note meaning is asserted anywhere until an approved profile
declares it.

## Integration deliberately deferred

- The normalization engine still refuses `jofotara_export` with
  `UNSUPPORTED_PROFILE` (no behavior change).
- There is **no** JoFotara→`CanonicalInvoice` adapter; the existing sales-only
  adapter is unchanged. Wiring a JoFotara profile into normalization or REC-001..005
  is a later slice and requires a genuinely approved profile plus the
  reconciliation integration gate.

## Required before enabling feature import (explicit blockers)

1. **Authorized, representative JoFotara sample exports** with recorded
   provenance and redistribution permission (B-01), and PO/expert confirmation
   of the layout (**DEC-10**).
2. **Repository classification** so verified fixtures may enter the repo
   (B-09/DEC-13); sanctioned fixtures must be clearly separated from synthetic
   negative tests, with no real customer data in the repo or CI.
3. A **profile approval gate** (accounting/tax review + signed runtime profile),
   matching the SRS publication gate — no AI suggestion may confirm a profile.
4. Resolution of the scanner/object-store decisions (DEC-S1/S2/02/03/R1) before
   any real document read or production processing.

## Gates kept closed

No scanner activation, no real document read, no source release, no mapping
approval bypass, no production financial processing, and no reconciliation
execution. All source-release and execution gates remain closed.
