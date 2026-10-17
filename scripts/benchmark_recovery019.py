"""Development regression after recovery; never imports gold into runtime."""
import argparse
import json
import sys
import time
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).parent))
import benchmark_web017 as old
from articleflow import typography019 as typo
from articleflow.structure017 import inventory, inspect_templates, compile_document, suggest_roles
from articleflow.research import render_pdf, compare_pixels, environment_manifest


def run(folder, render=True):
    folder.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((old.CORPUS/'manifest.json').read_text())
    for entry in manifest['entries']:
        if old.sha(old.CORPUS/entry['path']) != entry['sha256']:
            raise ValueError('CORPUS_HASH_MISMATCH')
    profiles = {}
    for family in manifest['styles']:
        spec = inspect_templates([old.CORPUS/e['path'] for e in manifest['entries'] if e['split']=='train' and e['style']==family])
        selected = {r: sorted(v, key=lambda k: (-len(v[k]), k))[0] for r,v in spec['variants'].items()}
        profiles[family] = {r:spec['styles'][r][k] for r,k in selected.items()}
        old.save(folder/(family+'-spec.json'),spec)
    rows=[]
    result={'series':'019','dataset':'synthetic-v1 development regression','model_calls':0,'rows':rows,
            'manifest_sha256':old.sha(old.CORPUS/'manifest.json'),
            'implementation_sha256':{p.name:old.sha(p) for p in (old.ROOT/'src/articleflow').glob('*.py')},
            'protocol_sha256':old.sha(old.ROOT/'docs/research/recovery-019-protocol.md')}
    for e in manifest['entries']:
        if e['kind'] not in ('source','missing_required'): continue
        src=old.CORPUS/e['path']; dst=folder/(e['id']+'.docx'); editorial=folder/(e['id']+'-editorial.docx')
        blocks=inventory(src)['blocks']; predicted,_=suggest_roles(blocks); gold=old.labels(e,blocks)
        start=time.perf_counter()
        report=compile_document(src,dst,styles=profiles[e['style']],editorial_output=editorial)
        row={'id':e['id'],**old.scores(gold,predicted),'seconds':time.perf_counter()-start,
             'status':report['status'], 'missing':report['missing'], 'legacy_018':old.conservation(src,dst,editorial)}
        output=old.body_nodes(dst)+(old.body_nodes(editorial) if editorial.exists() else [])
        output=[n for n in output if not ''.join(n.itertext()).startswith('[ЗАПОЛНИТЬ:')]
        row['scientific_payload_exact']=typo.scientific_signature(old.body_nodes(src))==typo.scientific_signature(output)
        if render and 'paired_reference' in e:
            a=render_pdf(old.CORPUS/e['paired_reference'],folder/e['id']/'golden')
            b=render_pdf(dst,folder/e['id']/'result')
            row['pixels']=compare_pixels(a,b)
        rows.append(row)
        old.save(folder/'results.json',result)
        print(json.dumps(row),flush=True)
    if render: result['render_environment']=environment_manifest()
    result['aggregate']={'roles_correct':sum(r['role_correct'] for r in rows),'roles_total':sum(r['role_total'] for r in rows),
        'documents_roles_exact':sum(r['roles_exact'] for r in rows),'scientific_payload_exact':sum(r['scientific_payload_exact'] for r in rows),
        'pixel_exact':sum(r.get('pixels',{}).get('pixel_exact',False) for r in rows)}
    old.save(folder/'results.json',result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--no-render',action='store_true');a=p.parse_args()
    run(a.output,not a.no_render)
