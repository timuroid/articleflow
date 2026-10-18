"""Archive only owned Python source snapshots, excluding documents, prompts and secrets."""
import argparse,gzip,json,re,hashlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
blobs={};runs={}
folders=list(a.artifacts.glob('repair034*/seed-engine'))+list(a.artifacts.glob('managed034*/seed'))
folders+=list(a.artifacts.glob('repair034*/repair/attempt-*/engine'))+list(a.artifacts.glob('managed034*/run/repair/attempt-*/engine'))
for folder in sorted(folders):
    files={}
    for path in sorted(folder.glob('*.py')):
        raw=path.read_bytes();text=raw.decode('utf-8')
        if re.search(r'sk-or-v1-[A-Za-z0-9]{20,}',text):raise SystemExit('Secret-shaped literal found; archive refused')
        h=hashlib.sha256(raw).hexdigest();blobs[h]=text;files[path.name]=h
    name=folder.parent.name if folder.name in {'seed','seed-engine'} else str(folder.relative_to(a.artifacts))
    runs[name]=files
payload={'schema':'owned-source-snapshots-034','encoding':'utf-8','experiments':runs,'blobs':blobs,'scope':'Owned .py source snapshots, including candidate code. No model prompts, document data, API logs or raw candidate response objects.'}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(gzip.compress(json.dumps(payload,ensure_ascii=False).encode(),mtime=0))
print(json.dumps({'experiments':len(runs),'unique_sources':len(blobs),'compressed_bytes':a.output.stat().st_size}))
