"""Read-only Word field controls. No external-data or executable field commands."""
from .docx_engine import NS,DocumentError
W=NS['w'];ALLOWED={'PAGE','NUMPAGES','PAGEREF','REF','TOC','TITLE'}

def validate_fields(root):
    stack=[]
    def validate(frame):
        instruction=''.join(frame['instruction']).strip()
        if not instruction or instruction.split()[0].upper() not in ALLOWED:raise DocumentError('FIELD_INSTRUCTION_UNSUPPORTED')
    for node in root.iter():
        if node.tag==f'{{{W}}}fldSimple':
            instruction=node.get(f'{{{W}}}instr','').strip()
            if not instruction or instruction.split()[0].upper() not in {'PAGE','NUMPAGES'}:raise DocumentError('FIELD_INSTRUCTION_UNSUPPORTED')
        elif node.tag==f'{{{W}}}fldChar':
            kind=node.get(f'{{{W}}}fldCharType')
            if kind=='begin':stack.append({'instruction':[],'result':False})
            elif kind=='separate':
                if not stack or stack[-1]['result']:raise DocumentError('FIELD_STRUCTURE_INVALID')
                validate(stack[-1]);stack[-1]['result']=True
            elif kind=='end':
                if not stack:raise DocumentError('FIELD_STRUCTURE_INVALID')
                validate(stack.pop())
            else:raise DocumentError('FIELD_STRUCTURE_INVALID')
        elif node.tag==f'{{{W}}}instrText':
            if not stack or stack[-1]['result']:raise DocumentError('FIELD_STRUCTURE_INVALID')
            stack[-1]['instruction'].append(node.text or '')
    if stack:raise DocumentError('FIELD_STRUCTURE_INVALID')
