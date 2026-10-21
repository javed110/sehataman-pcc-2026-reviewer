"""Coordinated ordering traces and identical HTTP workload for M and R."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import contextlib
import http.client
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import sys
import threading
import time
import uuid

import step5_validate as suite
from step5_validate import Fixture, prepare, require, audit_events, OUT, RUN, ROOT
from reference_policy import ReferenceService
from sehataman.crypto import canonical, digest
from sehataman.domain import Service
from sehataman.server import LocalServer


NETWORK=[]
def network_guard(event,args):
    if event=='socket.connect':
        address=args[1]
        host=address[0] if isinstance(address,tuple) else str(address)
        NETWORK.append(host)
        if host not in ('127.0.0.1','::1','localhost'):
            raise PermissionError('Synthetic benchmark blocks non-loopback connections')


def percentile(values,p):
    values=sorted(values)
    return values[max(0,min(len(values)-1,int(len(values)*p+0.999999)-1))]


def trace(base,arm,transition,index):
    f=Fixture(base,f'{arm}-trace-{transition}-{index:03d}',ReferenceService if arm=='R' else Service)
    state=f.state();g=next(iter(state['grants'].values()));a=next(iter(state['appointments'].values()))
    aff=next(v for v in state['affiliations'].values() if v['physician_id']==f.d01)
    gate=threading.Barrier(2); ids=['trace-'+uuid.uuid4().hex for _ in range(2)]
    result={'arm':arm,'transition':transition,'index':index}
    try:
        if transition=='competing_corrections':
            subs=[f.submit(amendment=True),f.submit(amendment=True)]
            def approve(i):
                gate.wait(timeout=10)
                return f.service.handle('POST','/api/lab/submissions/'+subs[i]['id']+'/approve',
                    {'Origin':f.service.origin,**f.clients['L01-A02']},{'expected_predecessor_id':f.v1},ids[i]).status
            with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(approve,range(2)))
            require(sorted(statuses)==[200,409],'conflicting successors did not serialize')
            after=f.state();versions=[v for v in after['versions'].values() if v['series_id']==f.r01['series_id']]
            require(len(versions)==2,'fork or lost original')
            require(after['versions'][f.v1]['package']==f.r01['package'],'original overwritten')
            result.update(statuses=statuses,accepted_heads=1)
        else:
            def change():
                gate.wait(timeout=10)
                if transition=='withdrawal':
                    return f.service.handle('POST','/api/grants/'+g['id']+'/withdraw',{'Origin':f.service.origin,**f.clients['P01']},{},ids[0]).status
                if transition=='appointment':
                    return f.service.handle('PATCH','/api/appointments/'+a['id']+'/status',{'Origin':f.service.origin,**f.clients['P01']},{'status':'cancelled','expected_revision':1},ids[0]).status
                if transition=='affiliation':
                    return f.service.handle('POST','/api/hospital/affiliations/'+aff['id']+'/status',{'Origin':f.service.origin,**f.clients['H01-M01']},{'status':'revoked','reason':'Synthetic trace','expected_revision':1},ids[0]).status
                with f.store.transaction() as tx:
                    tx.state['profiles'][f.d01]['registration']['status']='stale'
                    tx.audit('synthetic_registration_stale',{'id':'local-synthetic-verifier','label':'Local Synthetic Fixture Verifier','role':'local_fixture'},object_id=f.d01,reason='simulated_evidence_only',request_id=ids[0])
                return 200
            def read():
                gate.wait(timeout=10)
                return f.service.handle('GET','/api/report-versions/'+f.v1+('/file' if index%2 else ''),f.clients['D01'],request_id=ids[1])
            with ThreadPoolExecutor(max_workers=2) as pool:
                c=pool.submit(change);r=pool.submit(read);changed=c.result(timeout=20);reply=r.result(timeout=20)
            require(changed==200,'invalidation failed')
            require(reply.status in (200,404),'race request unexpected outcome')
            events=audit_events(f);commits=[e for e in events if e['request_id']==ids[0]]
            require(bool(commits),'missing invalidation ordering evidence')
            cut=commits[-1]['sequence'];decisions=[e for e in events if e['request_id']==ids[1]]
            require(not any(e['action']=='release_prepared' and e['sequence']>cut for e in decisions),'release ordered after invalidation')
            subsequent=f.service.handle('GET','/api/report-versions/'+f.v1+('/file' if index%2 else ''),f.clients['D01'])
            require(subsequent.status==404 and not isinstance(subsequent.body,bytes) and 'report' not in subsequent.body,'post-commit request disclosed clinical data')
            result.update(racing_read_status=reply.status,postcommit_status=subsequent.status,commit_sequence=cut,
                          racing_decision_sequences=[e['sequence'] for e in decisions])
        result['passed']=True
    except Exception as exc:result.update(passed=False,error=type(exc).__name__+': '+str(exc))
    return result


def performance(base,arm):
    f=Fixture(base,arm+'-performance',ReferenceService if arm=='R' else Service)
    server=LocalServer(f.store,0);server.service=type(f.service)(f.store,f'http://127.0.0.1:{server.server_port}')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    route='/api/report-versions/'+f.v1
    def request(i):
        alias='D01' if i%2==0 else 'D02';expected=200 if i%2==0 else 404
        started=time.perf_counter();status=None;error=None;leak=False;headers={}
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
            conn.request('GET',route,headers=f.clients[alias]);response=conn.getresponse()
            status=response.status;headers=dict(response.getheaders());body=response.read();conn.close()
            if expected==404:leak=b'"report"' in body or b'Not detected' in body
            require(status==expected,'unexpected status '+str(status));require(not leak,'denied metadata leak')
            require('no-store' in headers.get('Cache-Control',''),'cache policy absent')
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        return {'index':i,'expected_status':expected,'status':status,'milliseconds':round((time.perf_counter()-started)*1000,3),'error':error,'leak':leak}
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:warmup=list(pool.map(request,range(100)))
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as pool:rows=list(pool.map(request,range(1000)))
        elapsed=time.perf_counter()-start
        values=[r['milliseconds'] for r in rows]
        extras={}
        for name,alias,path in [('file','D01',route+'/file'),('login','anonymous','/api/sessions')]:
            started=time.perf_counter()
            if name=='file':r=f.http(alias,'GET',path[4:]);extras[name]={'milliseconds':round((time.perf_counter()-started)*1000,3),'status':r[0],'includes_adapter_startup':True}
            else:
                # Login is timed separately and uses an unused synthetic factor counter.
                f.mutate(lambda s:s['users'][f.p02].__setitem__('last_factor_counter',-1))
                started=time.perf_counter();r=f.login('P02');extras[name]={'milliseconds':round((time.perf_counter()-started)*1000,3),'status':r.status,'transport':'service boundary'}
        return {'arm':arm,'requests':1000,'permitted':500,'denied':500,'concurrency':10,'warmup_requests':100,
                'warmup_errors':sum(bool(x['error']) for x in warmup),'errors':sum(bool(x['error']) for x in rows),
                'denied_leaks':sum(x['leak'] for x in rows),'p50_ms':percentile(values,.5),'p95_ms':percentile(values,.95),
                'maximum_ms':max(values),'elapsed_seconds':round(elapsed,3),'target_p95_ms':1000,
                'target_met':percentile(values,.95)<=1000 and not any(x['error'] for x in rows),
                'measurement':'Client elapsed loopback HTTP metadata response including queue, authorization, full integrity verification and durable audit commit; not browser rendering.',
                'separate_timings':extras,'rows':rows}
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


def main():
    sys.addaudithook(network_guard)
    base=prepare();traces=[];perf=[];started=time.time()
    for arm in ('M','R'):
        for transition in ('withdrawal','affiliation','registration','appointment','competing_corrections'):
            rows=[trace(base,arm,transition,i) for i in range(100)];traces+=rows
            print(arm,transition,sum(x['passed'] for x in rows),'/100',flush=True)
        p=performance(base,arm);perf.append(p)
        print(arm,'HTTP performance p95',p['p95_ms'],'ms; errors',p['errors'],flush=True)
    report={'run':str(RUN),'all_synthetic':True,'started_unix':started,
            'hardware':{'platform':platform.platform(),'processor':platform.processor(),'logical_cpus':os.cpu_count(),'python':sys.version,'sqlite':__import__('sqlite3').sqlite_version},
            'network_destinations':sorted(set(NETWORK)),'non_loopback_destinations':[],
            'traces':traces,'performance':perf,'summary':{a:{'traces_passed':sum(x['passed'] for x in traces if x['arm']==a),'traces_total':500} for a in ('M','R')},
            'limits':['Single laptop, sequential M then R; no randomized hardware crossover or production sizing.','Synthetic purposive traces are not independent human subjects.','Shared-stack constructed reference; no commercial superiority inference.','Direct stakeholder validation and independent/domain review pending.']}
    filename=OUT/('benchmarks-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.json')
    filename.write_bytes(canonical(report));(OUT/'latest-benchmarks.json').write_bytes(canonical({'report':filename.name,'summary':report['summary']}))
    print('REPORT',filename,flush=True)
    return 0 if all(x['passed'] for x in traces) and all(x['target_met'] for x in perf) else 1


if __name__=='__main__':raise SystemExit(main())
