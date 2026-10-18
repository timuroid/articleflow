"""Explicit Docker isolation probe; no model calls or real credentials."""
import argparse,json,tempfile
from pathlib import Path
from docx import Document
from articleflow.sandbox034 import snapshot,Engine
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',default='articleflow-repair034');a=p.parse_args()
with tempfile.TemporaryDirectory() as td:
    root=Path(td);secret=root/'host-only-sentinel';secret.write_text('synthetic sentinel, not a credential')
    engine=root/'engine';snapshot(engine);file=engine/'rules023.py'
    body='''def semantic_spans(source):
    import os
    result={'uid':os.getuid()}
    try:
        open(HOST_SENTINEL).read();result['host_file_readable']=True
    except OSError:result['host_file_readable']=False
    try:
        open('/engine/articleflow/injected.py','w').write('pass');result['code_writable']=True
    except OSError:result['code_writable']=False
    result['route_rows']=max(0,len(open('/proc/net/route').read().splitlines())-1)
    return result
'''.replace('HOST_SENTINEL',repr(str(secret)))
    s=file.read_text();start=s.index('def semantic_spans(source):');end=s.index('\ndef features(',start);file.write_text(s[:start]+body+s[end:])
    source=root/'source.docx';d=Document();d.add_paragraph('Synthetic');d.save(source)
    r=Engine(engine,a.image).invoke('semantics',{}, {'source.docx':source},root/'out')
    assert r=={'uid':65534,'host_file_readable':False,'code_writable':False,'route_rows':0},r
    print(json.dumps(r))
