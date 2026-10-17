"""Describe property conflicts without copying document text into reports."""
from .docx_engine import parse_xml


def property_map(fragments):
    result = {}
    def walk(node, path):
        local = node.tag.rsplit('}', 1)[-1]
        here = path + '/' + local
        result[here] = True
        for key, value in sorted(node.attrib.items()):
            result[here + '/@' + key.rsplit('}', 1)[-1]] = value
        for index, child in enumerate(node):
            # Preserve occurrence order for potentially repeated property children.
            walk(child, here + '/' + str(index))
    for index, fragment in enumerate(fragments):
        walk(parse_xml(fragment.encode()), str(index))
    return result


def explain(conflicts, template):
    """Property names are evidence of ambiguity, never permission to drop them."""
    result = []
    for conflict in conflicts:
        row = dict(conflict)
        kind = conflict['kind']
        group = conflict.get('when', {}).get('kind') if kind == 'layout' else kind
        style_ids = {e['set'].get('style') for e in conflict.get('examples', [])}
        if group in template['styles'] and None not in style_ids:
            maps = [property_map(template['styles'][group][sid]) for sid in sorted(style_ids)]
            keys = set().union(*(m.keys() for m in maps)) if maps else set()
            missing = object()
            changed = sorted(k for k in keys if len({m.get(k, missing) for m in maps}) > 1)
            row['differing_properties'] = changed
            row['equivalence'] = 'not_established'
            row['diagnostic_complete'] = len(style_ids) == conflict.get('variants')
        result.append(row)
    return result
