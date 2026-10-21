"""Additional positive/unauthorized route coverage beyond the frozen 120."""
from copy import deepcopy
import json
import time
import uuid
from step5_validate import Fixture, prepare, OUT, require, privacy, canonical
from reference_policy import ReferenceService
from sehataman.domain import Service


def run(base,arm):
    cls=Service if arm=='M' else ReferenceService;rows=[]
    routes=[
      ('GET','/me/identity','P01','H01-M01',None,200),
      ('GET','/me/reports','P01','H01-M01',None,200),
      ('GET','/me/reports/{series}/versions','P01','P02',None,200),
      ('GET','/report-versions/{v1}','P01','P02',None,200),
      ('GET','/report-versions/{v1}/file','D01','H01-M01',None,200),
      ('GET','/physician/appointments/{appointment}/records','D01','D02',None,200),
      ('GET','/me/appointments','P01','H01-M01',None,200),
      ('GET','/physician/appointments','D01','P01',None,200),
      ('GET','/me/sharing','P01','H01-M01',None,200),
      ('GET','/me/access-history','P01','H01-M01',None,200),
      ('GET','/directory/physicians','P01','H01-M01',None,200),
      ('GET','/physician/status','D01','P01',None,200),
      ('GET','/lab/workspace','L01-S01','P01',None,200),
      ('GET','/lab/submissions','L01-A02','P01',None,200),
      ('GET','/lab/reports/{series}/versions','L01-A02','L02-A02',None,200),
      ('GET','/hospital/profiles','H01-M01','P01',None,200),
      ('GET','/hospital/affiliations','H01-M01','P01',None,200),
      ('PATCH','/appointments/{appointment}/status','P01','P02',{'status':'cancelled','expected_revision':1},200),
      ('POST','/grants/{grant}/withdraw','P01','P02',{},200),
      ('POST','/hospital/profiles/{doctor}/registration-review','H01-M01','P01',{},202),
      ('POST','/lab/submissions/{submission}/return','L01-A02','L01-S01',{'reason':'Synthetic review'},200),
      ('POST','/lab/submissions/{submission}/approve','L01-A02','L02-A02',{'expected_predecessor_id':None},200)]
    for i,(method,route,yes,no,data,expected) in enumerate(routes):
        f=Fixture(base,f'{arm}-route-{i}',cls)
        try:
            s=f.state();sub=f.submit() if '{submission}' in route else None
            path=route.format(series=f.r01['series_id'],v1=f.v1,appointment=next(iter(s['appointments'])),grant=next(iter(s['grants'])),doctor=f.d01,submission=sub['id'] if sub else '')
            denied=f.call(no,method,path,data);require(denied.status==404,'unauthorized route was not rejected')
            allowed=f.call(yes,method,path,data);require(allowed.status==expected,'valid route unexpectedly rejected')
            privacy(f);rows.append({'arm':arm,'route':route,'method':method,'allowed_status':allowed.status,'denied_status':denied.status,'passed':True})
        except Exception as e:rows.append({'arm':arm,'route':route,'method':method,'passed':False,'error':str(e)})
    f=Fixture(base,arm+'-pending-identity-sharing',cls)
    try:
        f.mutate(lambda s:s['patients'][f.p01]['identity'].__setitem__('status','pending'))
        r=f.call('P01','GET','/me/sharing',expected=200)
        require(not any(g['versions'] for g in r.body['grants']),'pending identity receives clinical metadata through sharing view')
        r=f.call('P01','POST','/grants/'+next(iter(f.initial['grants']))+'/withdraw',{},200)
        require(not r.body['grant']['versions'],'withdrawal response leaks clinical metadata with pending identity')
        rows.append({'arm':arm,'route':'sharing and withdrawal with pending identity','passed':True})
    except Exception as e:rows.append({'arm':arm,'route':'sharing and withdrawal with pending identity','passed':False,'error':str(e)})
    return rows


if __name__=='__main__':
    base=prepare();rows=run(base,'M')+run(base,'R')
    p=OUT/('routes-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.json')
    p.write_bytes(canonical({'all_synthetic':True,'checks':rows,'passed':sum(r['passed'] for r in rows),'total':len(rows)}))
    for r in rows:
        if not r['passed']:print(r,flush=True)
    print('REPORT',p,flush=True)
    raise SystemExit(0 if all(r['passed'] for r in rows) else 1)
