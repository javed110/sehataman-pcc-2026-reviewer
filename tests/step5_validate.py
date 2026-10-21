"""Execute frozen cases on isolated synthetic homes; never mutate the live demo.

Run from repository root with PYTHONPATH pointing to this directory and root.
The assertion source is the preimplementation manifest, not either arm's output.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import uuid

from test_mvp import MvpChecks, ROOT
from reference_policy import ReferenceService
from sehataman.bootstrap import bootstrap
from sehataman.crypto import canonical, digest, iso, timestamp, totp
from sehataman.domain import Service
from sehataman.issuer import sign_package
from sehataman.server import LocalServer
from sehataman.storage import IntegrityFailure

OUT = ROOT / 'planning' / 'step5_results'
RUN = ROOT / '.local' / 'step5-runs' / uuid.uuid4().hex
MANIFEST = ROOT / 'planning' / 'step4_frozen_scenario_manifest.json'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Fixture(MvpChecks):
    def __init__(self, base, name, cls=Service):
        super().__init__('runTest')
        self.home = RUN / name
        shutil.copytree(base, self.home)
        self.store = bootstrap(self.home)
        self.service = cls(self.store)
        with self.store.transaction() as tx:
            self.initial = deepcopy(tx.state)
            self.audit_start = len(tx.history)
        self.users = {u['alias']: u for u in self.initial['users'].values()}
        self.p01, self.p02, self.d01 = [self.users[a]['id'] for a in ('P01', 'P02', 'D01')]
        self.r01 = next(v for v in self.initial['versions'].values() if self.initial['series'][v['series_id']]['alias'] == 'R01')
        self.v1 = self.r01['id']
        self.accounts = json.loads((self.store.protected / 'demo-accounts.json').read_text('utf-8'))
        sessionfile = self.store.protected / 'benchmark-clients.json'
        self.clients = json.loads(sessionfile.read_text('utf-8')) if sessionfile.exists() else {}
        self.responses = []; self.actions = []

    def call(self, actor, method, path, data=None, expected=None, extra=None):
        if actor != 'anonymous' and actor not in self.clients:
            self.login(actor)
        headers={'Origin':self.service.origin}
        if actor!='anonymous':headers.update(self.clients[actor])
        headers.update(extra or {})
        request_id='case-'+uuid.uuid4().hex
        result=self.service.handle(method,'/api'+path,headers,data,request_id)
        if expected is not None:self.assertEqual(result.status,expected,result.body)
        self.responses.append((actor, method, path, result))
        self.actions.append({'actor': actor, 'method': method, 'route': path,
                             'request_id':request_id,'status': result.status, 'response_sha256': digest(result.body if isinstance(result.body, bytes) else canonical(result.body))})
        return result

    def mutate(self, fn, reason='declared_case_override'):
        with self.store.transaction() as tx:
            fn(tx.state)
            tx.audit('benchmark_fixture_transition', reason=reason, request_id='fixture-' + uuid.uuid4().hex)

    def version(self, alias='R02'):
        return next(v for v in self.state()['versions'].values() if self.state()['series'][v['series_id']]['alias'] == alias)

    def amendment(self):
        sub = self.submit(amendment=True)
        return self.approve(sub).body['version']['id']

    def package(self, lab='L01'):
        source = self.source()
        if lab == 'L02':
            order = next(x for x in self.initial['orders'].values() if x['alias'] == 'O02')
            source.update(order_id=order['id'], specimen_alias='S02', approver_id=self.users['L02-A02']['id'])
        alias = lab + '-S01'
        sub = self.call(alias, 'POST', '/lab/submissions', source, 201).body['submission']
        p = deepcopy(self.state()['submissions'][sub['id']]['package'])
        p['manifest']['message_id'] = 'INGEST-' + uuid.uuid4().hex
        return sign_package(self.store, lab, p['manifest'], p['content'])

    def http(self, actor, method, path, data=None, headers=None, raw=None):
        server = LocalServer(self.store, 0)
        server.service = type(self.service)(self.store, f'http://127.0.0.1:{server.server_port}')
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            h = {'Origin': server.service.origin, 'Content-Type': 'application/json'}
            if actor != 'anonymous':
                h.update(self.clients[actor])
            h.update(headers or {})
            payload = raw if raw is not None else canonical(data or {}) if method != 'GET' else None
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            client.request(method, '/api' + path, payload, h)
            response = client.getresponse(); status, meta, body = response.status, dict(response.getheaders()), response.read()
            client.close()
            return status, meta, body
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def restart(self):
        result = subprocess.run([sys.executable, str(ROOT / 'manage.py'), '--home', str(self.home), 'verify'],
                                capture_output=True, text=True, timeout=20, cwd=ROOT)
        require(result.returncode == 0, 'fresh process rejected committed store')
        self.store = bootstrap(self.home); self.service = type(self.service)(self.store)


def prepare():
    RUN.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
    clean = RUN / 'clean'; bootstrap(clean)
    f = Fixture(clean, 'base')
    for alias in f.users:
        f.login(alias)
    a = f.book(); f.share(a)
    (f.store.protected / 'benchmark-clients.json').write_bytes(canonical(f.clients))
    return f.home


def execute(f, case):
    key = case['id']; family, index = key.split('-'); n = int(index)
    p = case['action']['parameters_and_state_overrides']; actor = case['actor']
    status = None; details = []
    def read(who=actor, version=None, file=False):
        nonlocal status
        r = f.call(who, 'GET', '/report-versions/' + (version or f.v1) + ('/file' if file else ''))
        status = r.status
        if status != 200:
            require(not isinstance(r.body, bytes) and 'report' not in r.body, 'denied request released a protected payload')
        return r
    def setfield(collection, identity, field, value):
        f.mutate(lambda s: s[collection][identity].__setitem__(field, value))
    def grant():
        return next(iter(f.state()['grants'].values()))
    def appointment():
        return next(iter(f.state()['appointments'].values()))
    def profile_data():
        x = f.state()['profiles'][f.d01]
        return {k: x[k] for k in ('specialty', 'languages', 'location', 'fee')} | {'expected_revision': x['profile_revision']}
    def submit_data():
        x = f.source()
        if 'order' in p:
            order = next(v for v in f.initial['orders'].values() if v['alias'] == p['order'])
            pat = f.initial['patients'][order['patient_id']]
            x.update(order_id=order['id'], cnic=pat['cnic'], dob=pat['dob'], specimen_alias=order['specimen_alias'])
            x['approver_id'] = f.users[('L02' if p['order'] == 'O02' else 'L01') + '-A02']['id']
        for a, b in [('cnic', 'cnic'), ('dob', 'dob'), ('specimen', 'specimen_alias')]:
            if a in p: x[b] = p[a]
        return x
    if family == 'F01':
        if n <= 7:
            who = actor if actor != 'anonymous' else 'P01'
            row = next(x for x in f.accounts if x['alias'] == who)
            f.mutate(lambda s: s['users'][f.users[who]['id']].__setitem__('last_factor_counter', -1))
            data = {'username': p.get('username', row['username']), 'password': row['password'] if p['password'] == 'correct' else p['password'],
                    'totp': totp(row['totp_secret']) if p['totp'] == 'current' else p['totp']}
            r = f.call('anonymous', 'POST', '/sessions', data); status = r.status
            require(('Set-Cookie' in r.headers) == (n <= 4), 'login session outcome differs')
            if n <= 4: require(r.body['user']['role'] == f.users[who]['role'], 'wrong server role')
            else: require(r.body['error'] == 'invalid_credentials', 'non-generic credential response')
        elif n == 8:
            f.mutate(lambda s: s['patients'][f.p01]['identity'].__setitem__('status', 'pending')); read()
        elif n == 9:
            f.mutate(lambda s: [x.__setitem__('expires_at', time.time()-1) for x in s['users'][f.p01]['sessions'].values()]); read()
        else:
            r = f.call('anonymous', 'POST', '/recovery-requests', {'account': p['cnic']}, 202)
            require('Set-Cookie' not in r.headers, 'CNIC recovery created a session'); read('anonymous')
    elif family == 'F02':
        x = submit_data()
        if n == 10: f.mutate(lambda s: s['patients'][f.p01]['identity'].__setitem__('status', 'pending'))
        before = len(f.state()['versions'])
        r = f.call(actor, 'POST', '/lab/submissions', x); status = r.status
        if status == 201:
            require(r.body['submission']['status'] == ('awaiting_approval' if n <= 4 else 'held'), 'wrong admission state')
        require(len(f.state()['versions']) == before, 'submission bypassed distinct approval')
    elif family == 'F03':
        if n in (3, 8):
            aff = next(x for x in f.state()['affiliations'].values() if x['physician_id'] == f.d01)
            before = f.state()['profiles'][f.d01]['registration']
            r = f.call(actor, 'POST', '/hospital/affiliations/' + aff['id'] + '/status',
                       {'status': 'valid', 'reason': 'Synthetic renewal', 'expected_revision': aff['revision']}); status = r.status
            require(f.state()['profiles'][f.d01]['registration'] == before, 'affiliation changed registration')
        elif n in (4, 7):
            before = f.state()['profiles'][f.d01]['registration']; x = profile_data()
            if n == 4: x['languages'] = p['language']
            else: x['registration'] = 'valid'
            r = f.call(actor, 'PATCH', '/hospital/profiles/' + f.d01, x); status = r.status
            require(f.state()['profiles'][f.d01]['registration'] == before, 'profile self-verified registration')
        elif n == 9: status = f.call(actor, 'POST', '/hospital/registration', {'status': 'valid'}).status
        else:
            if n == 2:
                f.mutate(lambda s: (s['credential_history'].append(deepcopy(s['profiles'][f.d01]['registration'])), s['profiles'][f.d01]['registration'].__setitem__('source_ref','SIM-RENEWED')))
            if n in (5, 6):
                who = f.users[actor]['id']
                f.mutate(lambda s: (next(iter(s['grants'].values())).__setitem__('physician_id', who),
                                    next(iter(s['appointments'].values())).__setitem__('physician_id', who)))
            if n == 10: f.mutate(lambda s: next(iter(s['grants'].values())).__setitem__('hospital_id', 'H99'))
            read()
    elif family == 'F04' or (family == 'F06' and n == 4) or (family == 'F12' and n == 4):
        if case['action']['operation'] == 'grant':
            a = appointment(); versions = p.get('versions', ['R01-V1']); ids = []
            for name in versions:
                ids.append(f.amendment() if name == 'R01-V2' else f.version()['id'] if name == 'R02-V1' else f.v1)
            if family == 'F12':
                f.mutate(lambda s: next(iter(s['grants'].values())).__setitem__('expires_at', s['clock']))
            r = f.call(actor, 'POST', '/grants', {'appointment_id': a['id'], 'version_ids': ids, 'purpose':'consultation',
                       'starts_at': f.initial['clock'], 'expires_at': iso(timestamp(f.initial['clock'])+p.get('duration_minutes',90)*60), 'acknowledged':True})
            status = r.status
            if status == 201: require(r.body['grant']['version_ids'] == ids, 'grant broadened versions')
        else:
            if n == 3: setfield('appointments', appointment()['id'], 'status', 'confirmed')
            if n == 5: f.mutate(lambda s: s['grants'].clear())
            if n == 7: setfield('grants', grant()['id'], 'appointment_id', 'A99')
            if n == 10: setfield('grants', grant()['id'], 'purpose', 'other')
            read()
    elif family == 'F05':
        r = read(file=case['action']['operation'] == 'read_file')
        if n == 10:
            r = f.call(actor, 'GET', '/report-versions/' + f.v1, p); status = r.status
        if n == 5:
            missing = f.call(actor, 'GET', '/report-versions/' + str(uuid.uuid4()))
            require(r.body == missing.body, 'object-existence shape leak')
        if n in (2,4):
            require(isinstance(r.body, bytes) and b'SYNTHETIC' in r.body, 'expected protected text file')
    elif family == 'F06':
        if n in (1,2,3,5):
            v2 = f.amendment()
            require(f.state()['versions'][f.v1]['package'] == f.r01['package'], 'original changed')
            if n == 1: status=200; require(f.state()['series'][f.r01['series_id']]['current_version_id']==v2,'head not advanced')
            if n == 2:
                r=read(version=f.v1); require(r.body['report']['status']=='superseded' and v2 not in canonical(r.body).decode(),'old scope widened')
            if n == 3:
                r=f.call(actor,'GET','/me/reports/'+f.r01['series_id']+'/versions'); status=r.status
                require({v['version'] for v in r.body['versions']}=={1,2},'lineage missing')
            if n == 5: read(version=v2)
        elif n in (6,9):
            x=f.source(True)
            if n==6:x['correction_reason']=''
            r=f.call(actor,'POST','/lab/reports/'+f.r01['series_id']+'/amendments',x);status=r.status
        elif n==7:
            sub=f.submit(amendment=True); status=f.call(actor,'POST','/lab/submissions/'+sub['id']+'/approve',{'expected_predecessor_id':f.v1}).status
        elif n==8:
            pkg=f.package(); pkg['manifest'].update(approver_id=f.users['L02-A02']['id'])
            pkg=sign_package(f.store,'L01',pkg['manifest'],pkg['content'])
            sub=f.call('L01-S01','POST','/lab/ingest',{'package':pkg},201).body['submission']
            status=f.approve(sub,409).status
        else: status=f.call(actor,'PATCH','/report-versions/'+f.v1,{'result':'changed'}).status
    elif family == 'F07':
        if n in (3,4,10):
            if n==4:
                pub=f.store.protected/'issuer-key-lifecycle.json'; pub.write_text('{"L01":"retired_not_compromised"}')
                details.append('Historical public key retained; lifecycle annotation is test metadata, not a runtime rotation feature.')
            if n==10:
                with sqlite3.connect(f.store.db_path) as db: db.execute('UPDATE state SET body=?',(b'corrupted',))
            read()
        else:
            lab='L02' if n==2 else 'L01';pkg=f.package(lab)
            if n==5:pkg['manifest']['lab_id']='L99'
            if n in (6,7):pkg['content']+='ALTERED SYNTHETIC'
            if n==7:pkg['manifest']['content_digest']=digest(pkg['content'].encode())
            if n==8:pkg['manifest']['specimen_alias']='changed_after_signing'
            if n==9:pkg['manifest']['approver_id']=None
            r=f.call(actor,'POST','/lab/ingest',{'package':pkg});status=r.status
            if status==201:require(r.body['submission']['status']==('awaiting_approval' if n<=2 else 'held'),'bad integrity package admitted')
    elif family == 'F08':
        if n in (1,2,5):
            x=f.source();sub=f.submit(x)
            if n==1:status=201
            else:
                if n==5:x['result']='Changed synthetic'
                r=f.call(actor,'POST','/lab/submissions',x);status=r.status
                if n==2:require(r.body['submission']['id']==sub['id'],'replay produced another receipt')
            require(len(f.state()['submissions'])==1,'replay created extra effect')
        elif n==3:
            v2=f.amendment();x=f.source(True);x.update(version=3,predecessor_id=v2)
            sub=f.submit(x,True);status=f.approve(sub).status
            require(len([v for v in f.state()['versions'].values() if v['series_id']==f.r01['series_id']])==3,'successive lineage lost')
        elif n==4:
            for _ in range(2):status=f.call('P01','POST','/grants/'+grant()['id']+'/withdraw',{}).status
            require(grant()['status']=='revoked','withdrawal reactivated')
        elif n in (6,7,8):
            a=f.submit(amendment=True);b=f.submit(amendment=True)
            f.approve(a)
            status=f.approve(b,409).status
            require(len([v for v in f.state()['versions'].values() if v['series_id']==f.r01['series_id']])==2,'conflicting head accepted')
            if n==8: details.append('Two distinct messages propose the same source/version; second approval rejected.')
        elif n==9:
            with sqlite3.connect(f.store.db_path) as db: old=db.execute('SELECT body FROM state').fetchone()[0]
            f.call('P01','POST','/grants/'+grant()['id']+'/withdraw',{},200)
            with sqlite3.connect(f.store.db_path) as db: db.execute('UPDATE state SET body=?',(old,))
            read('P01')
        else:
            pkg=f.package('L02');pkg['manifest']['lab_id']=f.users['L01-S01']['org_id'];pkg['manifest']['lab_alias']='L01'
            r=f.call(actor,'POST','/lab/ingest',{'package':pkg});status=r.status
            require(r.body['submission']['status']=='held','cross-lab issuer impersonation')
    elif family == 'F09':
        if n in (1,10):
            f.call('D01','GET','/report-versions/'+f.v1,expected=200)
            r=f.call(actor,'GET','/me/access-history',p);status=r.status
            if n==10:require('Demo Physician D01' not in canonical(r.body).decode(),'foreign access history leaked')
        elif n==2:
            read(); require(any(e['action']=='release_prepared' and e['version_id']==f.v1 for e in audit_events(f)),'missing durable release audit')
        elif n==3:
            f.amendment();r=f.call('P01','GET','/me/reports/'+f.r01['series_id']+'/versions');status=r.status
            require(all(v['source_report_id'] and v['approver'] and v['content_digest'] for v in r.body['versions']),'missing provenance')
        elif n in (4,7,8):
            if n>4:
                with sqlite3.connect(f.store.db_path) as db:
                    if n==7:db.execute('UPDATE audit SET body=? WHERE seq=(SELECT MAX(seq) FROM audit)',(b'altered',))
                    else:db.execute('DELETE FROM audit WHERE seq=(SELECT MAX(seq) FROM audit)')
            try:f.store.verify();status=0
            except IntegrityFailure:status=1
        elif n in (5,6):status=f.call(actor,'PATCH' if n==5 else 'DELETE','/audit',{}).status
        else:
            for who,route in [('P01','/me/identity'),('P01','/me/reports'),('P01','/me/access-history'),('P01','/directory/physicians'),('H01-M01','/hospital/profiles'),('L01-S01','/lab/workspace')]:
                f.call(who,'GET',route,expected=200)
            privacy(f);status=0
    elif family == 'F10':
        if n<=4:
            before=f.state()
            if n==3:
                aff=next(v for v in before['affiliations'].values() if v['physician_id']==f.d01)
                f.call('H01-M01','POST','/hospital/affiliations/'+aff['id']+'/status',{'status':'revoked','reason':'Synthetic test','expected_revision':1},200)
                before=f.state()
            f.restart();after=f.state()
            for k in ('versions','grants','affiliations','appointments'):require(before[k]==after[k],'restart lost committed '+k)
            if n==3:read('D01');require(status==404,'revocation lost on restart');status=200
            else:status=0 if n==4 else 200
        elif n==5:
            count=len(f.state()['grants']);f.store.inject_audit_failure=True
            r=f.call('P01','POST','/grants',{'appointment_id':appointment()['id'],'version_ids':[f.v1],'purpose':'consultation','starts_at':f.initial['clock'],'expires_at':iso(timestamp(f.initial['clock'])+3600),'acknowledged':True});status=r.status
            f.store.inject_audit_failure=False;require(len(f.state()['grants'])==count,'failed grant partially committed')
        elif n==6:f.store.inject_audit_failure=True;read();f.store.inject_audit_failure=False
        elif n==7:
            sub=f.submit(amendment=True);f.store.inject_audit_failure=True
            status=f.call('L01-A02','POST','/lab/submissions/'+sub['id']+'/approve',{'expected_predecessor_id':f.v1}).status
            f.store.inject_audit_failure=False;require(f.state()['series'][f.r01['series_id']]['current_version_id']==f.v1,'interrupted correction committed')
        elif n==8:
            g=grant();f.store.inject_checkpoint_failure=True
            status=f.call('P01','POST','/grants/'+g['id']+'/withdraw',{}).status
            f.store.inject_checkpoint_failure=False
            with sqlite3.connect(f.store.db_path) as db: blob=db.execute('SELECT body FROM state').fetchone()[0]
            require(json.loads(f.store.cipher.decrypt(blob))['grants'][g['id']]['status']=='revoked','committed revocation lost')
            require(f.call('D01','GET','/report-versions/'+f.v1).status==503,'checkpoint failure reanchored silently')
        elif n==9:
            f.store.checkpoint.rename(f.store.checkpoint.with_suffix('.held'))
            try:f.store.verify();status=0
            except IntegrityFailure:status=1
        else:f.call('P01','POST','/grants/'+grant()['id']+'/withdraw',{},200);read()
    elif family == 'F11':
        if n==1:
            raw=canonical(f.source());raw+=b' '*(2048-len(raw));status,_,_=f.http(actor,'POST','/lab/submissions',raw=raw)
        elif n in (2,9):
            x=profile_data();x.update({'specialty':'<script>demo</script>'} if n==2 else {'role':'admin','verified':True})
            status=f.call(actor,'PATCH','/hospital/profiles/'+f.d01,x).status
            if n==2:require(f.state()['profiles'][f.d01]['specialty']=='<script>demo</script>','text not preserved for escaping check')
        elif n in (3,5,6):
            x={'appointment_id':appointment()['id'],'version_ids':[f.v1],'purpose':'consultation','starts_at':f.initial['clock'],'expires_at':iso(timestamp(f.initial['clock'])+1800),'acknowledged':True}
            headers={} if n==3 else {'Origin':'https://untrusted.invalid'} if n==5 else {'X-CSRF-Token':''}
            status,_,body=f.http(actor,'POST','/grants',x,headers)
            if n>3:require(b'"grant"' not in body,'cross-origin/CSRF mutation succeeded')
        elif n==4:
            r=f.call(actor,'GET','/directory/physicians');status=r.status
            matches=[v for v in r.body['physicians'] if v['specialty']==p['specialty'] and p['language'] in v['languages']]
            require(len(matches)==1 and matches[0]['alias']=='D01','directory filter wrong');details.append('Filters are applied in the UI over the scoped public directory response.')
        elif n==7:status,_,_=f.http(actor,'POST','/lab/submissions',raw=b'x'*70000)
        elif n==8:status,_,body=f.http(actor,'GET','/report-versions/../../protected/keys.json');require(b'encryption' not in body,'private file exposed')
        else:
            for _ in range(12):status=f.call('anonymous','POST','/sessions',{'username':'p01','password':'wrong','totp':'000000'}).status
    elif family == 'F12':
        if n in (1,2,5,6):
            g=grant();clock=timestamp(g['expires_at'])+(-1 if n==1 else 1 if n==6 else 0) if n!=2 else timestamp(g['starts_at'])
            f.mutate(lambda s:s.__setitem__('clock',iso(clock)))
        elif n==7:f.call('P01','POST','/grants/'+grant()['id']+'/withdraw',{},200)
        elif n==8:f.call('P01','PATCH','/appointments/'+appointment()['id']+'/status',{'status':'cancelled','expected_revision':1},200)
        elif n==9:
            aff=next(v for v in f.state()['affiliations'].values() if v['physician_id']==f.d01)
            f.call('H01-M01','POST','/hospital/affiliations/'+aff['id']+'/status',{'status':'revoked','reason':'Synthetic revocation','expected_revision':1},200)
        elif n==10:f.mutate(lambda s:s['profiles'][f.d01]['registration'].__setitem__('status','stale'))
        read(file=case['action']['operation']=='read_file')
    else:raise AssertionError('Unimplemented frozen case')
    require(status is not None,'case did not execute an assertion')
    return status, details


def audit_events(f):
    with f.store.transaction() as tx:return deepcopy(tx.history)


def privacy(f):
    secrets=[p['cnic'] for p in f.initial['patients'].values()]+[p['cnic'].replace('-','') for p in f.initial['patients'].values()]
    secrets += [a[k] for a in f.accounts for k in ('password','totp_secret')]
    for actor, method, path, r in f.responses:
        encoded=(r.body.decode('utf-8') if isinstance(r.body,bytes) else canonical(r.body).decode())
        require(not any(value in encoded for value in secrets),'full synthetic CNIC or password/factor seed leaked')
        require('password_hash' not in encoded and 'factor_secret' not in encoded,'authentication storage leaked')


def validate_case(base, case, arm):
    f=Fixture(base,arm+'-'+case['id'],ReferenceService if arm=='R' else Service)
    started=time.perf_counter(); result={'id':case['id'],'arm':arm,'category':case['category'],'designation':case['designation'],'expected_status':case['expected']['status']}
    try:
        status,notes=execute(f,case);result.update(actual_status=status,notes=notes)
        require(status==case['expected']['status'],'frozen status mismatch: expected %s, got %s'%(case['expected']['status'],status))
        privacy(f)
        try:
            events=audit_events(f)
            new=events[f.audit_start:]
            incomplete=[e['action'] for e in new if not all(e.get(k) for k in ('actor_id','action','server_time','outcome','request_id','reason_code'))]
            result['audit_events']=len(new);result['incomplete_audit_events']=incomplete
            require(not incomplete,'audit events lack decision basis or correlation: '+','.join(sorted(set(incomplete))))
            for action in f.actions:
                if action['status']!=503:
                    require(any(e['request_id']==action['request_id'] for e in new),'missing correlated durable API event')
            s=f.state();required={'lab_id','patient_id','order_id','specimen_id','specimen_alias','source_report_id','issued_at',
                'submitter_id','approver_id','content_digest','target','method','specimen_type','version'}
            accepted=[v for v in s['versions'].values() if v['status'] in ('accepted','superseded')]
            for v in accepted:
                m=v['package']['manifest']
                require(all(m.get(k) is not None and m.get(k)!='' for k in required),'required provenance field absent')
                require(v['accepted_at'] and v['received_at'],'source timestamps missing')
                if m['version']>1:require(m['predecessor_id'] in s['versions'] and bool(m['correction_reason']),'amendment lineage missing')
            for identity,v in f.initial['versions'].items():
                require(s['versions'][identity]['package']==v['package'],'accepted original source package overwritten')
            result['accepted_versions_checked']=len(accepted)
        except IntegrityFailure:
            require(case['id'] in {'F07-10','F08-09','F09-07','F09-08','F10-08','F10-09'},'unexpected integrity hold')
        result['passed']=True
    except Exception as exc:
        result.update(passed=False,error=type(exc).__name__+': '+str(exc))
    result.update(milliseconds=round((time.perf_counter()-started)*1000,3),actions=f.actions)
    return result


def main():
    freeze=json.loads((ROOT/'planning/step4_manifest_freeze.json').read_text('utf-8'))
    require(digest(MANIFEST.read_bytes())==freeze['digest'],'frozen manifest was altered')
    base=prepare();cases=json.loads(MANIFEST.read_text('utf-8'))['cases'];results=[]
    source_hashes={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in list((ROOT/'sehataman').glob('*.py'))+[Path(__file__),ROOT/'tests/reference_policy.py']}
    for arm in ('M','R'):
        for case in cases:
            r=validate_case(base,case,arm);results.append(r)
            if not r['passed']:print(arm,r['id'],r.get('error'),flush=True)
        print(arm,'completed:',sum(x['passed'] for x in results if x['arm']==arm),'/120',flush=True)
    report={'kind':'Frozen-case engineering evaluation','run':str(RUN),'manifest_sha256':freeze['digest'],
            'source_hashes':source_hashes,'reference_specification':'../step5_reference_specification.json',
            'independent_domain_review':'pending','blinded':False,'data':'all synthetic','results':results,
            'summary':{a:{'passed':sum(x['passed'] for x in results if x['arm']==a),'total':120} for a in ('M','R')}}
    filename=OUT/('cases-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.json')
    filename.write_bytes(canonical(report));(OUT/'latest-cases.json').write_bytes(canonical({'report':filename.name,'summary':report['summary']}))
    print('REPORT',filename,flush=True)
    return 0 if all(x['passed'] for x in results) else 1


if __name__=='__main__':raise SystemExit(main())
