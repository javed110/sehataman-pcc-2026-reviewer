"""Fill only answer slots in the retained PCC template; preserve opaque parts."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
import sys
from zipfile import ZipFile
from lxml import etree as E

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(r'D:\PCC 2026 dox\Tehreem_Haris_Majid_Humaira_PCC26_Concept_Note_Template.docx')
if not SOURCE.exists():SOURCE=ROOT/'docs'/'PCC26_Concept_Note_Template.docx'
DEST=ROOT/'docs'/'SehatAman_PCC26_Concept_Note.docx'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+NS['w']+'}'
repo='https://github.com/javed110/sehataman-pcc-2026-reviewer'
bench=None
latest=ROOT/'planning/step5_results/latest-benchmarks.json'
if latest.exists():
    bench=json.loads((latest.parent/json.loads(latest.read_text())['report']).read_text())
case=json.loads((ROOT/'planning/step5_results/latest-cases.json').read_text())
passed=case['summary']['M']['passed']
performance='Performance validation is in progress; no final latency claim.'
if bench:
    p=next(x for x in bench['performance'] if x['arm']=='M')
    performance=f"Retained laptop HTTP p95 {p['p95_ms']:.1f} ms at concurrency 10 over 1,000 mixed requests; {p['errors']} errors. "
    if not p['target_met']:performance+='The proposed one-second p95 target has not yet been met.'
summary=f"{passed}/120 frozen scenarios pass in both MVP and constructed reference. "
if bench:summary+='500/500 coordinated traces pass per arm. '+performance
else:summary+='Concurrency/performance evaluation is in progress.'

answers={
1:[
 'SehatAman Patient Controlled Molecular Report Sharing',
 '[X] Student Team    [  ] Researcher / Academic    [  ] Startup    [  ] Industry Professional',
 '[  ] AI + Cybersecurity          [  ] OT / ICS / Critical Infrastructure\n[  ] Emerging AI Threats       [X] Emerging Tech (Cloud/IoT/Web3/Zero Trust)\n[X] Cyber Defense & Resilience',
 '[  ] Idea / Concept              [  ] Proof of Concept / Prototype\n[X] Minimum Viable Product (MVP)  [  ] Commercialized Solution',
 'A diagnostic report must reach the correct patient and remain accessible only under current permission and credentials. An old physician session, a mistaken CNIC/specimen link or an overwritten correction can defeat that protection. SehatAman tests these connected failure points in a Pakistan-informed workflow joining patients, molecular laboratories, physicians and hospitals.',
 'SehatAman is a working persisted local MVP enforcing exact-version patient permission and separate simulated professional-registration and hospital-affiliation checks. Signed laboratory packages, distinct approval and linked corrections preserve source provenance and original versions. In synthetic engineering evaluation it passed 120 frozen scenarios and 500 coordinated traces per arm with no unauthorized release in the tested deny cases; its local metadata-response p95 was 668 ms at concurrency 10.'
],
2:['SehatAman Team','Student affiliations: National University of Sciences and Technology (NUST), Atta-ur-Rahman School of Applied Biosciences (ASAB) and School of Electrical Engineering and Computer Science (SEECS); National University of Medical Sciences (NUMS), Faculty of Multidisciplinary Sciences.\nSupervisors / mentors: Dr. Javed Ashraf, Professor of Public Health, NUMS; Dr. Hira Anwar, Assistant Professor, Department of Computer Sciences, SEECS, NUST.'],
5:[
 'Unauthorized release after consent withdrawal, credential invalidation or appointment cancellation; mismatched CNIC/order/specimen linkage; tampered or conflicting report revisions.',
 'Adult patients, molecular diagnostics laboratories, physicians and hospital profile/affiliation offices. Every demonstration identity and organization is invented.',
 'A disclosure or incorrectly linked version could compromise confidentiality and clinical traceability. The prototype measures engineering enforcement only; it does not estimate Pakistani attack incidence, financial loss or clinical benefit.',
 'Pakistani provider portals and medical-record workflows already exist, and PMDC provides professional verification. Hospital affiliation must be evidenced separately. The narrower research question is reproducible enforcement across consent, credential and correction transitions; commercial absence and local adoption remain unconfirmed. See the Pakistan evidence register in the repository.'
],
6:[
 'One app serves four entity types, with separate lab submitter and approver roles. Labs validate synthetic CNIC plus demographic/order/specimen context and signed packages; patients share exact accepted versions for an appointment; physicians pass current-state checks on every release; hospitals maintain profiles and affiliation without clinical access.',
 '[  ] Defensive AI (AI used to detect/mitigate threats)\n[  ] Adversarial Security (Securing AI/LLM models from attack)\n[X] Non-AI Emerging Tech (Blockchain, Zero Trust, Cryptography, etc.)',
 'The candidate contribution is a Pakistan-informed conformance profile and predeclared state-transition benchmark joining separate credentials, version-bound permission and signed correction provenance. Established cryptography and access-control methods are used; neither a new cryptographic primitive nor first-in-Pakistan status is claimed.',
 'N/A. No AI model, clinical prediction, automated diagnosis or training dataset is used. Threat tests instead address broken object access, stale authorization, source tampering, replay, concurrent corrections and audit/storage failure.',
 'Demonstrated strength: a working four-entity workflow with reproducible transition, provenance and failure evidence rather than a concept-only proposal. '+summary+' The equivalently configured constructed reference also passes; commercial cost, usability and superiority remain unvalidated.'
],
7:[
 'Browser role workspace -> authenticated loopback HTTP API -> current-state policy and source validation -> encrypted SQLite state and audit -> protected checkpoint. Report corrections append linked versions. Each physician metadata/file request rechecks explicit grant, appointment, time, identity and separate registration/affiliation evidence; audit/integrity failures hold release.',
 'Invented adult patients P01-P05, physicians D01-D03, labs L01-L02 and hospital H01; synthetic staff, CNICs, orders, specimens, reports, sessions and verification outcomes. Frozen 120-case manifest, 500 coordinated traces per arm and 1,000 mixed HTTP requests per arm. No live NADRA/PMDC, patient, lab or hospital data; no external runtime integration.',
 'Python 3.12; loopback HTTP server; SQLite; cryptography and argon2-cffi. Argon2id passwords, replay-resistant local TOTP, server sessions, CSRF/origin checks, Ed25519 signatures, authenticated encryption and protected audit/checkpoints. The demo-code helper is not an independent-device factor. Local HTTP is not production TLS.',
 '[  ] Concept stage    [  ] Algorithmic PoC    [X] Functional Lab Prototype    [  ] Live MVP\nFunctional persisted local MVP; no public deployment. '+summary+' Independent/domain review and direct stakeholder validation remain pending.'
],
8:[
 'Integration and conformance evaluation. Testable claim: under the specified synthetic threats and trusted-host/key assumptions, current-state checks prevent newly ordered unauthorized release and preserve accepted correction lineage. Broader novelty and market-gap claims remain unconfirmed.',
 '[  ] Granted Patent    [  ] Patent Filed / Pending    [  ] High IP Potential (Unfiled)    [  ] Open Source\nPending confirmation. No patent filing, ownership conclusion or open-source licence is asserted.',
 '[  ] Government / Defense        [  ] Critical Infrastructure / Energy\n[  ] Banking & Financial Services [X] Enterprise / Healthcare\n[  ] Small & Medium Enterprises   [X] General Public / End Users',
 'A physician obtains permission for R01 version 1. After a lab correction, the original remains historical and that permission cannot open version 2; the patient must share it separately. After withdrawal or recorded credential invalidation, the next metadata/file request in the same session is denied. A hospital profile alone grants no record access.'
],
9:[
 'Pending confirmation. A possible future institutional licensing or subscription model requires buyer interviews and pricing validation. No market-size estimate, customer contract, revenue or willingness-to-pay evidence is claimed.',
 'Proposed, subject to approval: 3 months - independent/domain review and synthetic usability sessions; 6 months - refine workflow, integration specifications and operational security; 12 months - assess an institution-approved pilot only if validation and governance gates are satisfied. No deployment or real-data pilot is currently authorized.',
 'Current demonstration uses one existing laptop and local software; no cloud or specialised lab hardware is required. Future personnel, hosting, assessment and integration costs need a costed plan. Funding amount and PKR/USD budget: pending confirmation.',
 'Data minimisation, masked CNIC display, encryption, explicit purpose/time/version scope, least privilege and separate institutional attestations. Every clinical route is checked server-side and requires durable audit evidence. A trusted local OS and protected keys are assumed; delivered copies cannot be recalled. Direct human validation remains pending.',
 '[  ] ISO 27001    [  ] NIST CSF    [  ] GDPR / Local Data Protection    [X] N/A\nNo certification, regulatory compliance or completed framework assessment is claimed. Engineering checks use documented authentication/access-control principles; formal legal/standards assessment is outside this local prototype.'
],
10:[
 '[Full recorded walkthrough]('+repo+'/blob/main/demos/sehataman-complete-walkthrough.mp4) and [all role demonstrations]('+repo+'/tree/main/demos). Public viewing/download; no GitHub sign-in required. Interactive MVP: download the [source]('+repo+') and follow README.txt to run locally. No public app deployment.',
 '[Public reviewer repository]('+repo+'). Contact-redacted source, concept note, recordings and evidence. No credentials, signing keys, sessions or demo database. The owner application repository remains private.',
 'N/A - no research publication or pitch deck supplied. Technical guide and validation evidence are included in the repository.',
 '[Setup guide]('+repo+'/blob/main/README.txt); [validation results]('+repo+'/tree/main/planning/step5_results); [frozen cases]('+repo+'/blob/main/planning/step4_frozen_scenario_manifest.json); [Pakistan evidence register]('+repo+'/blob/main/planning/pakistan_web_validation_evidence.json). Verification context: [PMDC](https://pmdc.pk/). Stakeholder validation and independent/domain review remain pending.'
]}

def fill(cell,value):
    ps=cell.findall('w:p',NS);p=ps[0]
    exemplar=p.find('w:r',NS);rpr=deepcopy(exemplar.find('w:rPr',NS)) if exemplar is not None and exemplar.find('w:rPr',NS) is not None else deepcopy(answer_rpr)
    for tag in ('i','iCs','color'):
        for el in list(rpr.findall('w:'+tag,NS)):rpr.remove(el)
    color=E.SubElement(rpr,W+'color');color.set(W+'val','000000')
    for x in list(p):
        if x.tag!=W+'pPr':p.remove(x)
    for extra in ps[1:]:cell.remove(extra)
    def text_run(parent,text):
        r=E.SubElement(parent,W+'r');r.append(deepcopy(rpr))
        t=E.SubElement(r,W+'t');t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');t.text=text
    for i,line in enumerate(value.split('\n')):
        if i:E.SubElement(E.SubElement(p,W+'r'),W+'br')
        offset=0
        for match in re.finditer(r'\[([^\]]+)\]\((https://[^\s)]+)\)',line):
            if match.start()>offset:text_run(p,line[offset:match.start()])
            rid='rIdReviewerLink'+str(len(relationships)+1)
            rel=E.SubElement(relationships,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship')
            rel.set('Id',rid);rel.set('Type','http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink');rel.set('Target',match.group(2));rel.set('TargetMode','External')
            link=E.SubElement(p,W+'hyperlink');link.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id',rid)
            text_run(link,match.group(1))
            for run in link.findall(W+'r'):
                rp=run.find(W+'rPr');color=rp.find(W+'color');color.set(W+'val','0563C1');E.SubElement(rp,W+'u').set(W+'val','single')
            offset=match.end()
        if offset<len(line):text_run(p,line[offset:])

raw=SOURCE.read_bytes();sha=hashlib.sha256(raw).hexdigest()
with ZipFile(SOURCE) as zin:
    parts={i.filename:zin.read(i.filename) for i in zin.infolist()};root=E.fromstring(parts['word/document.xml'])
    relationships=E.fromstring(parts['word/_rels/document.xml.rels'])
    tables=root.find('w:body',NS).findall('w:tbl',NS)
    answer_rpr=deepcopy(tables[1].findall('w:tr',NS)[4].findall('w:tc',NS)[1].find('.//w:rPr',NS))
    for index,values in answers.items():
        rows=tables[index].findall('w:tr',NS)
        assert len(rows)==len(values),(index,len(rows),len(values))
        for row,value in zip(rows,values):fill(row.findall('w:tc',NS)[1],value)
    team=json.loads((ROOT/'planning/application_team_details.json').read_text())
    for i,m in enumerate(team['members'],1):
        cells=tables[3].findall('w:tr',NS)[i].findall('w:tc',NS)
        fill(cells[1],m['name'])
        degree=m['role']+'; '+m['qualification']+', '+m['semester']+'.\n'+m['department']+'.\n'
        degree+=('Faculty of Computing; SEECS, NUST' if 'SEECS' in m.get('school','') else 'ASAB, NUST' if 'ASAB' in m.get('school','') else 'Faculty of Multidisciplinary Sciences; NUMS')
        fill(cells[2],degree)
        contact=m.get('public_contact_note')
        fill(cells[3],contact if contact else 'Email: '+(m['email'] or 'To be provided')+'\nPhone: '+(m['phone'] or 'To be provided'))
    fill(tables[3].findall('w:tr',NS)[2].findall('w:tc',NS)[0],'Tech Lead')
    # Filled responses use the template's existing response font. Keep the team
    # heading with its header and repeat that header on continuation pages.
    for p in root.findall('.//w:body/w:p',NS):
        if ''.join(p.itertext())=='Key Team Members:':
            pp=p.find('w:pPr',NS)
            if pp is None:pp=E.SubElement(p,W+'pPr')
            E.SubElement(pp,W+'keepNext')
    for i,row in enumerate(tables[3].findall('w:tr',NS)):
        rp=row.find('w:trPr',NS)
        if rp is None:rp=E.SubElement(row,W+'trPr')
        E.SubElement(rp,W+'cantSplit')
        if i==0:E.SubElement(rp,W+'tblHeader')
    for i in (3,4):
        cell=tables[4].findall('w:tr',NS)[i].findall('w:tc',NS)[0]
        for t in cell.findall('.//w:t',NS):
            if '[  ]' in (t.text or ''):t.text=t.text.replace('[  ]','[X]',1)
    for table in tables:
        for row in table.findall('w:tr',NS):
            rp=row.find('w:trPr',NS)
            if rp is None:rp=E.SubElement(row,W+'trPr')
            if rp.find('w:cantSplit',NS) is None:E.SubElement(rp,W+'cantSplit')
    parts['word/document.xml']=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    parts['word/_rels/document.xml.rels']=E.tostring(relationships,xml_declaration=True,encoding='UTF-8',standalone=True)
    DEST.parent.mkdir(exist_ok=True)
    with ZipFile(DEST,'w') as zout:
        for info in zin.infolist():zout.writestr(info,parts[info.filename])
with ZipFile(SOURCE) as a,ZipFile(DEST) as b:
    changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]
assert set(changed)=={'word/document.xml','word/_rels/document.xml.rels'},changed
assert SOURCE.read_bytes()==raw,'source changed'
record={'source':str(SOURCE),'source_sha256':sha,'output':str(DEST),'changed_parts':changed,
        'preserved_part_count':len(parts)-2,'answer_slots_populated':True,'submission_ready':False,'signature':'unchanged and unsigned',
        'missing_details':team['remaining_required_details'],'validation_summary':summary,
        'public_deployment':False,'repository':repo}
(ROOT/'planning/concept-note-qa/fill-verification.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(DEST)
