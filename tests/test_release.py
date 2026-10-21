"""Release checks for public synthetic media, the Word form and package inputs."""
import hashlib
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
import uuid
from zipfile import ZipFile
from xml.etree import ElementTree as E
from sehataman.bootstrap import bootstrap
from sehataman.server import LocalServer

ROOT=Path(__file__).resolve().parents[1]

class ReleaseChecks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.home=ROOT/'.local/release-smoke'/uuid.uuid4().hex
  cls.server=LocalServer(bootstrap(cls.home),0)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=3)
 def request(self,path,method='GET'):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);c.request(method,path)
  r=c.getresponse();answer=r.status,dict(r.getheaders()),r.read();c.close();return answer
 def test_reviewer_guide_and_frontend_are_available(self):
  for path in ('/','/app.js','/style.css','/brand.svg','/reviewer'):
   status,headers,body=self.request(path);self.assertEqual(status,200);self.assertTrue(body)
   self.assertIn('no-store',headers['Cache-Control']);self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
   self.assertIn("media-src 'self'",headers['Content-Security-Policy'])
   self.assertIn("default-src 'none'",headers['Content-Security-Policy'])
  body=self.request('/reviewer')[2].decode()
  self.assertNotIn(' style=',body);self.assertNotIn('<script',body)
 def test_recordings_match_manifest_and_served_bytes(self):
  manifest=json.loads((ROOT/'demos/recording_manifest.json').read_text())
  self.assertTrue(manifest['all_synthetic'])
  self.assertEqual(len(manifest['files']),5)
  for row in manifest['files']:
   status,headers,body=self.request('/demos/'+row['file'])
   self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'video/mp4')
   self.assertEqual(hashlib.sha256(body).hexdigest(),row['sha256'])
   status,headers,body=self.request('/demos/'+row['file'],'HEAD')
   self.assertEqual(status,200);self.assertEqual(body,b'');self.assertEqual(int(headers['Content-Length']),row['bytes'])
 def test_no_private_file_or_unlisted_media_route(self):
  for path in ('/.local/protected/keys.json','/demos/../../.local/protected/keys.json','/demos/unknown.mp4','/docs/SehatAman_PCC26_Concept_Note.docx','/demos/patient-sharing.mp4?download=1'):
   self.assertEqual(self.request(path)[0],404)
 def test_word_answers_and_source_fidelity(self):
  source=ROOT/'docs/PCC26_Concept_Note_Template.docx';final=ROOT/'docs/SehatAman_PCC26_Concept_Note.docx'
  with ZipFile(source) as a,ZipFile(final) as b:
   self.assertEqual(a.namelist(),b.namelist());self.assertEqual(set(n for n in a.namelist() if a.read(n)!=b.read(n)),{'word/document.xml','word/_rels/document.xml.rels'})
   original=E.fromstring(a.read('word/_rels/document.xml.rels'));updated=E.fromstring(b.read('word/_rels/document.xml.rels'))
   by_id={r.get('Id'):r for r in updated}
   for r in original:self.assertEqual(r.attrib,by_id[r.get('Id')].attrib)
   links=[r for r in updated if r.get('Type','').endswith('/hyperlink')]
   self.assertGreaterEqual(len(links),9)
   for r in links:
    self.assertEqual(r.get('TargetMode'),'External')
    self.assertTrue(r.get('Target','').startswith(('https://github.com/javed110/sehataman-pcc-2026-reviewer','https://pmdc.pk/')))
   root=E.fromstring(b.read('word/document.xml'));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
   tables=root.find('w:body',ns).findall('w:tbl',ns)
   self.assertEqual(len(tables),12)
   text=' '.join(root.itertext())
   for name in ('Tehreem Hamid','Muhammad Haris','Muhammad Majid','Humaira Zubair','Dr. Javed Ashraf','Dr. Hira Anwar'):
    self.assertIn(name,text)
   self.assertIn('668 ms',text);self.assertNotIn('1232.6',text)
   self.assertIn('To be provided',text)
   self.assertEqual(E.tostring(tables[11].find('w:tr',ns).find('w:tc',ns).find('w:p',ns)),E.tostring(E.fromstring(a.read('word/document.xml')).find('w:body',ns).findall('w:tbl',ns)[11].find('w:tr',ns).find('w:tc',ns).find('w:p',ns)))
 def test_frozen_manifest_unchanged(self):
  freeze=json.loads((ROOT/'planning/step4_manifest_freeze.json').read_text())
  self.assertEqual(hashlib.sha256((ROOT/'planning/step4_frozen_scenario_manifest.json').read_bytes()).hexdigest(),freeze['digest'])

if __name__=='__main__':unittest.main(verbosity=2)
