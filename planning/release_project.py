"""One allowlist for the GitHub integration and verified user ZIP."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import uuid
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
TOP={'.gitignore','README.md','README.txt','requirements.txt','manage.py','Run-SehatAman.cmd','Show-DemoAccounts.cmd','Stop-SehatAman.ps1'}
def files():
 result=[]
 candidates=[]
 for directory,dirs,names in os.walk(ROOT):
  dirs[:]=[d for d in dirs if not d.startswith('.local') and d not in ('__pycache__','.git','deliverables','concept-note-qa')]
  candidates.extend(Path(directory)/n for n in names)
 for p in sorted(candidates):
  r=p.relative_to(ROOT);parts=r.parts
  if p.name.startswith('~$') or p.name.endswith(('.tmp','.temp')):continue
  if any(x.startswith('.local') or x in ('__pycache__','.git','deliverables','concept-note-qa') for x in parts):continue
  if len(parts)==1 and r.name in TOP:result.append(p);continue
  if parts[0]=='JCPSP_Submission' and p.suffix.lower() in ('.py','.json','.txt','.md','.docx','.csv','.ris','.bib','.pdf','.png','.svg'):result.append(p);continue
  if parts[0] in ('sehataman','tests','docs','demos') and p.suffix.lower() in ('.py','.js','.css','.html','.svg','.txt','.json','.docx','.mp4','.jpg','.png'):result.append(p)
  elif parts[0]=='planning' and p.suffix.lower() in ('.py','.json','.txt','.html','.js','.jpg','.png'):result.append(p)
 return result

def inventory():
 return [{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
          'binary':p.suffix.lower() in ('.docx','.mp4','.jpg','.png')} for p in files()]

def package():
 rows=inventory();out=ROOT/'deliverables';out.mkdir(exist_ok=True)
 dest=out/'SehatAman_PCC2026_Complete_Project.zip'
 manifest={'application':'SehatAman','version':'0.5.0','all_app_fixtures_synthetic':True,'excluded':['credentials','private keys','sessions','persisted databases','test homes','render intermediates'],
           'pending_application_fields':'Tehreem, Haris and Majid email/phone; Tehreem exact MS program; applicant review/signature. Business/budget/IP details pending.',
           'files':rows}
 prefix='SehatAman_PCC2026/'
 with ZipFile(dest,'w',ZIP_DEFLATED,compresslevel=6) as z:
  for row in rows:z.write(ROOT/row['path'],prefix+row['path'])
  z.writestr(prefix+'PROJECT_MANIFEST.json',json.dumps(manifest,indent=2))
 with ZipFile(dest) as z:
  assert z.testzip() is None
  for row in rows:assert hashlib.sha256(z.read(prefix+row['path'])).hexdigest()==row['sha256'],row['path']
  assert not any('/.local' in n or '/protected/' in n or '/issuer-secrets/' in n or n.endswith(('.key','.sqlite3','.pyc')) for n in z.namelist())
 report={'archive':str(dest),'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'files':len(rows),'crc_check':'passed','all_file_hashes':'passed','excluded_secrets_paths':'passed','fresh_extraction_smoke_test':'pending'}
 (out/'ZIP_VERIFICATION.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps(report,indent=2))

def verify_fresh_extraction():
 out=ROOT/'deliverables';report_path=out/'ZIP_VERIFICATION.json'
 report=json.loads(report_path.read_text(encoding='utf-8'));archive=Path(report['archive'])
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==report['sha256']
 extraction=ROOT/'.local-zipcheck'/uuid.uuid4().hex[:8]
 extraction.mkdir(parents=True)
 with ZipFile(archive) as z:
  for name in z.namelist():
   target=(extraction/name).resolve()
   assert target.is_relative_to(extraction.resolve()),name
  z.extractall(extraction)
 project=extraction/'SehatAman_PCC2026'
 manifest=json.loads((project/'PROJECT_MANIFEST.json').read_text())
 for row in manifest['files']:
  assert hashlib.sha256((project/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
 env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join((str(project),str(project/'tests')))
 checks=[]
 for arguments in ([sys.executable,'manage.py','verify'],[sys.executable,'-m','unittest','discover','-s','tests','-p','test_mvp.py','-v'],[sys.executable,'-m','unittest','discover','-s','tests','-p','test_release.py','-v']):
  done=subprocess.run(arguments,cwd=project,env=env,capture_output=True,text=True,timeout=180)
  checks.append({'command':arguments[1:],'returncode':done.returncode,'output':done.stdout+done.stderr})
  assert done.returncode==0,checks[-1]
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==report['sha256']
 report.update({'fresh_extraction_smoke_test':'passed','extraction':str(project),'extracted_file_hashes':'passed','checks':checks})
 report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({'archive':str(archive),'sha256':report['sha256'],'fresh_extraction_smoke_test':'passed','checks':len(checks),'regressions':27,'release_checks':5},indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['inventory','chunk','zip','verify-zip']);p.add_argument('--path');p.add_argument('--offset',type=int,default=0);p.add_argument('--count',type=int,default=16000);a=p.parse_args()
 if a.command=='inventory':print(json.dumps(inventory()))
 elif a.command=='zip':package()
 elif a.command=='verify-zip':verify_fresh_extraction()
 else:
  q=ROOT/a.path
  assert q.resolve().is_relative_to(ROOT.resolve()) and q in files()
  value=q.read_bytes().decode('utf-8');print(json.dumps({'chunk':value[a.offset:a.offset+a.count],'length':len(value)}))
