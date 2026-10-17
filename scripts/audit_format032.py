"""Independent property audit; no provider requests."""
import argparse,json
from pathlib import Path
from articleflow.format032 import audit
from articleflow.docx_engine import dump
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=audit(a.source,a.target);dump(a.output,r);print(json.dumps(r))
