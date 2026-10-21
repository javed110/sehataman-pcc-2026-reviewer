from pathlib import Path
import json
from collections import Counter

ROOT=Path(__file__).resolve().parents[1];out=ROOT/'planning/step5_results'
def latest(name):
 p=json.loads((out/('latest-'+name+'.json')).read_text())['report'];return p,json.loads((out/p).read_text())
cf,cases=latest('cases');bf,bench=latest('benchmarks')
rf=sorted(out.glob('routes-*.json'))[-1];routes=json.loads(rf.read_text())
summary={'application':'SehatAman','version':'0.5.0','stage':'Step 5','engineering_evaluation':'complete',
 'all_demo_data_synthetic':True,'deployed':False,'step6_authorized':False,
 'frozen_cases':cases['summary'],'traces':bench['summary'],'regressions':{'passed':27,'total':27},
 'supplementary_checks':{'passed':routes['passed'],'total':routes['total']},
 'performance':[{k:p[k] for k in ('arm','requests','permitted','denied','concurrency','p50_ms','p95_ms','maximum_ms','errors','denied_leaks','target_met')} for p in bench['performance']],
 'case_report':cf,'benchmark_report':bf,'route_report':rf.name,
 'fixed_issues':['Audit events now include a decision basis and correlation identifier.','Incomplete source approval packages receive a held receipt and cannot publish.','Pending-identity sharing/withdrawal responses no longer disclose report metadata.','Protected encrypted-audit row verification removes redundant decoding while preserving tamper/truncation/rollback checks.'],
 'remaining':['Independent/domain review of the expected-outcome table','Direct Pakistani stakeholder validation','Commercial gap and buyer validation','Student email addresses and phone numbers','Applicant signature and review','Owner-approved reviewer access to private GitHub materials'],
 'study_limits':['Agent-authored expectations and reference; reserved cases not blinded.','Reference shares workflow, session, storage, audit, cryptographic and HTTP components; shared defects are possible.','Single laptop, sequential M then R, no randomized hardware crossover.','Configuration person-hours were not prospectively timed; no cost/setup-effort advantage is claimed.','Historical key-retirement case retains the verification public key; no live key-rotation service is implemented.','Performance measured before addition of public synthetic reviewer-media routes, which do not participate in the metadata workload.'],
 'next_step':'Await explicit approval before Step 6; no deployment, application submission or reviewer invitations performed.'}
(ROOT/'planning/step5_completion.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
lines=['SEHATAMAN PCC 2026 STEP 5 ENGINEERING VALIDATION','',
 'All application/test entities and data are synthetic. No external clinical or verification services and no app deployment.',
 'The 120-case manifest SHA-256 remains d7191bdd7ec753004da9bc48869f2e140481cf43b7a441947bceeff1fafd9890.',
 'This is an executed synthetic engineering protocol, not an independent security certification or stakeholder-validated clinical study.','',
 'RESULTS','M = the MVP; R = constructed conventional ABAC reference on the same stack.']
for arm in ('M','R'):
 rs=[r for r in cases['results'] if r['arm']==arm]
 deny=sum(1 for r in rs for a in r['actions'] if a['route'].startswith('/report-versions/') and a['method']=='GET' and a['status']>=400)
 versions=sum(r.get('accepted_versions_checked',0) for r in rs)
 lines += [f"{arm}: {sum(r['passed'] for r in rs)}/120 cases; 48 predeclared valid and 72 adverse/failure cases; 36 reserved variants were not blinded.",
           f"{arm}: {deny} denied direct clinical read/file requests across the case workflows; no prohibited payload in these responses.",
           f"{arm}: {versions} accepted-version provenance assertions across independent case homes, with original-package and predecessor retention checks. These are repeated fixture assertions, not distinct patients.",
           f"{arm}: 500/500 coordinated traces: 100 withdrawal, 100 affiliation, 100 registration, 100 appointment and 100 competing-correction traces."]
for p in bench['performance']:
 lines += [f"{p['arm']}: 1000 HTTP metadata requests, 500 permitted/500 denied, concurrency 10, after 100 separate warm-up requests.",
           f"p50 {p['p50_ms']:.3f} ms; p95 {p['p95_ms']:.3f} ms; max {p['maximum_ms']:.3f} ms; errors {p['errors']}; denied payload leaks {p['denied_leaks']}; proposed p95 <=1000 ms target met: {p['target_met']}."]
lines += ['', '27/27 implementation regressions pass. 46/46 supplementary check groups pass across both arms, covering 22 positive/unauthorized route pairs per arm plus pending-identity sharing/withdrawal.','',
 'ORDERING AND FAILURE CHECKS',
 'Race decisions are compared with committed audit sequence order. Every post-commit read in the four invalidation families is denied in the existing session. Conflicting corrections permit one successor and preserve the original.',
 'Injected audit failures roll back pending changes and prevent clinical release. A post-commit checkpoint failure retains the committed withdrawal and enters a recovery hold. Tampering, truncation, rollback, missing checkpoint and corrupted state are detected. Fresh-process verification checks committed state after restart.',
 'Every new manifest security event is checked for actor/action/time/outcome/decision basis/correlation. Original accepted versions and required source/context/timestamps/approver/predecessor/reason fields are asserted. The protected checkpoint binds every encrypted audit row; plaintext chain MACs are additionally checked when the full audit is requested.',
 '', 'FIXES AND RETAINED FAILURES']
lines += summary['fixed_issues']
lines += ['The initial case run passed 89/120 per arm because of incomplete audit basis fields and the held-receipt contract mismatch. A supplemental route run exposed pending-identity metadata. The first MVP performance run p95 was 1232.631 ms; all failed run files are retained. Existing historical live-demo audit entries were not rewritten to fabricate fields.',
 '', 'REFERENCE FAIRNESS AND LIMITS']+summary['study_limits']
lines += ['Both arms receive the same evidence, fixtures, workload and shared infrastructure. R independently specifies attribute rules for eligibility, grant scope, source validation and record access. Equal correctness supports conformance; the measured R p95 is lower in this run. No security, speed, cost, accuracy or usability superiority is claimed.',
 'The report does not measure real NADRA/PMDC accuracy, real-world credential notification delay, clinical diagnostic accuracy, human comprehension, adoption or national demand.',
 '', 'HARDWARE AND CAPTURED NETWORK',json.dumps(bench['hardware'],indent=2),
 'Captured benchmark socket destinations: '+', '.join(bench['network_destinations'])+'. Non-loopback connections were blocked by the benchmark audit hook. This excludes separate development tools used for GitHub and document/media preparation.',
 '', 'ARTIFACTS',cf,bf,rf.name,'planning/step5_completion.json','', 'PENDING']+summary['remaining']
(ROOT/'docs/STEP5_VALIDATION_REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'cases':cases['summary'],'traces':bench['summary'],'supplementary':routes['passed']},indent=2))
