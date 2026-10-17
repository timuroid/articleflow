"""Bounded local extraction agent: observe, experiment, enrich, verify or stop.

The evaluator may use source assignments. They are never runtime rules or an
LLM accuracy measurement. A complete catalogue is distinct from coarse transfer.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from collections import Counter
from . import typography019 as t
from .docx_engine import (NS, DocumentError, load_package, parse_xml, xml_bytes,
                          write_package, digest, dump, content_fingerprint)
from .structure017 import inventory
from .catalogue import extract_catalogue, render_catalogue, placement_fingerprint
from .research import render_pdf, compare_pixels, raster_hashes

MAX_BLOCKS = 2000
MAX_PAGES = 100
MAX_SECONDS = 600


def compare_all(expected, actual, folder):
    """All pages, exact pixels; retain per-page heatmaps without public text."""
    import pymupdf
    import numpy as np
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(expected) as a, pymupdf.open(actual) as b:
        if max(len(a), len(b)) > MAX_PAGES:
            raise DocumentError('VISUAL_PAGE_LIMIT')
    result = compare_pixels(expected, actual)
    with pymupdf.open(expected) as a, pymupdf.open(actual) as b:
        for i in range(min(len(a), len(b))):
            pa, pb = [p.get_pixmap(dpi=144, colorspace=pymupdf.csRGB, alpha=False) for p in (a[i], b[i])]
            if (pa.width, pa.height) != (pb.width, pb.height): continue
            aa = np.frombuffer(pa.samples, dtype=np.uint8).reshape(pa.height, pa.width, 3)
            bb = np.frombuffer(pb.samples, dtype=np.uint8).reshape(pb.height, pb.width, 3)
            mask = np.any(aa != bb, axis=2)
            y, x = np.where(mask)
            row = result['matched_page_diagnostics'][i]
            row['difference_bbox_px'] = [int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)] if len(x) else None
            preview = (aa.astype(np.uint16)*.25+191).astype(np.uint8)
            preview[mask] = [220, 30, 40]
            Image.fromarray(preview).save(folder/f'diff-{i+1}.png')
    result['reference_rasters'] = raster_hashes(expected)
    result['candidate_rasters'] = raster_hashes(actual)
    return result


def compact_reconstruction(source, spec, target):
    """Evaluator-only replay of EVERY observed role variant, never an unseen test."""
    parts = load_package(source)
    root = parse_xml(parts['word/document.xml']); body = root.find('w:body', NS)
    resolver = t.Resolver(parts); inv = inventory(source)
    blocks = {b['id']: b for b in inv['blocks']}
    sample = next(s for s in spec['samples'] if s['sha256'] == inv['source_sha256'])
    if any('range' in b for b in blocks.values()):
        raise DocumentError('COMPACT_INLINE_BOUNDARY_REVIEW')
    observed = {o['block_id'] for o in sample['observations']}
    if observed != set(blocks): raise DocumentError('COMPACT_OBSERVATION_COVERAGE')
    for o in sample['observations']:
        node = body[blocks[o['block_id']]['index']]
        profile = spec['styles'][o['role']][o['style_key']]
        if node.tag == t.tag('tbl'): t.apply_table(node, profile, resolver)
        else: t.apply(node, profile, resolver, o['role'])
    parts['word/document.xml'] = xml_bytes(root)
    write_package(target, parts)
    return len(observed)


def annotations(source, spec):
    parts = load_package(source); body = parse_xml(parts['word/document.xml']).find('w:body', NS)
    inv = inventory(source); blocks = {b['id']: b for b in inv['blocks']}
    sample = next(s for s in spec['samples'] if s['sha256'] == inv['source_sha256'])
    by_index = {}
    for obs in sample['observations']:
        by_index.setdefault(blocks[obs['block_id']]['index'], set()).add(obs['role'])
    labels = {}
    for i, node in enumerate(body):
        roles = by_index.get(i, {'unresolved'})
        # A paragraph with several semantic spans needs its own observed role.
        role = next(iter(roles)) if len(roles) == 1 else 'mixed_inline'
        for p in node.iter(t.tag('p')): labels[p] = role
    return {f'b-{i+1:06d}': labels[p] for i,p in enumerate(body.findall('.//w:p',NS))}


def _negative_controls(source, golden, folder):
    """Ensure the comparator detects font and section changes, not stale files."""
    results = []
    from .layout021 import empty_paragraph
    source_body=parse_xml(load_package(source)['word/document.xml']).find('w:body',NS)
    table_gap=next((i+1 for i,n in enumerate(source_body[:-1]) if n.tag==t.tag('tbl') and empty_paragraph(source_body[i+1])),None)
    modes=['font','page_geometry']+(['after_table_gap'] if table_gap is not None else [])
    for mode in modes:
        parts = load_package(source); root = parse_xml(parts['word/document.xml'])
        if mode == 'font':
            run = root.find('.//w:r[w:t]', NS)
            if run is None: raise DocumentError('VISUAL_CONTROL_NO_TEXT')
            rp = t.child(run, 'rPr')
            if rp is None: rp=t.prop('rPr'); run.insert(0,rp)
            t._replace(rp,'sz',t.prop('sz',val=80))
        elif mode=='page_geometry':
            pg = root.find('.//w:sectPr/w:pgSz',NS)
            if pg is None: raise DocumentError('VISUAL_CONTROL_NO_GEOMETRY')
            pg.set(t.tag('w'),str(int(pg.get(t.tag('w')))+720))
        else:
            body=root.find('w:body',NS);body.remove(body[table_gap])
        parts['word/document.xml']=xml_bytes(root)
        path=folder/f'negative-{mode}.docx';write_package(path,parts)
        pdf=render_pdf(path,folder/f'negative-{mode}')
        metric=compare_pixels(golden,pdf)
        results.append({'kind':mode,'detected':not metric['pixel_exact']})
    return results


def run(paths, spec, folder, progress=None, max_attempts=2, selected=None):
    """Bounded tool-agent with two representation hypotheses; no paid calls.

    Stop on success, unsupported input, renderer failure, or exhausted hypotheses.
    Never change tolerances, use block-id runtime rules or ask to waive a failure.
    """
    if not 1 <= max_attempts <= 2: raise DocumentError('AGENT_ATTEMPT_LIMIT')
    if not 1 <= len(paths) <= 10: raise DocumentError('TEMPLATE_COUNT')
    folder.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + MAX_SECONDS
    result={'schema':'template-agent-022','status':'running','samples':[],
            'scope':'all reference pages; reconstruction control, not unseen transfer',
            'model_calls':0,'paid_cost_usd':0,'max_attempts':max_attempts,
            'transfer_validation':'not_measured','started_at':time.time()}
    def emit(stage):
        if stage != 'finished' and time.monotonic() > deadline: raise DocumentError('AGENT_TIME_LIMIT')
        result['stage']=stage;dump(folder/'result.json',result)
        if progress: progress(copy.deepcopy(result))
    try:
        import os, subprocess
        result['renderer'] = {'version':subprocess.run([os.environ.get('ARTICLEFLOW_SOFFICE','soffice'),'--version'],capture_output=True,text=True,timeout=10,check=True).stdout.strip(),'dpi':144,'color':'RGB','pixel_tolerance':0}
        result['recommendations'] = {}
        for role, variants in spec['variants'].items():
            ranked=sorted(variants,key=lambda k:(-len(variants[k]),k))
            first=ranked[0]; unique=len(ranked)==1 or len(variants[first])>len(variants[ranked[1]])
            result['recommendations'][role]={'selected':first if unique else None,'observations':len(variants[first]),'total':sum(map(len,variants.values())),'basis':'dominant_observation' if unique else 'ambiguous_no_auto_choice'}
        result['selected'] = selected if selected is not None else {
            role: advice['selected'] or sorted(spec['variants'][role])[0]
            for role,advice in result['recommendations'].items()}
        if set(result['selected']) != set(spec['variants']) or any(key not in spec['variants'][role] for role,key in result['selected'].items()):
            raise DocumentError('RUNTIME_SELECTION_INVALID')
        result['selection_basis'] = 'explicit' if selected is not None else 'diagnostic_only'
        result['acceptance_contract'] = 'production-roundtrip-022-v1'
        for index,source in enumerate(paths):
            work=folder/f'sample-{index+1}';work.mkdir()
            sample={'source_sha256':digest(source.read_bytes()),'attempts':[], 'status':'running'}
            result['samples'].append(sample);emit('inventory')
            inv=inventory(source)
            parts=load_package(source);root=parse_xml(parts['word/document.xml'])
            paragraph_count=len(root.findall('w:body//w:p',NS))
            if paragraph_count>MAX_BLOCKS:raise DocumentError('VISUAL_BLOCK_LIMIT')
            sample['coverage']={'top_level_blocks':len(inv['blocks']),'paragraphs_including_cells':paragraph_count,
                                'tables':len(root.findall('.//w:tbl',NS)),'drawings':len(root.findall('.//w:drawing',NS)),
                                'math':len(root.findall('.//m:oMath',NS))}
            golden=render_pdf(source,work/'reference')
            import pymupdf
            with pymupdf.open(golden) as pdf:
                if len(pdf)>MAX_PAGES:raise DocumentError('VISUAL_PAGE_LIMIT')
            emit('compact_experiment')
            candidate=work/'compact.docx'
            compact={'strategy':'compact_role_profiles','status':'running'};sample['attempts'].append(compact)
            try:
                compact_reconstruction(source,spec,candidate)
                rendered=render_pdf(candidate,work/'compact')
                compact['pixels']=compare_all(golden,rendered,work/'compact-diff')
                compact['status']='passed' if compact['pixels']['pixel_exact'] else 'failed'
            except DocumentError as exc:
                compact.update(status='unsupported',code=str(exc))
            # Always materialize the complete reusable catalogue. A successful compact
            # experiment alone is not evidence that inline/layout variants were stored.
            if max_attempts<2:
                sample['status']='needs_review';sample['stop_reason']='attempt_limit';continue
            emit('enrich_catalogue')
            catalogue=work/'catalogue';roles=annotations(source,spec)
            manifest=extract_catalogue(source,roles,{'roles':{r:r for r in set(roles.values())}},catalogue)
            sample['catalogue_counts']=manifest['catalogue_counts']
            sample['runtime_catalogue']={'rules_sha256':manifest['template_sha256'],
                                        'path':f'sample-{index+1}/catalogue/template',
                                        'contains_reference_assignments':False}
            full={'strategy':'complete_property_catalogue','reason':'retain all observed inline and layout variants', 'status':'running'}
            sample['attempts'].append(full);emit('catalogue_experiment')
            plan=json.loads((catalogue/'oracle-plan.json').read_text())
            rebuilt=work/'reconstructed.docx'
            full['renderer']=render_catalogue(catalogue/'template',catalogue/'content',plan,rebuilt)
            # Independent content + binding checks; equal pixels alone are insufficient.
            full['content_exact']=content_fingerprint(source)==content_fingerprint(rebuilt)
            full['placements_exact']=placement_fingerprint(source)==placement_fingerprint(rebuilt)
            full['output_sha256']=digest(rebuilt.read_bytes())
            actual=render_pdf(rebuilt,work/'reconstructed')
            full['pixels']=compare_all(golden,actual,work/'catalogue-diff')
            emit('negative_controls')
            sample['negative_controls']=_negative_controls(rebuilt,actual,work)
            ok=full['content_exact'] and full['placements_exact'] and full['pixels']['pixel_exact'] and all(r['detected'] for r in sample['negative_controls'])
            full['status']='passed' if ok else 'failed'
            # The catalogue/oracle renderer is NOT the production formatter. Its
            # success must never mask a failing selected runtime template.
            emit('production_roundtrip')
            from .roundtrip022 import verify
            try:
                runtime=verify(source,spec,result['selected'],work/'production',golden,compare_all,render_pdf)
            except DocumentError as exc:
                runtime={'strategy':'production_roundtrip','status':'unsupported','code':str(exc)}
            sample['attempts'].append(runtime)
            accepted=ok and runtime['status']=='passed'
            sample['status']='passed' if accepted else 'needs_review'
            sample['stop_reason']='verified_production_roundtrip' if accepted else 'production_template_not_verified'
        result['status']='passed' if all(s['status']=='passed' for s in result['samples']) else 'needs_review'
    except DocumentError as exc:
        result.update(status='needs_review',code=str(exc))
    except Exception as exc:
        result.update(status='unavailable',error_type=type(exc).__name__)
    result['finished_at']=time.time();emit('finished');return result
