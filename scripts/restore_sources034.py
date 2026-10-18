"""Restore a frozen owned-source snapshot into a NEW directory; never execute it."""
import argparse,gzip,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--experiment',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
r=json.loads(gzip.decompress(a.bundle.read_bytes()))
if r.get('schema')!='owned-source-snapshots-034':raise SystemExit('Unknown snapshot schema')
files=r['experiments'][a.experiment]
for name,h in files.items():
    if Path(name).name!=name or not name.endswith('.py') or hashlib.sha256(r['blobs'][h].encode()).hexdigest()!=h:raise SystemExit('Invalid source snapshot')
a.output.mkdir(parents=True,exist_ok=False)
for name,h in files.items():(a.output/name).write_text(r['blobs'][h])
print('Restored owned sources only; dependencies and private run evidence are separate.')
