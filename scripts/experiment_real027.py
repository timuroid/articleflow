"""Frozen real-DOCX reconstruction benchmark. Paid calls only with --live.

Third-party documents and raw responses stay in the ignored output directory.
No source repair, model retries, oracle assignments or production code edits.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from decimal import Decimal
from articleflow.agent023 import run, apply
from articleflow.docx_engine import NS, DocumentError, dump, load_package, parse_xml, xml_bytes, write_package
from articleflow.roundtrip022 import neutralize
from articleflow.research import render_pdf, compare_pixels
from articleflow import typography019 as t
from articleflow.stories026 import roots

FROZEN = '6f562abd94c2b59e07a17ec3054913a94e10a8b0'
ROOT = Path(__file__).resolve().parents[1]


def verify_frozen():
    paths = subprocess.check_output(['git','ls-tree','-r','--name-only',FROZEN,'src/articleflow'],cwd=ROOT,text=True).splitlines()
    for name in paths:
        expected=subprocess.check_output(['git','show',f'{FROZEN}:{name}'],cwd=ROOT)
        if (ROOT/name).read_bytes()!=expected:raise ValueError('FROZEN_IMPLEMENTATION_CHANGED')
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}


def content_signature(path):
    """Independent corruption guard: ordered text/field/object events and payload bytes."""
    parts=load_package(path);events={}
    for name in sorted(parts):
        if name=='word/document.xml' or name.startswith(('word/header','word/footer')) and name.endswith('.xml'):
            root=parse_xml(parts[name]); rows=[]
            for node in root.iter():
                local=node.tag.rsplit('}',1)[-1]
                if local=='tab' and node.getparent().tag!=t.tag('r'):continue
                if local in {'t','instrText','tab','br','cr','noBreakHyphen','softHyphen','fldChar','fldSimple','blip','imagedata','OLEObject'}:
                    rows.append((node.tag,node.text or '',sorted(node.attrib.items())))
            events[name]=rows
    payload={name:hashlib.sha256(data).hexdigest() for name,data in parts.items() if name.startswith(('word/media/','word/embeddings/'))}
    return {'events':events,'payloads':payload}


def restyle(source,target):
    """Second appearance, same neutralized content; no oracle roles."""
    parts=load_package(source)
    for name,root in roots(parts):
        for i,p in enumerate(root.findall('.//w:p',NS)):
            pp=p.find('w:pPr',NS)
            if pp is None:pp=t.prop('pPr');p.insert(0,pp)
            for local in ('spacing','ind','jc'):
                for old in list(pp.findall('w:'+local,NS)):pp.remove(old)
            pp.extend([t.prop('spacing',before=160,after=200,line=360,lineRule='auto'),t.prop('ind',left=360,firstLine=180),t.prop('jc',val='left')])
            for r in p.findall('.//w:r',NS):
                rp=r.find('w:rPr',NS)
                if rp is None:rp=t.prop('rPr');r.insert(0,rp)
                for local in ('rFonts','sz','szCs','color'):
                    for old in list(rp.findall('w:'+local,NS)):rp.remove(old)
                rp.extend([t.prop('rFonts',ascii='Arial',hAnsi='Arial'),t.prop('sz',val=28),t.prop('szCs',val=28),t.prop('color',val='7030A0')])
        if name=='word/document.xml':
            full=parse_xml(parts[name]);full.replace(full.find('w:body',NS),root);parts[name]=xml_bytes(full)
        else:parts[name]=xml_bytes(root)
    write_package(target,parts)


def compact_pixels(p):
    return {k:p[k] for k in ('golden_pages','candidate_pages','pixel_exact','differing_pixel_ratio','page_sizes_equal','matched_page_diagnostics')}


def evaluate(args):
    hashes=verify_frozen()
    protocol=json.loads((ROOT/'datasets/real-v027/protocol.json').read_text())
    sources=json.loads(args.sources.read_text())['documents']
    selected=[r for r in sources if r['status']=='downloaded']
    args.output.mkdir(parents=True,exist_ok=False)
    dump(args.output/'freeze.json',{'commit':FROZEN,'implementation':hashes,'protocol':protocol,'source_manifest_sha256':hashlib.sha256(args.sources.read_bytes()).hexdigest(),'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    summary={'series':'027','commit':FROZEN,'live':args.live,'documents':[],'task':'same_content_reconstruction','new_content_transfer':False}
    teacher={'model':protocol['teacher'],'reasoning_effort':'low'}
    student={'model':protocol['student'],'reasoning_effort':'none'}
    if args.live:
        if not args.key_file or not args.ledger:raise ValueError('LIVE_REQUIRES_EXISTING_KEY_AND_LEDGER')
        for config in (teacher,student):config.update(key_file=str(args.key_file.resolve()),ledger=str(args.ledger.resolve()),series='027')
    for source in selected:
        verify_frozen()
        sid=source['id'];incoming=args.inputs/(sid+'.docx');folder=args.output/sid;folder.mkdir()
        row={'id':sid,'sha256':source['sha256'],'variants':[]};summary['documents'].append(row)
        def save():dump(args.output/'summary.json',summary)
        save()
        try:
            if hashlib.sha256(incoming.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('SOURCE_HASH_CHANGED')
            golden=render_pdf(incoming,folder/'golden')
            import pymupdf
            with pymupdf.open(golden) as pdf:row['reference_pages']=len(pdf)
            neutral=folder/'neutralized.docx';neutralize(incoming,neutral)
            other=folder/'restyled.docx';restyle(neutral,other)
            variants=[('neutralized',neutral),('restyled',other)]
            for name,path in variants:
                same=content_signature(incoming)==content_signature(path)
                vr={'variant':name,'content_preserved_by_corruption':same,'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                row['variants'].append(vr)
                if not same:raise ValueError('CORRUPTION_CHANGED_CONTENT')
                vr['before']=compact_pixels(compare_pixels(golden,render_pdf(path,folder/(name+'-before'))));save()
            if not args.live:row['status']='prepared';save();continue
            report=run([incoming],folder/'learning',teacher,student,max_iterations=protocol['teacher_iterations'])
            row.update(status=report['status'],code=report.get('code'),last_stage=report.get('last_stage'))
            row['iterations']=[{'number':i['number'],'status':i['status'],'conflicting_groups':i.get('conflicting_groups'),
                'code':i.get('code'),'applications':[{'status':a['status'],'unresolved':len(a['unresolved']),
                'pixel_exact':a.get('pixels',{}).get('pixel_exact')} for a in i.get('applications',[])]} for i in report['iterations']]
            # An unverified package is not approved silently; keep both variants as blocked.
            for vr in row['variants']:vr['status']='blocked_template_not_verified'
            save()
            if report['status']=='reference_verified':
                for (name,path),vr in zip(variants,row['variants']):
                    try:
                        result=apply(path,Path(report['template']),folder/('application-'+name),student)
                        vr.update(status=result['status'],unresolved=len(result['unresolved']))
                        vr['integrity']={k:v for k,v in result.items() if k.endswith('_exact')}
                        if result.get('pdf'):vr['after']=compact_pixels(compare_pixels(golden,Path(result['pdf'])))
                    except DocumentError as e:vr.update(status='failed',code=str(e))
                    except Exception as e:vr.update(status='unavailable',error_type=type(e).__name__)
                    save()
        except DocumentError as e:row.update(status='failed',code=str(e))
        except Exception as e:row.update(status='unavailable',error_type=type(e).__name__)
        save();print(json.dumps({'id':sid,'status':row.get('status'),'code':row.get('code')},ensure_ascii=False),flush=True)
    metas=[json.loads(p.read_text()) for p in args.output.rglob('meta.json')]
    summary['api_attempts']=sum(m.get('api_attempts',0) for m in metas)
    summary['cost_usd']=str(sum((Decimal(m.get('cost_usd') or '0') for m in metas),Decimal(0)))
    summary['calls']=[{k:m[k] for k in ('model','status','cost_usd','api_attempts','seconds') if k in m} for m in metas]
    verify_frozen();save()
    print(json.dumps({'api_attempts':summary['api_attempts'],'cost_usd':summary['cost_usd']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('sources','inputs','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--key-file',type=Path);p.add_argument('--ledger',type=Path)
    evaluate(p.parse_args())
