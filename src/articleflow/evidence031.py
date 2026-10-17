"""Lossless short style identifiers in teacher evidence; runtime IDs stay unchanged."""
import copy

STYLE_FIELDS={'style','paragraph_style','run_style','drawing_style'}

def prepare(observations,feedback=None):
    ids=sorted({key for catalogue in observations.get('catalogues',[]) for styles in catalogue.values() for key in styles})
    aliases={value:'s'+str(i+1) for i,value in enumerate(ids)}
    def convert(value,field=None):
        if isinstance(value,dict):return {aliases.get(k,k):convert(v,k) for k,v in value.items()}
        if isinstance(value,list):return [convert(v,'style' if field=='character_styles' else field) for v in value]
        return aliases.get(value,value) if field in STYLE_FIELDS and isinstance(value,str) else value
    result=convert(copy.deepcopy(observations));result['style_aliases']={alias:original for original,alias in aliases.items()}
    return result,convert(copy.deepcopy(feedback))


def restore(value,aliases,field=None):
    """Decode a saved teacher request before checking a same-protocol continuation."""
    if isinstance(value,dict):return {aliases.get(k,k):restore(v,aliases,k) for k,v in value.items()}
    if isinstance(value,list):return [restore(v,aliases,'style' if field=='character_styles' else field) for v in value]
    return aliases.get(value,value) if field in STYLE_FIELDS and isinstance(value,str) else value
