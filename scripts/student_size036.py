"""One-call, diagnostic-only comparison of a student model on a frozen template.

Example (all paths are supplied by the operator; raw data stays in artifacts/):

  PYTHONPATH=src .venv/bin/python scripts/student_size036.py \
    --reference-content artifacts/series/learning/reference-1/extracted/content/content.json \
    --teacher-response artifacts/series/learning/iteration-2/teacher/validated.json \
    --template artifacts/series/learning/iteration-2/template \
    --neutralized-docx artifacts/previous-diagnostic/neutralized.docx \
    --expected-input-content artifacts/previous-diagnostic/application/input-original.json \
    --model provider/model --key-file artifacts/private/key \
    --ledger artifacts/private/ledger.json --output artifacts/new-diagnostic

This script never assembles or visually certifies a DOCX. It sends exactly one
student request through provider023.call; that caller enforces the shared ledger.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from articleflow.agent023 import extract_input
from articleflow.docx_engine import DocumentError, digest, dump
from articleflow.inline026 import validate as validate_inline
from articleflow.provider023 import call
from articleflow.semantic023 import expand_groups, student_messages


def _content_key(block):
    return block['text'],[atom['kind'] for atom in block.get('atoms',[]) if atom['kind']!='text']


def align_expected(reference, incoming, teacher, *, include_inline=False):
    """Monotone 178→161 alignment: only empty layout paragraphs may disappear."""
    originals=reference['blocks'];new=incoming['blocks']
    prefixed=[{'id':'0:'+b['id'],'text':b['text']} for b in originals]
    teacher_labels=expand_groups(teacher,prefixed)
    expected={};original_for_new={};cursor=0;skipped=0
    for block in new:
        while cursor<len(originals) and _content_key(originals[cursor])!=_content_key(block):
            old=originals[cursor]
            if old['text'] or old.get('atoms'):
                raise DocumentError('EVALUATION_CONTENT_ALIGNMENT')
            cursor+=1;skipped+=1
        if cursor>=len(originals):raise DocumentError('EVALUATION_CONTENT_ALIGNMENT')
        expected[block['id']]=teacher_labels['0:'+originals[cursor]['id']]
        original_for_new[block['id']]=originals[cursor]['id']
        cursor+=1
    if any(b['text'] or b.get('atoms') for b in originals[cursor:]):
        raise DocumentError('EVALUATION_CONTENT_ALIGNMENT')
    skipped+=len(originals)-cursor
    if include_inline:
        annotations=validate_inline(teacher,originals)
        return expected,skipped,{b['id']:annotations[original_for_new[b['id']]] for b in new}
    return expected,skipped


def inline_diagnostics(response, blocks, definitions):
    """Count invalid rows independently; whole-list validation also catches overlap."""
    if not isinstance(response,dict):
        return {'rows':None,'invalid_rows':None,'validation_code':'STUDENT_SCHEMA'}
    if definitions and 'inline' not in response:
        return {'rows':None,'invalid_rows':None,'validation_code':'INLINE_RESPONSE_REQUIRED'}
    rows=response.get('inline',[])
    if not isinstance(rows,list):
        return {'rows':None,'invalid_rows':None,'validation_code':'INLINE_SCHEMA'}
    invalid=set();reasons=Counter();valid=[]
    for index,row in enumerate(rows):
        try:
            result=validate_inline({'inline':[row]},blocks,definitions)
            span=result[blocks[row['paragraph']-1]['id']][0]
            valid.append((row['paragraph'],span['start'],span['end'],index))
        except (DocumentError,KeyError,IndexError,TypeError) as exc:
            invalid.add(index)
            reasons[str(exc) if isinstance(exc,DocumentError) else 'INLINE_SCHEMA']+=1
    active=[]
    for paragraph,start,end,index in sorted(valid):
        active=[prior for prior in active if prior[0]==paragraph and prior[2]>start]
        for _,_,_,prior_index in active:
            invalid.update((prior_index,index))
            reasons['INLINE_OVERLAP']+=1
        active.append((paragraph,start,end,index))
    try:
        validate_inline(response,blocks,definitions)
        code=None
    except DocumentError as exc:code=str(exc)
    return {'rows':len(rows),'invalid_rows':len(invalid),
            'invalid_reason_counts':dict(sorted(reasons.items())),
            'validation_code':code}


def score_response(response, incoming, expected, package, expected_inline=None):
    """External semantic check; no layout inference or DOCX success claim."""
    blocks=incoming['blocks'];roles=package['roles'];inline_roles=package.get('inline_roles',{})
    try:
        predicted=expand_groups(response,blocks,roles)
        group_code=None
        correct=sum(predicted[b['id']]==expected[b['id']] for b in blocks)
        agreement={'correct':correct,'total':len(blocks),
                   'accuracy':round(correct/len(blocks),6) if blocks else None}
    except (DocumentError,KeyError,TypeError) as exc:
        group_code=str(exc) if isinstance(exc,DocumentError) else 'STUDENT_SCHEMA'
        agreement={'correct':None,'total':len(blocks),'accuracy':None}
    inline=inline_diagnostics(response,blocks,inline_roles)
    if expected_inline is not None:
        def canonical(spans):
            return {(bid,span['start'],span['end'],span['role'])
                    for bid,items in spans.items() for span in items}
        required=canonical(expected_inline)
        if inline['validation_code'] is None:
            actual=canonical(validate_inline(response,blocks,inline_roles))
            matched=len(required & actual)
            inline['teacher_exact_span_agreement']={
                'matched':matched,'expected':len(required),'predicted':len(actual),
                'precision':round(matched/len(actual),6) if actual else (1.0 if not required else 0.0),
                'recall':round(matched/len(required),6) if required else 1.0}
        else:
            inline['teacher_exact_span_agreement']={
                'matched':None,'expected':len(required),'predicted':None,
                'precision':None,'recall':None}
    return {'role_agreement_with_teacher':agreement,
            'group_validation_code':group_code,'inline':inline,
            'student_response_structurally_valid':group_code is None and inline['validation_code'] is None}


def compact_student_messages(standard):
    """Re-encode diagnostic paragraph maps without deleting any input field.

    Output labels keep the same schema. Only the user payload representation
    changes; production ``semantic023.student_messages`` stays untouched.
    """
    payload=json.loads(standard[1]['content'])
    rows=payload['paragraphs']
    fields=list(rows[0]) if rows else []
    if any(set(row)!=set(fields) for row in rows):
        raise DocumentError('COMPACT_ROWS_SCHEMA')
    constant_fields={key:rows[0][key] for key in fields
                     if key not in ('n','text') and all(row[key]==rows[0][key] for row in rows)}
    columns=[key for key in fields if key not in constant_fields]
    compact={'schema':'paragraph-columns-v1','roles':payload['roles'],
             'inline_roles':payload['inline_roles'],'columns':columns,
             'constants':constant_fields,
             'paragraphs':[[row[key] for key in columns] for row in rows]}
    instruction=(' Input schema paragraph-columns-v1: each paragraphs array is one paragraph; '
                 'columns gives its positional field names; constants are fields shared by EVERY paragraph. '
                 'Reconstruct every paragraph, including empty ones, before assigning roles. '
                 'The output JSON format remains unchanged.')
    return [{'role':standard[0]['role'],'content':standard[0]['content']+instruction},
            {'role':standard[1]['role'],'content':json.dumps(compact,ensure_ascii=False,separators=(',',':'))}]


def expand_compact_payload(payload):
    """Offline proof helper: recover the exact standard user JSON structure."""
    if payload.get('schema')!='paragraph-columns-v1':raise DocumentError('COMPACT_ROWS_SCHEMA')
    columns=payload['columns'];constants=payload['constants']
    if len(columns)!=len(set(columns)) or set(columns)&set(constants):
        raise DocumentError('COMPACT_ROWS_SCHEMA')
    rows=[]
    for values in payload['paragraphs']:
        if len(values)!=len(columns):raise DocumentError('COMPACT_ROWS_SCHEMA')
        rows.append({**dict(zip(columns,values)),**constants})
    return {'roles':payload['roles'],'inline_roles':payload['inline_roles'],'paragraphs':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('reference-content','teacher-response','template','neutralized-docx',
                 'key-file','ledger','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--expected-input-content',type=Path,
                        help='Previously extracted neutralized content; fail if the new extraction differs')
    parser.add_argument('--model',required=True)
    parser.add_argument('--max-tokens',type=int,default=8192)
    parser.add_argument('--reasoning-effort',default='none',
                        choices=('none','minimal','low','medium','high','xhigh'),
                        help='OpenRouter reasoning effort for this single student request')
    parser.add_argument('--compact',action='store_true',
                        help='Diagnostic-only invertible column/row prompt; production prompt is unchanged')
    parser.add_argument('--series',default='036-student-size-diagnostic')
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    artifact_root=(repo/'artifacts').resolve()
    output=args.output.resolve()
    if not output.is_relative_to(artifact_root) or output==artifact_root:
        parser.error('--output must be a new directory under ignored artifacts/')
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    output.chmod(0o700)
    reference=json.loads(args.reference_content.read_text())
    teacher=json.loads(args.teacher_response.read_text())
    package=json.loads((args.template/'semantic.json').read_text())
    if package['roles']!=teacher['roles'] or package.get('inline_roles',{})!=teacher.get('inline_roles',{}):
        raise DocumentError('FROZEN_TEACHER_TEMPLATE_MISMATCH')
    incoming=extract_input(args.neutralized_docx,output/'input')
    if args.expected_input_content:
        old=json.loads(args.expected_input_content.read_text())
        if old['blocks']!=incoming['blocks'] or old['structure']!=incoming['structure']:
            raise DocumentError('FROZEN_NEUTRAL_INPUT_CHANGED')
    expected,skipped,expected_inline=align_expected(reference,incoming,teacher,include_inline=True)
    aligned_inline_roles=Counter(span['role'] for spans in expected_inline.values() for span in spans)
    teacher_inline_obligations={
        'reference_rows':len(teacher.get('inline',[])),
        'aligned_rows':sum(aligned_inline_roles.values()),
        'defined_roles':len(package.get('inline_roles',{})),
        'aligned_rows_by_role':dict(sorted(aligned_inline_roles.items()))}
    standard_messages=student_messages(package['roles'],incoming,package.get('inline_roles'))
    messages=compact_student_messages(standard_messages) if args.compact else standard_messages
    def prompt_bytes(value):
        return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())
    baseline_prompt_bytes=prompt_bytes(standard_messages)
    selected_prompt_bytes=prompt_bytes(messages)
    prompt_sha256=digest(json.dumps(messages,sort_keys=True,ensure_ascii=False).encode())
    codefiles=['semantic023.py','rules023.py','inline026.py','provider023.py']
    protocol={'schema':'student-size-diagnostic-036','model':args.model,
              'teacher_sha256':digest(args.teacher_response.read_bytes()),
              'template_sha256':{name:digest((args.template/name).read_bytes())
                                 for name in ('semantic.json','rules.json','resources.zip')},
              'neutralized_sha256':digest(args.neutralized_docx.read_bytes()),
              'reference_content_sha256':digest(args.reference_content.read_bytes()),
              'reference_blocks':len(reference['blocks']),'incoming_blocks':len(incoming['blocks']),
              'removed_empty_layout_blocks':skipped,
              'teacher_inline_obligations':teacher_inline_obligations,
              'source_code_sha256':{name:digest((repo/'src/articleflow'/name).read_bytes()) for name in codefiles},
              'diagnostic_code_sha256':digest(Path(__file__).read_bytes()),
              'student_messages_sha256':prompt_sha256,
              'prompt_format':'paragraph-columns-v1' if args.compact else 'standard',
              'baseline_prompt_utf8_bytes':baseline_prompt_bytes,
              'selected_prompt_utf8_bytes':selected_prompt_bytes,
              'max_tokens':args.max_tokens,'reasoning_effort':args.reasoning_effort,
              'template_training_conflicts':package.get('unresolved_training_groups'),
              'mode':'one student call; diagnostic only; no DOCX construction or pixel claim'}
    dump(output/'protocol.json',protocol)
    config={'model':args.model,'key_file':str(args.key_file.resolve()),
            'ledger':str(args.ledger.resolve()),'series':args.series,
            'reasoning_effort':args.reasoning_effort}
    started=time.monotonic();response=None;error=None;meta={}
    try:
        response,meta=call(config,messages,output/'student',max_tokens=args.max_tokens)
    except DocumentError as exc:
        error=str(exc)
        path=output/'student/meta.json'
        if path.exists():meta=json.loads(path.read_text())
    scored=score_response(response,incoming,expected,package,expected_inline) if response is not None else None
    summary={'schema':'student-size-diagnostic-036-summary','model':args.model,
             'reasoning_effort':args.reasoning_effort,
             'status':'diagnosed' if scored is not None else 'provider_or_json_failure',
             'error_code':error,'provider_status':meta.get('status','not_sent'),
             'http_status':meta.get('http_status'),'api_attempts':meta.get('api_attempts',0),
             'cost_usd':meta.get('cost_usd'),'reserve_usd':meta.get('reserve_usd'),
             'provider_seconds':meta.get('seconds'),
             'elapsed_seconds':round(time.monotonic()-started,3),
             'request_sha256':meta.get('request_sha256'),
             'student_messages_sha256':prompt_sha256,
             'prompt_format':protocol['prompt_format'],
             'baseline_prompt_utf8_bytes':baseline_prompt_bytes,
             'selected_prompt_utf8_bytes':selected_prompt_bytes,
             'reference_blocks':protocol['reference_blocks'],
             'incoming_blocks':protocol['incoming_blocks'],
             'removed_empty_layout_blocks':skipped,
             'teacher_inline_obligations':teacher_inline_obligations,
             'template_training_conflicts':protocol['template_training_conflicts'],
             'document_rendered':False,'pixel_exact':None,
             'certification':'not_evaluated_conflicting_template' if package.get('unresolved_training_groups')
                            else 'not_evaluated_diagnostic_only',
             'semantic_diagnostics':scored}
    dump(output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
