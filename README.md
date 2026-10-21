# SehatAman PCC 2026 public reviewer copy

A single persisted local MVP for patient-controlled molecular diagnostic report sharing. All demonstration people, organizations, identifiers, reports and verification outcomes are invented.

## Start the app

Use Python 3.12 or later. Install `requirements.txt` in a virtual environment, then run `python manage.py serve --port 8787`. On the prepared Windows laptop, double-click `Run-SehatAman.cmd`. Open [the local application](http://127.0.0.1:8787/). It binds only to loopback.

Run `python manage.py accounts` or `Show-DemoAccounts.cmd` locally for newly generated demo passwords and current TOTP codes. Each account must authenticate. No credential, private key, session or persisted database is distributed in this repository or its ZIP. First startup creates a fresh synthetic store.

## Review the deliverables

- [Editable Microsoft Word concept note](docs/SehatAman_PCC26_Concept_Note.docx)
- [Complete recorded walkthrough](demos/sehataman-complete-walkthrough.mp4)
- [Patient sharing](demos/patient-sharing.mp4), [physician access](demos/physician-access.mp4), [laboratory provenance](demos/laboratory-provenance.mp4), [hospital affiliation](demos/hospital-affiliation.mp4)
- [Engineering validation report](docs/STEP5_VALIDATION_REPORT.txt)
- [Step 6 reviewer handover and fresh-demo instructions](docs/STEP6_REVIEWER_HANDOVER.txt)
- [Claim-to-evidence checklist](docs/CLAIM_EVIDENCE_CHECKLIST.txt)
- [Section-by-section concept-note review](docs/SECTION_BY_SECTION_REVIEW.txt)
- [Full operating and demonstration guide](README.txt)
- [Frozen cases and research evidence](planning/)

The local [reviewer guide](http://127.0.0.1:8787/reviewer) plays these videos after the app starts. The MP4s are actual browser screen captures sampled during live interactions and edited into role walkthroughs. They contain no generated UI footage, authentication secrets or audio. The synthetic actions shown in recordings are reproducible from the guide; fresh startup intentionally creates new credentials and a clean initial state.

The recordings precede the latest interface polish and may show older labels and spacing. The current app has clearer sign-in guidance, consistent access-denied screens and corrected submission-status labels; the recorded workflow and access rules are unchanged.

The intended public reviewer destination is [sehataman-pcc-2026-reviewer](https://github.com/javed110/sehataman-pcc-2026-reviewer). See `planning/reviewer_publication.json` for its current publication and verification status. This is delivery of code, documents and recordings; it does not host a running app. The owner retains a separate private application copy; it is not required to review this contact-redacted package.

The private application copy of the Word note retains the supplied contact information. The separate public reviewer copy redacts personal contacts, including the supplied contact, and preserves the names, roles and academic details. Redaction does not turn a supplied fact into a missing fact. Unresolved application details remain pending in both copies.

## Security and evidence

Patient permission binds the physician, appointment, hospital context, purpose, exact immutable versions and interval. Every clinical metadata/file request rechecks current state. Professional registration and hospital affiliation are independent simulated attestations; neither a profile nor a booking confers record access. Labs use signed source packages and a distinct approver. Corrections retain their predecessors, originals and reasons. CNIC supports synthetic linkage, never authentication or recovery.

Argon2id passwords, local TOTP, server sessions, CSRF/origin checks, object authorization, Ed25519 signatures, encrypted SQLite state, durable audit and a protected integrity checkpoint execute in the MVP. Every encrypted audit row remains bound to the protected checkpoint before release; plaintext audit decoding is deferred until needed.

The local credential/code helper is a test convenience, not an independent-device authentication factor. All identity, professional-registration and affiliation outcomes are synthetic.

Step 5 results: **120/120 frozen cases and 500/500 coordinated traces per arm**, **27 passing regressions**, and **46 supplementary checks across both arms**. The MVP's measured p95 metadata response was **668.130 ms**, over 1,000 mixed loopback HTTP requests at concurrency 10, with zero errors. The constructed conventional reference also passes; it shares infrastructure and workflow components. No commercial superiority is established. Detailed rows, earlier failures and limits are retained in `planning/step5_results`.

## Run the checks

Set `PYTHONPATH` to the project root and its `tests` directory. Run `python -m unittest discover -s tests -p test_mvp.py -v`, `python -m unittest discover -s tests -p test_release.py -v`, `python tests/step5_validate.py`, `python tests/step5_route_checks.py`, and `python tests/step5_benchmarks.py`. Each creates isolated synthetic test homes under `.local`, never resets the working demo, and uses loopback HTTP only.

The user approved Step 5 and authorized Step 6 reviewer handover preparation. See `planning/step6_handover.json` for the current gate; earlier planning snapshots retain their historical approval state. Missing application details remain pending. Deployment and application submission require separate explicit approval.

## Application accuracy and boundaries

The confirmed student team is Tehreem Hamid, Muhammad Haris, Muhammad Majid and Humaira Zubair, with mentors Dr. Javed Ashraf and Dr. Hira Anwar. The Word form contains the user-confirmed roles and academic details. Humaira's contacts and BS Molecular Biology and Genetics program are supplied. Tehreem's, Haris's and Majid's email addresses and phone numbers, and Tehreem's exact official MS program title, remain to be supplied; the declaration is unsigned. Business, budget and IP status remain pending. No open-source licence, patent, certification or institutional endorsement is asserted.

Direct stakeholder validation, independent/domain review and commercial market-gap confirmation remain pending. The predeclared reserved cases were not blinded. This is a local synthetic demonstrator with a trusted OS/key assumption, not a clinical service or production TLS deployment. No live NADRA/PMDC, laboratory, hospital, messaging, AI or external runtime service is used. **Do not deploy without separate approval.**

Historical Step 1–4 planning and design evidence remains in `planning`; the executable application is `sehataman`. The reference is an evaluation fixture, not a second product. Private application links require approved GitHub access. The intended public reviewer package provides a contact-redacted delivery route, subject to the publication status above. Localhost links are run-locally instructions for the computer running the server, not an externally accessible demonstration.

This package is the public, contact-redacted reviewer copy. See [public-copy details](docs/PUBLIC_REVIEW_COPY.txt) and `planning/reviewer_publication.json` for publication and verification status. Public material delivery does not deploy the app.
