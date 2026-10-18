"""External metamorphic gate for source-formatting leakage in repair candidates.

The teacher labels and inline annotations are frozen. Only the *incoming*
DOCX typography changes. The gate rejects newly unstable selectors, rule
decisions and actual compiler plans relative to the previous engine; it does
not forbid a semantic bold rule already present in that engine.
"""
import json
import copy
from collections import Counter
from pathlib import Path

from .docx_engine import DocumentError, NS, digest, load_package, parse_xml, write_package, xml_bytes
from .integrity023 import check
from .sandbox034 import use


def _set(parent, name, attributes):
    tag = '{%s}%s' % (NS['w'], name)
    node = parent.find('w:' + name, NS)
    if node is None:
        from lxml import etree
        node = etree.SubElement(parent, tag)
    node.attrib.clear()
    node.attrib.update({'{%s}%s' % (NS['w'], key): str(value) for key, value in attributes.items()})


def perturb(source, target, variant):
    """Corrupt only direct source typography, independently of expected style."""
    if variant not in (0, 1):
        raise DocumentError('TYPOGRAPHY_PROBE_VARIANT')
    parts = load_package(source)
    count = 0
    changed_parts = 0
    for name in sorted(parts):
        if name != 'word/document.xml' and not (name.startswith(('word/header', 'word/footer')) and name.endswith('.xml')):
            continue
        root = parse_xml(parts[name])
        for paragraph in root.findall('.//w:p', NS):
            ppr = paragraph.find('w:pPr', NS)
            if ppr is None:
                from lxml import etree
                ppr = etree.Element('{%s}pPr' % NS['w'])
                paragraph.insert(0, ppr)
            _set(ppr, 'spacing', {'before': 180 + variant * 240, 'after': 80 + variant * 160,
                                   'line': 240 + variant * 120, 'lineRule': 'auto'})
            _set(ppr, 'ind', {'left': 100 + variant * 300, 'right': 50 + variant * 100,
                               'firstLine': 80 + variant * 160})
            _set(ppr, 'jc', {'val': 'left' if variant else 'right'})
            for run in paragraph.xpath('.//w:r[not(ancestor::m:oMath)]', namespaces=NS):
                rpr = run.find('w:rPr', NS)
                if rpr is None:
                    from lxml import etree
                    rpr = etree.Element('{%s}rPr' % NS['w'])
                    run.insert(0, rpr)
                flip = (count + variant) % 2
                color = '137FAB' if flip else 'D04A21'
                _set(rpr, 'rFonts', {'ascii': 'Arial' if flip else 'Courier New',
                                     'hAnsi': 'Arial' if flip else 'Courier New',
                                     'eastAsia': 'Arial' if flip else 'Courier New',
                                     'cs': 'Arial' if flip else 'Courier New'})
                _set(rpr, 'sz', {'val': 17 if flip else 29})
                _set(rpr, 'szCs', {'val': 17 if flip else 29})
                _set(rpr, 'color', {'val': color})
                _set(rpr, 'shd', {'val': 'clear', 'color': 'auto', 'fill': color})
                _set(rpr, 'highlight', {'val': 'cyan' if flip else 'yellow'})
                for emphasis in ('b', 'bCs', 'i', 'iCs'):
                    _set(rpr, emphasis, {'val': flip})
                count += 1
        updated = xml_bytes(root)
        if updated != parts[name]:
            changed_parts += 1
        parts[name] = updated
    write_package(target, parts)
    if count == 0 or changed_parts == 0 or set(load_package(target)) != set(parts) or not all(check(source, target).values()):
        raise DocumentError('TYPOGRAPHY_PROBE_INTEGRITY')
    return count


def _rules(template):
    package = json.loads((Path(template) / 'semantic.json').read_text())
    return package['rules']


def _selectors(rules):
    result = {kind: set() for kind in ('paragraph', 'character', 'layout', 'drawing')}
    for rule in rules:
        result[rule['kind']].update(rule['when'])
    return result


def _observe(engine, source, extracted, assignments):
    from .agent023 import extract_input
    from .rules023 import features, semantic_spans
    with use(engine):
        content = extract_input(source, extracted)
        semantics = semantic_spans(source)
        structural = features(content, assignments)
    return content, semantics, structural


def _plan_fingerprint(plan):
    """Hash rendering decisions, not metadata or equal-style span boundaries."""
    canonical = {key: copy.deepcopy(plan[key])
                 for key in ('blocks', 'layout', 'objects', 'section_style')}
    for block in canonical['blocks']:
        merged = []
        for span in block['spans']:
            if merged and merged[-1]['end'] == span['start'] and merged[-1]['style'] == span['style']:
                merged[-1]['end'] = span['end']
            else:
                merged.append(span)
        block['spans'] = merged
    return digest(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode())


def compile_probe(source, template_dir, content, semantics, assignments, marks):
    """Run the real candidate compiler with frozen labels, without rendering.

    This function also runs inside worker034, where ``rules023``, ``order024``
    and the other editable modules come from the isolated candidate snapshot.
    Only a style-plan fingerprint leaves that worker.
    """
    from .inline026 import overlay
    from .order024 import arrange
    from .rules023 import compile_plan
    from .spacers023 import restore
    template_dir = Path(template_dir)
    package = json.loads((template_dir / 'semantic.json').read_text())
    template = json.loads((template_dir / 'rules.json').read_text())
    content = copy.deepcopy(content)
    semantics = copy.deepcopy(semantics)
    if package.get('inline_roles'):
        semantics = overlay(semantics, marks)
    content, _, _, order_issues = arrange(content, assignments, package.get('order'), source)
    content, runtime_assignments, semantics, forced, _ = restore(
        content, assignments, semantics, package, template)
    plan, unresolved = compile_plan(template, content, package,
                                    runtime_assignments, semantics, forced)
    unresolved.extend(order_issues)
    if plan is not None and not order_issues:
        fingerprint = _plan_fingerprint(plan)
        return {'status': 'planned', 'fingerprint': fingerprint}
    issues = sorted((str(issue.get('kind', '')), str(issue.get('id', '')),
                     str(issue.get('code', ''))) for issue in unresolved)
    return {'status': 'unresolved', 'issues': issues}


def _compile(engine, source, template, observation, assignments, marks, destination):
    content, semantics, _ = observation
    if engine is None:
        return compile_probe(source, template, content, semantics, assignments, marks)
    return engine.invoke('compile', {
        'content': content, 'semantics': semantics,
        'assignments': assignments, 'marks': marks},
        {'source.docx': source, 'template': template}, destination)


def _span_value(spans, offset, key):
    for span in spans:
        if span['start'] <= offset < span['end']:
            return span['features'].get(key)
    return None


def _instability(original, corrupted, selectors):
    a_content, a_semantics, a_features = original
    b_content, b_semantics, b_features = corrupted
    a_blocks = [(b['id'], b['text']) for b in a_content['blocks']]
    b_blocks = [(b['id'], b['text']) for b in b_content['blocks']]
    if a_blocks != b_blocks:
        raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')
    changed = Counter()
    examined = Counter()
    for kind in ('paragraph', 'layout', 'drawing'):
        if set(a_features[kind]) != set(b_features[kind]):
            raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')
        for item in a_features[kind]:
            for key in selectors[kind]:
                examined[(kind, key)] += 1
                if a_features[kind][item].get(key) != b_features[kind][item].get(key):
                    changed[(kind, key)] += 1
    if set(a_semantics) != set(b_semantics):
        raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')
    for block in a_content['blocks']:
        bid = block['id']
        for key in selectors['character']:
            if key in a_features['paragraph'][bid] or key in b_features['paragraph'][bid]:
                examined[('character', key)] += len(block['text'])
                if a_features['paragraph'][bid].get(key) != b_features['paragraph'][bid].get(key):
                    changed[('character', key)] += len(block['text'])
                continue
            for offset in range(len(block['text'])):
                examined[('character', key)] += 1
                if _span_value(a_semantics[bid], offset, key) != _span_value(b_semantics[bid], offset, key):
                    changed[('character', key)] += 1
    return changed, examined


def _decision(rules, kind, features):
    """Evaluate a frozen rule table without executing candidate Python."""
    matches = [rule for rule in rules if rule['kind'] == kind and
               all(features.get(key) == value for key, value in rule['when'].items())]
    if not matches:
        return ('no_rule',)
    specificity = max(len(rule['when']) for rule in matches)
    targets = {json.dumps(rule.get('set'), sort_keys=True, ensure_ascii=False)
               for rule in matches if len(rule['when']) == specificity}
    return ('style', next(iter(targets))) if len(targets) == 1 else ('conflict',)


def _features_at(spans, offset):
    for span in spans:
        if span['start'] <= offset < span['end']:
            return span['features']
    raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')


def _decision_instability(base_original, base_corrupted, base_rules,
                          candidate_original, candidate_corrupted, candidate_rules):
    """Reject newly unstable *style decisions*, even on an old selector key.

    A base rule can already mention ``bold``. Comparing selector-change counts
    alone then misses a candidate that starts using that same key to distinguish
    another role. Only decisions newly changed by input corruption count here.
    """
    observations = (base_original, base_corrupted, candidate_original, candidate_corrupted)
    blocks = [[(block['id'], block['text']) for block in item[0]['blocks']]
              for item in observations]
    if any(block != blocks[0] for block in blocks[1:]):
        raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')
    new_changes = Counter()
    examined = Counter()
    for kind in ('paragraph', 'layout', 'drawing'):
        feature_maps = [item[2][kind] for item in observations]
        if any(set(features) != set(feature_maps[0]) for features in feature_maps[1:]):
            raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')
        for identifier in feature_maps[0]:
            decisions = [_decision(base_rules if index < 2 else candidate_rules,
                                   kind, feature_maps[index][identifier])
                         for index in range(4)]
            examined[kind] += 1
            if decisions[2] != decisions[3] and decisions[0] == decisions[1]:
                new_changes[kind] += 1
    for block in observations[0][0]['blocks']:
        identifier, text = block['id'], block['text']
        semantics = [item[1][identifier] for item in observations]
        boundaries = {0, len(text)}
        for spans in semantics:
            for span in spans:
                boundaries.update((span['start'], span['end']))
        points = sorted(boundaries)
        if points[0] != 0 or points[-1] != len(text):
            raise DocumentError('TYPOGRAPHY_PROBE_ALIGNMENT')
        for start, end in zip(points, points[1:]):
            if start == end:
                continue
            decision = []
            for index, item in enumerate(observations):
                paragraph = item[2]['paragraph'][identifier]
                features = {**paragraph, 'script': paragraph['language'],
                            **_features_at(semantics[index], start)}
                decision.append(_decision(base_rules if index < 2 else candidate_rules,
                                          'character', features))
            examined['character'] += end - start
            if decision[2] != decision[3] and decision[0] == decision[1]:
                new_changes['character'] += end - start
    return new_changes, examined


def compare(base_engine, candidate_engine, training, base_template, candidate_template, folder):
    """Reject new source-typography dependence relative to the old engine.

    Labels and inline marks stay frozen. Text and style decisions are used
    locally for comparison; only aggregate counts leave this gate.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    if not 1 <= len(training['samples']) <= 10 or len(training['samples']) != len(training['labels']):
        raise DocumentError('TYPOGRAPHY_PROBE_LIMIT')
    rules = {'base': _rules(base_template), 'candidate': _rules(candidate_template)}
    engines = {'base': (base_engine, _selectors(rules['base'])),
               'candidate': (candidate_engine, _selectors(rules['candidate']))}
    changed = {'base': Counter(), 'candidate': Counter()}
    examined = {'base': Counter(), 'candidate': Counter()}
    unstable_decisions = Counter()
    examined_decisions = Counter()
    unstable_compilations = 0
    examined_compilations = 0
    for index, (sample, assignments) in enumerate(zip(training['samples'], training['labels'])):
        source = Path(sample['source'])
        marks = {identifier: [{'start': span['start'], 'end': span['end'],
                               'role': span['features']['inline_role']}
                              for span in spans if span['features'].get('inline_role', 'plain') != 'plain']
                 for identifier, spans in sample.get('semantics', {}).items()}
        corrupted = []
        for variant in (0, 1):
            target = folder / f'input-{index}-{variant}.docx'
            perturb(source, target, variant)
            corrupted.append(target)
        originals = {}
        trials = {}
        compiled = {}
        for label, (engine, selectors) in engines.items():
            original = _observe(engine, source, folder / label / f'original-{index}', assignments)
            originals[label] = original
            trials[label] = []
            compiled[label] = [_compile(engine, source, base_template if label == 'base' else candidate_template,
                                        original, assignments, marks,
                                        folder / label / f'compiled-original-{index}')]
            for variant, target in enumerate(corrupted):
                trial = _observe(engine, target, folder / label / f'corrupted-{index}-{variant}', assignments)
                trials[label].append(trial)
                compiled[label].append(_compile(engine, target,
                                                base_template if label == 'base' else candidate_template,
                                                trial, assignments, marks,
                                                folder / label / f'compiled-corrupted-{index}-{variant}'))
                delta, total = _instability(original, trial, selectors)
                changed[label].update(delta)
                examined[label].update(total)
        for variant in (0, 1):
            delta, total = _decision_instability(
                originals['base'], trials['base'][variant], rules['base'],
                originals['candidate'], trials['candidate'][variant], rules['candidate'])
            unstable_decisions.update(delta)
            examined_decisions.update(total)
            examined_compilations += 1
            if (compiled['candidate'][0] != compiled['candidate'][variant + 1] and
                    compiled['base'][0] == compiled['base'][variant + 1]):
                unstable_compilations += 1
    unstable = []
    for selector, candidate_count in sorted(changed['candidate'].items()):
        candidate_total = examined['candidate'][selector]
        base_count = changed['base'][selector]
        base_total = examined['base'][selector]
        # The denominator accounts for different span segmentation while the
        # source text and number of independent perturbations stay aligned.
        if candidate_total and candidate_count * max(base_total, 1) > base_count * candidate_total:
            unstable.append({'kind': selector[0], 'selector': selector[1],
                             'changed': candidate_count, 'examined': candidate_total})
    decision_rows = [{'kind': kind, 'changed': unstable_decisions[kind],
                      'examined': examined_decisions[kind]}
                     for kind in sorted(unstable_decisions)]
    passed = not unstable and not decision_rows and not unstable_compilations
    return {'passed': passed, 'code': None if passed else 'TYPOGRAPHY_LEAKAGE',
            'variants': 2, 'documents': len(training['samples']),
            'unstable_selectors': unstable, 'unstable_decisions': decision_rows,
            'unstable_compilations': unstable_compilations,
            'examined_compilations': examined_compilations}
