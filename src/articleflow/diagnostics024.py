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


def evidence(conflicts, samples, limit=50):
    """Private run diagnostics only; never include source excerpts in runtime rules."""
    documents = [{b['id']: (i, b) for i, b in enumerate(s['content']['blocks'], 1)}
                 for s in samples]
    groups = []
    for conflict in conflicts[:limit]:
        locations = []
        seen = set()
        for example in conflict.get('examples', []):
            document = example.get('document')
            if not isinstance(document, int) or not 1 <= document <= len(documents):
                continue
            found = documents[document - 1].get(example['id'])
            if found is None:
                continue
            variant = str(sorted(example['set'].items()))
            if variant in seen:
                continue
            seen.add(variant)
            ordinal, block = found
            span = example.get('range')
            text = block['text']
            excerpt = text[span[0]:span[1]] if span else text
            locations.append({'document': document, 'block_id': block['id'],
                              'paragraph': ordinal, 'range': span,
                              'excerpt': excerpt[:240], 'target': example['set']})
        groups.append({'kind': conflict['kind'], 'when': conflict.get('when', {}),
                       'differing_properties': conflict.get('differing_properties', []),
                       'locations': locations, 'requires_clarification': True,
                       'variants': conflict.get('variants'),
                       'location_complete': bool(locations) and len(locations) == conflict.get('variants')})
    return {'groups': groups, 'total': len(conflicts), 'truncated': len(conflicts) > limit,
            'policy': 'preserve_exact_differences'}


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
