"""Untrusted candidate process. Its reports are never quality certificates."""
import json,time
from pathlib import Path
from .docx_engine import dump,DocumentError

def main():
    task=json.loads(Path('/work/task.json').read_text());op=task['operation'];p=task['payload'];out=Path('/out')
    try:
        from . import agent023,rules023
        if op=='extract':value=agent023.extract_input(Path('/work/source.docx'),out/'extracted')
        elif op=='semantics':value=rules023.semantic_spans(Path('/work/source.docx'))
        elif op=='features':value=rules023.features(p['content'],p['assignments'])
        elif op=='build':
            samples=[{**s,'extracted':Path('/work/samples')/str(i)} for i,s in enumerate(p['samples'])]
            package,conflicts=agent023.build_package(
                samples,p['labels'],p['definitions'],out/'template',p.get('inline_roles'),
                span_grammar=p.get('span_grammar',False))
            value={'package':package,'conflicts':conflicts}
        elif op=='compile':
            from .leakage034 import compile_probe
            value=compile_probe(Path('/work/source.docx'),Path('/work/template'),
                                p['content'],p['semantics'],p['assignments'],p['marks'])
        elif op=='apply':
            # Rendering and quality assessment take place in the trusted supervisor.
            agent023.render_pdf=lambda *a:Path('/not-rendered')
            value=agent023.apply(Path('/work/source.docx'),Path('/work/template'),out/'application',{},caller=lambda *a,**kw:(p['response'],{'api_attempts':0}))
        elif op=='render':
            from .catalogue import render_catalogue
            render_catalogue(Path('/work/template'),Path('/work/samples'),p['plan'],out/'result.docx');value={}
        else:raise DocumentError('WORKER_OPERATION')
        dump(out/'worker.json',{'status':'ok','value':value})
    except Exception as exc:dump(out/'worker.json',{'status':'failed','code':str(exc)[:100] if isinstance(exc,DocumentError) else type(exc).__name__})
    (out/'_done').touch();time.sleep(600)

if __name__=='__main__':main()
