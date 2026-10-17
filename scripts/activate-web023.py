"""Root-only activation of an already prepared 023 release, with private rollback snapshot.
Inspect the current proxy and service first; never run on an unrelated server.
"""
import os,sys,json,subprocess,tarfile,hashlib,io,time,sqlite3,urllib.request
from pathlib import Path
release=Path(sys.argv[1]).resolve();commit=sys.argv[2]
assert release.is_dir() and (release/'RELEASE_COMMIT').read_text()==commit
root=Path('/var/lib/articleflow');current=Path('/opt/articleflow/current');previous=current.resolve()
config=Path('/etc/caddy/Caddyfile');proxy_before=hashlib.sha256(config.read_bytes()).hexdigest()
con=sqlite3.connect(root/'articleflow.sqlite3')
assert not con.execute("select count(*) from jobs where status in ('queued','processing')").fetchone()[0]
oldjobs=con.execute('select count(*) from jobs').fetchone()[0];con.close()
ledger=root/'config019/ledger.json';ledger_before=hashlib.sha256(ledger.read_bytes()).hexdigest()
archive=Path('/root/articleflow-pre023-'+commit[:8]+'.tar.gz');assert not archive.exists()
subprocess.run(['systemctl','stop','articleflow'],check=True)
try:
 files=[p for p in root.rglob('*') if p.is_file() and p.name not in {'key.env','csrf-token'}]
 manifest=[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
 with tarfile.open(archive,'w:gz') as tar:
  for p in files:tar.add(p,arcname=str(p.relative_to(root)),recursive=False)
  data=json.dumps(manifest).encode();info=tarfile.TarInfo('MANIFEST-023.json');info.size=len(data);info.mode=0o600;tar.addfile(info,io.BytesIO(data))
 os.chmod(archive,0o600)
 with tarfile.open(archive) as tar:
  for item in manifest:assert hashlib.sha256(tar.extractfile(item['path']).read()).hexdigest()==item['sha256']
 temp=current.with_name('current-023-'+commit[:8]);assert not temp.exists();temp.symlink_to(release);temp.replace(current)
 drop=Path('/etc/systemd/system/articleflow.service.d/release023.conf');assert not drop.exists();drop.write_text('[Service]\nEnvironment=ARTICLEFLOW_RELEASE='+commit+'\n')
 subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','start','articleflow'],check=True)
 ok=False
 for _ in range(30):
  try:
   data=json.load(urllib.request.urlopen('http://127.0.0.1:8769/healthz',timeout=2))
   if data.get('release')==commit and data.get('web_version')=='023':ok=True;break
  except Exception:pass
  time.sleep(1)
 assert ok,'health failed'
 assert hashlib.sha256(config.read_bytes()).hexdigest()==proxy_before
 assert hashlib.sha256(ledger.read_bytes()).hexdigest()==ledger_before
 con=sqlite3.connect(root/'articleflow.sqlite3');assert con.execute('pragma integrity_check').fetchone()[0]=='ok'
 assert con.execute('select count(*) from jobs').fetchone()[0]==oldjobs
 result={'release':str(release),'commit':commit,'previous':str(previous),'snapshot_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'snapshot':str(archive),'snapshot_files':len(files),'old_jobs_preserved':oldjobs,'sqlite_integrity':'ok','caddy_unchanged':True,'ledger_unchanged':True,'health':data}
 Path('/root/articleflow-023-activation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
except Exception:
 rollback=current.with_name('rollback-023-'+commit[:8]);rollback.symlink_to(previous);rollback.replace(current)
 drop=Path('/etc/systemd/system/articleflow.service.d/release023.conf')
 if drop.exists():drop.rename(drop.with_suffix('.failed'))
 subprocess.run(['systemctl','daemon-reload']);subprocess.run(['systemctl','restart','articleflow'])
 raise
