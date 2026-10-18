"""Trusted orchestration of an immutable, sandboxed candidate engine."""
import json,shutil,tempfile
from pathlib import Path
from .docx_engine import DocumentError,dump,digest,load_package,parse_xml,xml_bytes,write_package,NS
from .sandbox034 import ACTIVE,use


def extract(engine,source,folder):
    with tempfile.TemporaryDirectory() as td:
        job=Path(td)/'result';value=engine.invoke('extract',{}, {'source.docx':source},job)
        shutil.copytree(job/'extracted',folder)
        return value


def simple(engine,operation,payload,inputs):
    with tempfile.TemporaryDirectory() as td:return engine.invoke(operation,payload,inputs,Path(td)/'result')


def build(engine,samples,labels,definitions,destination,inline_roles):
    with tempfile.TemporaryDirectory() as td:
        base=Path(td);copies=base/'samples';copies.mkdir()
        for i,sample in enumerate(samples):shutil.copytree(sample['extracted'],copies/str(i))
        payload={'samples':[{k:s[k] for k in ('content','semantics')} for s in samples],'labels':labels,'definitions':definitions,'inline_roles':inline_roles}
        value=engine.invoke('build',payload,{'samples':copies},base/'result')
        shutil.copytree(base/'result/template',destination)
        return value['package'],value['conflicts']


def render(engine,template,content,plan,destination):
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)/'result';engine.invoke('render',{'plan':plan},{'template':template,'samples':content},base)
        shutil.copyfile(base/'result.docx',destination)


def apply(engine,source,template,folder,config,caller):
    from .agent023 import extract_input
    from .semantic023 import expand_groups,student_messages
    from .inline026 import validate as validate_inline
    original=source;package=json.loads((template/'semantic.json').read_text())
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)
        if package.get('import_policy')=='annotations-028':
            from .adapters028 import normalize
            source=base/'normalized.docx';normalize(original,source)
        content=extract(engine,source,base/'extracted')
        def validate(response):
            if package.get('inline_roles') and 'inline' not in response:raise DocumentError('INLINE_RESPONSE_REQUIRED')
            expand_groups(response,content['blocks'],package['roles']);validate_inline(response,content['blocks'],package.get('inline_roles',{}));return response
        # Credentials remain in this supervisor; the container gets only the response.
        response,meta=caller(config,student_messages(package['roles'],content,package.get('inline_roles')),folder/'student',validate=validate)
        validate(response)
        trial=engine.invoke('apply',{'response':response},{'source.docx':original,'template':template},base/'result')
        folder.mkdir(parents=True,exist_ok=True)
        shutil.copytree(base/'result/application',folder,dirs_exist_ok=True)
        trial['model']=meta;trial['engine_hashes']=engine.hashes;trial.pop('pdf',None)
        assignments=expand_groups(response,content['blocks'],package['roles']);trial['assignments']=assignments
        output=folder/'result.docx'
        if output.exists():
            # Independent authorization of movement and empty layout insertions.
            from .order024 import arrange,expected_source
            from .spacers023 import restore
            from .rules023 import semantic_spans
            from .integrity023 import check
            from .research import render_pdf
            with use(None):
                ordered,permutation,_,issues=arrange(content,assignments,package.get('order'),source)
                if issues or permutation!=trial.get('structure_permutation'):raise DocumentError('CANDIDATE_UNAUTHORIZED_ORDER')
                _,_,_,_,inserted=restore(ordered,assignments,semantic_spans(source),package,json.loads((template/'rules.json').read_text()))
                checked=output
                if inserted:
                    parts=load_package(output);root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
                    for i in sorted(inserted,reverse=True):
                        node=body[i]
                        if node.tag!='{%s}p'%NS['w'] or node.xpath('.//w:t | .//w:drawing | .//w:fldChar | .//w:br',namespaces=NS):raise DocumentError('CANDIDATE_NONEMPTY_SPACER')
                        body.remove(node)
                    parts['word/document.xml']=xml_bytes(root);checked=base/'checked.docx';write_package(checked,parts)
                expected=expected_source(source,permutation,base/'expected.docx');integrity=check(expected,checked)
                trial.update(integrity)
                trial['status']='rendered_unverified' if all(integrity.values()) else 'integrity_failed'
                if all(integrity.values()):trial['pdf']=str(render_pdf(output,folder/'render'))
        else:trial['status']='needs_review'
        dump(folder/'input-original.json',content);dump(folder/'result.json',trial)
        return trial
