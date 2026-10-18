"""Explicit PAID HTTPS end-to-end smoke on authored synthetic articles only."""
import argparse,hashlib,io,json,socket,ssl,time,zipfile
from pathlib import Path
import httpx
from articleflow.roundtrip022 import neutralize
from articleflow.docx_engine import load_package,parse_xml,xml_bytes,write_package,NS,dump
from articleflow.research import render_pdf
from articleflow.templateagent022 import compare_all

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--base',required=True);p.add_argument('--password-file',type=Path,required=True)
 p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--commit',required=True);p.add_argument('--allow-paid',action='store_true');a=p.parse_args()
 if not a.allow_paid:raise SystemExit('Explicit --allow-paid and an existing bounded server ledger are required')
 if not a.base.startswith('https://'):raise SystemExit('HTTPS required')
 a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
 c=httpx.Client(base_url=a.base,auth=('owner',a.password_file.read_text().strip()),timeout=300)
 assert httpx.get(a.base+'/healthz').status_code==401
 health=c.get('/healthz');health.raise_for_status();assert health.json()['release']==a.commit
 config=c.get('/api/v017/config').json();assert config['font_audit']['exact'] and config['llm_enabled']
 headers={'X-CSRF-Token':config['csrf_token']}
 def wait_run(rid):
  for _ in range(900):
   r=c.get('/api/v017/template-runs/'+rid);r.raise_for_status();data=r.json()
   if data['status'] not in ('queued','running'):return data
   time.sleep(1)
  raise RuntimeError('LEARNING_TIMEOUT')
 source=a.corpus/'article-1.docx'
 response=c.post('/api/v017/templates',headers=headers,data={'name':'Синтетический шаблон 023: серверная приёмка'},files={'files':(source.name,source.read_bytes())});response.raise_for_status();created=response.json();tid=created['id']
 wait_run(created['extraction_run_id'])
 response=c.post(f'/api/v017/templates/{tid}/learn',headers=headers,json={'consent_external':True,'iterations':2});response.raise_for_status();rid=response.json()['id']
 run=wait_run(rid);dump(a.output/'training.json',run)
 assert run['status']=='reference_verified',run['report'].get('code',run['status'])
 roles=run['report']['role_definitions'];keywords=[r for r in roles if 'keyword' in r]
 assert keywords,'KEYWORDS_ROLE_MISSING'
 # This synthetic smoke explicitly requires every semantic role present in its full sample.
 response=c.post(f'/api/v017/templates/{tid}/approve-agent',headers=headers,json={'run_id':rid,'answers':{r:True for r in roles}});response.raise_for_status()
 golden=a.corpus/'article-17.docx';neutralize(golden,a.output/'complete.docx')
 parts=load_package(a.output/'complete.docx');root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
 for n in list(body):
  if ''.join(n.itertext()).startswith('Ключевые слова:'):body.remove(n)
 parts['word/document.xml']=xml_bytes(root);write_package(a.output/'missing-keywords.docx',parts)
 response=c.post('/api/v017/batches',headers=headers,data={'template_id':tid,'use_llm':'true','consent_external':'true'},files=[('files',(name,(a.output/name).read_bytes())) for name in ('complete.docx','missing-keywords.docx')]);response.raise_for_status();batch=response.json();rows=[]
 for jid in batch['jobs']:
  for _ in range(600):
   job=c.get('/api/v017/jobs/'+jid).json()
   if job['status'] not in ('queued','processing'):break
   time.sleep(1)
  dump(a.output/(jid+'-job.json'),job)
  if job['source_name']=='complete.docx':
   assert job['status']=='ready',job['report'].get('questions')
   output=c.get(f'/api/v017/jobs/{jid}/files/final');output.raise_for_status();path=a.output/(jid+'.docx');path.write_bytes(output.content)
   pdf=c.get(f'/api/v017/jobs/{jid}/preview');pdf.raise_for_status();assert pdf.content.startswith(b'%PDF');pdfpath=a.output/(jid+'.pdf');pdfpath.write_bytes(pdf.content)
   pixels=compare_all(render_pdf(golden,a.output/'golden'),pdfpath,a.output/'diff');assert pixels['pixel_exact']
  else:
   assert job['status']=='draft',job['report'];assert set(keywords)&set(job['report']['missing'])
   assert c.get(f'/api/v017/jobs/{jid}/files/final').status_code==409
  assert c.patch(f'/api/v017/jobs/{jid}/decisions',headers=headers,json={'expected_revision':0,'assignments':{}}).status_code==409
  rows.append({'status':job['status'],'missing':job['report']['missing'],'source_name':job['source_name']})
 response=c.post(f'/api/v017/batches/{batch["id"]}/exports',headers=headers);response.raise_for_status()
 export=c.get(response.json()['url']);export.raise_for_status();(a.output/'batch.zip').write_bytes(export.content)
 with zipfile.ZipFile(io.BytesIO(export.content)) as z:
  assert z.testzip() is None;assert len([n for n in z.namelist() if n.startswith('results/')])==1
  manifest=json.loads(z.read('manifest.json'));assert sorted(j['status'] for j in manifest['jobs'])==['draft','ready']
 host=httpx.URL(a.base).host
 with socket.create_connection((host,443),timeout=10) as sock:
  with ssl.create_default_context().wrap_socket(sock,server_hostname=host) as tls:cert=tls.getpeercert();tls_version=tls.version()
 result={'health':health.json(),'http_without_auth':401,'http_with_auth':200,'tls':tls_version,'certificate_expires':cert['notAfter'],
         'fonts_exact':True,'learning_status':run['status'],'run_id':rid,'template_id':tid,'jobs':rows,
         'complete_pixels_exact':pixels['pixel_exact'],'complete_pages':pixels['golden_pages'],'zip_ready_files':1,'legacy_manual_edit_http':409}
 dump(a.output/'result.json',result);print(json.dumps(result))
