SEHATAMAN — صحت امان
Apni sehat. Apna ikhtiyar.
Tehreem PCC 2026 | Step 5 engineering validation complete | Entirely synthetic local MVP

OPEN THE APP
http://127.0.0.1:8787/

This is a run-locally address for the computer running the server, not a remote demo.
The prepared server runs only on its laptop. Nothing is deployed online.
If the server is stopped, double-click Run-SehatAman.cmd. Keep its terminal open.
Stop a foreground server with Ctrl+C. A background server started by this chat can
be stopped with Stop-SehatAman.ps1; it verifies the recorded process belongs to this
project before stopping it. Stopping the server does not erase data.

SIGN IN
Double-click Show-DemoAccounts.cmd. It displays generated synthetic usernames,
passwords and current test second-factor codes. Codes rotate every 30 seconds;
each accepted code is usable only once per account. Run it again for a fresh code.
Passwords and factor seeds are not embedded in public frontend files.
The local helper displays the test code on the same computer; it is not an
independent-device authentication factor or an SMS delivery service.

Useful synthetic accounts:
  p01 ... p05       Patients
  d01 ... d03       Physicians
  l01-s01          Lab L01 submitter
  l01-a02          Lab L01 distinct approver
  l02-s01          Lab L02 submitter
  l02-a02          Lab L02 distinct approver
  h01-m01          Hospital profile/affiliation manager

LABORATORY INPUTS
The restricted local command "python manage.py inputs" displays deliberately
invented CNIC and birth-date fixtures for the laboratory identity-entry fields.
Use the bundled Python below if "python" is not configured on this laptop.
Routine screens and responses mask CNIC. Do not use any real identifier or record.

DEMONSTRATION ROUTE
1. Sign in as p01. Review the supplied diagnostic history and provenance. Patient
   p02 has a separate history; p03-p05 begin without accepted reports.
2. Open Find physician. D01 has both simulated checks valid. D02 has registration
   only; D03 has affiliation only. Only D01 is initially bookable.
3. Book D01. Sign out and use d01: the appointment alone exposes no reports.
4. As p01, select an appointment, exact report versions and a duration. Confirm
   sharing separately. As d01, open only the selected versions and protected files.
5. As l01-s01, choose an assigned order. Enter a mismatched synthetic CNIC or
   specimen: the submission is held and does not enter an accepted patient history.
6. Submit a concordant package. Sign in as l01-a02 to approve it. Submitters cannot
   approve their own work; invalid identity/integrity findings cannot be overridden.
7. As l01-s01, open a current source report and propose an amendment with a reason.
   Approve with l01-a02. The old version remains historical; the new version needs
   separate patient permission. Replays and competing successors cannot overwrite it.
8. As h01-m01, revise a hospital profile or revoke/renew its affiliation evidence.
   Professional registration stays independent and read-only in this workspace.
9. Withdraw a permission, cancel an appointment, or use the local registration
   fixture command below. The next affected physician metadata/file request is
   denied, even in an existing session. Revisit My sharing for who/what/when events.
10. Stop and restart the server. Reports, corrections, permissions, credential
    states and audit evidence persist.

To demonstrate withdrawal while keeping the physician's existing session, use
separate browser profiles for patient and physician (for example, an ordinary and
a private browser window). Two tabs in the same profile share their login cookie.
Keep appointment, verification states and synthetic time unchanged during that
check. Withdrawal blocks newly ordered affected requests, not previously delivered
copies. Automated same-session ordering tests are retained with the evidence.

The live data may include synthetic actions performed during browser checks.
Those actions and their audit trail are retained. For a fresh independent demo,
use a NEW empty home, for example "python manage.py --home .local-fresh serve
--port 8788". Existing data is never silently reset. Do not delete keys/checkpoints
to try to repair an existing database.

LOCAL FIXTURE CONTROLS
These are privileged terminal-only synthetic controls, not browser administrator
routes or live verification. They cannot be used by hospital staff to self-verify
professional registration.
  python manage.py verify
  python manage.py registration D01 stale
  python manage.py registration D01 valid
  python manage.py identity P01 pending
  python manage.py identity P01 valid
  python manage.py issuer L01 revoked
  python manage.py clock --advance-minutes 120
  python manage.py clock --set 2026-10-21T10:00:00+05:00
  python manage.py revoke-sessions D01

The visible fixed synthetic clock controls report/consent/evidence intervals.
Sessions, inactivity limits and second-factor codes use actual server time.
Clinical intervals have inclusive starts and exclusive ends. Demo grants are
bounded to 24 hours; hospital evidence intervals to 90 days. These are engineering
bounds for this demonstration, not validated production freshness policies.

CYBERSECURITY IMPLEMENTED
- Argon2id password hashing; time-based separate test factor with replay rejection;
  server-side sessions, logout invalidation, eight-hour absolute expiry and
  twenty-minute inactivity expiry; throttled failed sign-ins.
- Server-assigned roles; object and function checks; patient ownership; source-lab
  scope; zero hospital clinical access; exact-version patient grants.
- Every physician release checks current appointment, time, independent professional
  registration, separate hospital affiliation, patient identity/linkage, report
  integrity and required durable audit availability. Booking/profile listing grants
  no clinical access. Metadata and protected downloads share the gate.
- CNIC is normalized for linkage, uses a secret-keyed lookup and is stored inside
  authenticated encrypted state. It is never a login or recovery secret.
- Local synthetic per-lab Ed25519 issuer signatures bind metadata and the actual
  report-content digest. Distinct source approval and transactional predecessor
  checks preserve originals and reject replay/conflicting changes.
- Encrypted SQLite state and audit records; serialized cross-process transactions;
  chained authenticated events plus a separately protected latest-state checkpoint.
  Required audit failures prevent release. A post-commit checkpoint failure retains
  the committed state but requires recovery; the app never silently re-anchors it.
- Same-origin/CSRF checks, HttpOnly/SameSite cookies, host allowlisting, no-store
  responses, CSP, no active report HTML, bounded request bodies, worker and request
  limits, and an exact static-file allowlist. Private files are not web-served.
- Patient access summaries show exact record/version, actor category and recorded
  time. Own browsing is retained in the protected audit; the readable summary shows
  source/sharing and other-party access decisions. Server release preparation is
  not proof of human reading. Previously delivered copies cannot be recalled.

STORAGE AND ASSUMPTIONS
  .local/data/sehataman.sqlite3       Encrypted persisted clinical state and audit
  .local/protected/                  Keys, checkpoint and local demo credentials
  .local/issuer-secrets/             Synthetic issuer signing keys
These paths are outside the served frontend. Keep keys/checkpoints and encrypted
data together when making an owner-controlled backup. Loss of protected evidence
causes a recovery hold. The local OS and protected keys are trusted; this does not
protect against an attacker controlling both the runtime/OS and those keys.
The loopback HTTP server is a local demonstration server. It is not a production
TLS deployment or clinical service. There are no live PMDC, NADRA, laboratory,
hospital, email, SMS, payment or external analytics calls. All application entities
are invented; the applicant team information is separately user supplied.

IMPLEMENTATION CHECKS AND APPROVAL STATUS
This is one integrated app with four entity workspaces, five distinct access roles
and shared persisted state; the lab submitter and approver are separate roles.
All 27 implementation checks pass. The final running build was reloaded in
the browser after restart; persisted history and integrity checks pass. Desktop
and 320-pixel layouts were checked. See planning/step4_build_status.json for the
consolidated delivery record and approval gate.
See planning/step4_implementation_checks.json and planning/step4_browser_checks/.
The frozen 120-case manifest and its digest were created before app implementation.
Step 5 is authorized and its engineering evaluation is complete: 120/120 frozen
cases and 500/500 coordinated traces pass per arm. The constructed reference uses
equivalent safeguards on a shared stack; it is not an independent commercial product.
All 27 implementation regressions pass, as do 46 supplementary checks across both
arms. The measured MVP HTTP p95 is 668.130 ms over 1000 requests at concurrency 10,
with no request errors or denied payload leaks. Earlier failures are retained.
See docs/STEP5_VALIDATION_REPORT.txt for methods, denominators and limitations.
Independent/domain review and direct local stakeholder validation remain pending.
Prior web research is contextual evidence only. No security certification, clinical
validation or commercial superiority is claimed. The user has approved Step 5 and
authorized Step 6 reviewer handover preparation. See planning/step6_handover.json
for the current approval gate; earlier stage reports retain historical status.
Deployment remains deferred. The owner retains a separate private application
copy; it is not required to review this public, contact-redacted package.
The separately authorized intended public reviewer destination is
https://github.com/javed110/sehataman-pcc-2026-reviewer . Consult
planning/reviewer_publication.json for its current publication/verification status.
Public code/material delivery is not deployment of the app or submission to PCC.

REVIEWER MATERIALS
Start with docs/STEP6_REVIEWER_HANDOVER.txt for a fresh review using a separate
home and matching credentials. docs/CLAIM_EVIDENCE_CHECKLIST.txt maps form claims
to inspectable source/evaluation evidence and their limits.
docs/SECTION_BY_SECTION_REVIEW.txt guides the concept-note review in order.
Application submission
and deployment both require separate explicit user approval.
Open http://127.0.0.1:8787/reviewer for the guide and recordings after starting the app.
The demos/ folder contains four role videos and one complete walkthrough MP4.
These are edited actual browser screen captures, sampled during live interaction;
sign-in secrets and waiting intervals are omitted. Audio is not included.
These recordings precede the latest interface polish and may show older labels
and spacing. Their core workflow and authorization rules remain unchanged.
docs/SehatAman_PCC26_Concept_Note.docx is the editable filled application template.
Tehreem's, Haris's and Majid's emails and phones remain To be provided; Humaira's
contacts and corrected BS Molecular Biology and Genetics program are supplied.
Tehreem's exact official MS program title remains to be confirmed. The declaration is unsigned.
The private application Word copy retains the supplied contact information; the
separate public reviewer copy redacts personal contacts without changing confirmed
academic facts or the pending status of missing information. Private GitHub links
still require owner-approved access. Public materials do not provide a hosted app.

RUNTIME
On this laptop the launchers use:
C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
Python 3.12.14, cryptography 50.0.2, argon2-cffi 23.1.0, SQLite 3.53.1.
On another machine use Python 3.12+ and install requirements.txt in an isolated
environment, then run "python manage.py serve". No Node build or external CDN is
needed to run the app. The current local source and persisted demo are retained.

ENGINEERING REFERENCES
https://cryptography.io/en/50.0.0/fernet/
https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/
https://argon2-cffi.readthedocs.io/en/stable/howto.html
https://docs.python.org/3.12/library/http.server.html
https://www.rfc-editor.org/rfc/rfc6238
These guide implementation; they do not certify this application.

PUBLIC REVIEW COPY
Personal contacts are redacted in this copy. See docs/PUBLIC_REVIEW_COPY.txt.
