"""Observed role precedence, with explicit, conservative movement boundaries.

The package contains role pairs, never reference text or paragraph identities.
Only contiguous plain-text role groups can move. Tables, objects, markers,
numbering and repeated/interleaved roles are barriers, not silently detached.
"""
import copy
from collections import Counter
from .docx_engine import DocumentError, NS, load_package, parse_xml, write_package, xml_bytes


def fit(samples):
    sequences = []
    for content, assignments in samples:
        blocks = {b['id']: b for b in content['blocks']}
        sequence = []
        for node in content['structure']:
            if node['kind'] != 'paragraph':
                sequence.append(None)
                continue
            block = blocks[node['id']]
            if not block['text'] and not block['atoms']:
                continue
            role = assignments[node['id']]
            if not sequence or sequence[-1] != role:
                sequence.append(role)
        sequences.append(sequence)
    # A role that recurs in any reference cannot be globally sorted (e.g. headings).
    recurrent = {r for seq in sequences for r, n in Counter(seq).items() if n > 1}
    evidence = {}
    for seq in sequences:
        seq = [r for r in seq if r is not None and r not in recurrent]
        for i, before in enumerate(seq):
            for after in seq[i + 1:]:
                evidence[(before, after)] = evidence.get((before, after), 0) + 1
    conflicts = [{'kind': 'role_order', 'roles': [a, b]}
                 for a, b in sorted(evidence) if a < b and (b, a) in evidence]
    edges = [{'before': a, 'after': b, 'observations': count}
             for (a, b), count in sorted(evidence.items()) if (b, a) not in evidence]
    # Inconsistent partial observations may form a cycle without reverse pairs.
    graph = {}
    for edge in edges:
        graph.setdefault(edge['before'], set()).add(edge['after'])
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            return False
        if node in visited:
            return True
        visiting.add(node)
        if not all(visit(n) for n in graph.get(node, ())):
            return False
        visiting.remove(node); visited.add(node)
        return True
    if not all(visit(n) for n in list(graph)):
        conflicts.append({'kind': 'role_order_cycle'})
    return {'schema': 'role-order-024', 'edges': edges,
            'status': 'conflicting' if conflicts else 'observed',
            'mandatory_roles_inferred': False}, conflicts


def arrange(content, assignments, contract, source):
    """Return reordered content and an auditable top-level permutation.

When a required move crosses a protected boundary, return the original content
and an issue. A caller must not present it as a correctly ordered result.
"""
    original = list(content['structure'])
    identity = list(range(len(original)))
    if contract is None:  # Frozen 023 packages retain their original semantics.
        return content, identity, [], []
    if contract.get('schema') != 'role-order-024' or contract.get('status') != 'observed':
        return content, identity, [], [{'kind': 'structure', 'code': 'ORDER_CONTRACT_UNVERIFIED'}]
    roles = set(assignments.values())
    edges = []
    for edge in contract.get('edges', []):
        a, b = edge.get('before'), edge.get('after')
        if not isinstance(a, str) or not isinstance(b, str) or a == b:
            raise DocumentError('ORDER_RULE_INVALID')
        if a in roles and b in roles:
            edges.append((a, b))
    blocks = {b['id']: b for b in content['blocks']}
    # Numbering is source content with potentially order-dependent meaning.
    parts = load_package(source)
    body = parse_xml(parts['word/document.xml']).find('w:body', NS)
    nodes = [n for n in body if n.tag != '{%s}sectPr' % NS['w']]
    if len(nodes) != len(original):
        raise DocumentError('ORDER_SOURCE_ALIGNMENT')
    def movable_atom(atom):
        if atom['kind']=='text':return True
        if atom['kind']!='control':return False
        node=parse_xml(atom['xml'].encode())
        return node.tag=='{%s}sym'%NS['w'] or (node.tag=='{%s}br'%NS['w'] and node.get('{%s}type'%NS['w']) in {None,'textWrapping'} and node.get('{%s}clear'%NS['w']) in {None,'none'})
    def neighbour_binding(atom):
        if atom['kind']=='control':
            node=parse_xml(atom['xml'].encode())
            # A page break remains a barrier itself; it does not bind a caption
            # to the following paragraph. A plain line break binds nothing.
            if node.tag in {'{%s}br'%NS['w'],'{%s}sym'%NS['w']}:return False
        return atom['kind']!='text'
    def safe(index):
        node = original[index]
        if node['kind'] != 'paragraph':
            return False
        block = blocks[node['id']]
        # Preserve immediate neighbours of objects/tables as possible captions.
        for neighbour in (index-1,index+1):
            if not 0<=neighbour<len(original):continue
            nearby=original[neighbour]
            if nearby['kind']!='paragraph' or any(neighbour_binding(a) for a in blocks[nearby['id']]['atoms']):
                return False
        # Marker/hyperlink/object atoms stay fixed; no caption binding is invented.
        if not block['text'] or not all(movable_atom(a) for a in block['atoms']):
            return False
        xml = nodes[index]
        if xml.xpath('.//w:numPr | .//w:bookmarkStart | .//w:bookmarkEnd | .//w:fldChar | .//w:instrText | .//w:sectPr', namespaces=NS):
            return False
        # A style may carry inherited numbering. Conservatively block that style.
        style = xml.find('w:pPr/w:pStyle', NS)
        if style is not None and 'word/styles.xml' in parts:
            styles = parse_xml(parts['word/styles.xml'])
            by_id = {s.get('{%s}styleId' % NS['w']): s for s in styles.findall('w:style', NS)}
            sid = style.get('{%s}val' % NS['w']); seen = set()
            while sid in by_id and sid not in seen:
                seen.add(sid); s = by_id[sid]
                if s.find('w:pPr/w:numPr', NS) is not None:
                    return False
                parent = s.find('w:basedOn', NS)
                sid = parent.get('{%s}val' % NS['w']) if parent is not None else None
        return True
    labels = [assignments[n['id']] if n['kind'] == 'paragraph' else None for n in original]
    runs = []
    for i, role in enumerate(labels):
        if runs and runs[-1]['role'] == role and safe(i) and runs[-1]['safe']:
            runs[-1]['indices'].append(i)
        else:
            runs.append({'role': role, 'indices': [i], 'safe': safe(i)})
    counts = Counter(r['role'] for r in runs)
    for run in runs:
        run['safe'] = run['safe'] and counts[run['role']] == 1
    permutation = []
    start = 0
    while start < len(runs):
        if not runs[start]['safe']:
            permutation.extend(runs[start]['indices']); start += 1; continue
        end = start
        while end < len(runs) and runs[end]['safe']:
            end += 1
        pending = runs[start:end]
        ordered = []
        while pending:
            available = [r for r in pending if not any(b == r['role'] and any(x['role'] == a for x in pending) for a, b in edges)]
            if not available:
                return content, identity, [], [{'kind': 'structure', 'code': 'ORDER_CYCLE'}]
            chosen = available[0]  # Stable among unconstrained roles.
            ordered.extend(chosen['indices']); pending.remove(chosen)
        permutation.extend(ordered); start = end
    positions = {}
    for new, old in enumerate(permutation):
        if labels[old] is not None:
            positions.setdefault(labels[old], []).append(new)
    violations = [{'kind': 'structure', 'code': 'ORDER_PROTECTED_BOUNDARY', 'before': a, 'after': b}
                  for a, b in edges if a in positions and b in positions and max(positions[a]) > min(positions[b])]
    if violations:
        return content, identity, [], violations
    if sorted(permutation) != identity:
        raise DocumentError('ORDER_NOT_PERMUTATION')
    result = copy.deepcopy(content)
    result['structure'] = [original[i] for i in permutation]
    moves = [{'block_id': original[old]['id'], 'role': labels[old], 'from': old, 'to': new}
             for new, old in enumerate(permutation) if new != old]
    return result, permutation, moves, []


def expected_source(source, permutation, destination):
    """Materialize only the authorized permutation; never alter payload/properties."""
    parts = load_package(source)
    root = parse_xml(parts['word/document.xml']); body = root.find('w:body', NS)
    nodes = [n for n in body if n.tag != '{%s}sectPr' % NS['w']]
    if sorted(permutation) != list(range(len(nodes))):
        raise DocumentError('ORDER_NOT_PERMUTATION')
    for n in nodes:
        body.remove(n)
    for i, old in enumerate(permutation):
        body.insert(i, nodes[old])
    parts['word/document.xml'] = xml_bytes(root)
    write_package(destination, parts)
    return destination
