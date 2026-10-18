"""Independent, authored DOCX family for grammar and abstention checks."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from articleflow.agent023 import build_package, extract_input
from articleflow.catalogue import render_catalogue
from articleflow.docx_engine import NS, content_fingerprint, digest, load_package, parse_xml
from articleflow.format032 import audit
from articleflow.inline026 import overlay
from articleflow.research import compare_pixels, render_pdf
from articleflow.rules023 import compile_plan, semantic_spans
from scripts.build_span_grammar037 import build, sha256


REPOSITORY=Path(__file__).resolve().parents[1]
CORPUS=REPOSITORY/'datasets/span-grammar-v037'


def annotations(source,rows):
    marks={f'b-{i:06d}':[{key:mark[key] for key in ('start','end','role')}
                           for mark in row['inline']] for i,row in enumerate(rows,1)}
    return overlay(semantic_spans(source),marks)


class SpanGrammarCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.manifest=build(cls.root/'generated')
        cls.source=cls.root/'generated'
        cls.truth=json.loads((cls.source/'ground-truth.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_public_docs_are_deterministic_and_training_resources_match(self):
        self.assertEqual(self.manifest['training'],
                         ['reference-01','reference-02','reference-03'])
        published_manifest=json.loads((CORPUS/'manifest.json').read_text())
        with tempfile.TemporaryDirectory() as td:
            repeat=Path(td)/'repeat';build(repeat)
            for file in self.source.iterdir():
                if file.suffix in {'.docx','.json'}:
                    self.assertEqual(file.read_bytes(),(repeat/file.name).read_bytes())
        resources=[];sections=[];training_body=set()
        for name,entry in self.manifest['entries'].items():
            published=CORPUS/entry['file'];regenerated=self.source/entry['file']
            self.assertEqual(sha256(regenerated),entry['sha256'])
            self.assertEqual(sha256(published),published_manifest['entries'][name]['sha256'])
            self.assertEqual(published.read_bytes(),regenerated.read_bytes())
            if name not in self.manifest['training']:continue
            self.assertEqual(entry['paragraphs'],44)
            self.assertGreaterEqual(entry['role_counts']['body'],24)
            self.assertGreaterEqual(entry['style_variant_counts']['character'],8)
            extracted=self.root/f'check-{name}'
            content=extract_input(regenerated,extracted)
            self.assertEqual(len(content['objects']),2)  # OMML and authored PNG.
            rules=json.loads((extracted/'template/rules.json').read_text())
            plan=json.loads((extracted/'oracle-plan.json').read_text())
            resources.append(rules['resource_sha256'])
            sections.append(plan['section_style'])
            training_body.update(row['text'] for row in entry['rows'] if row['role']=='body')
        self.assertEqual(len(set(resources)),1)
        self.assertEqual(len(set(sections)),1)
        heldout=self.manifest['entries']['heldout-target']
        self.assertEqual(heldout['paragraphs'],44)
        self.assertTrue(training_body.isdisjoint(
            row['text'] for row in heldout['rows'] if row['role']=='body'))

    def test_plain_span_has_hidden_dash_rule_and_same_term_has_two_styles(self):
        entry=self.manifest['entries']['reference-01'];source=self.source/entry['file']
        extracted=self.root/'semantic-evidence';extract_input(source,extracted)
        plan=json.loads((extracted/'oracle-plan.json').read_text())
        by_id={row['id']:row for row in plan['blocks']}
        rows=entry['rows'];body_index=next(i for i,row in enumerate(rows,1) if row['role']=='body')
        body=rows[body_index-1];bid=f'b-{body_index:06d}'
        self.assertEqual(len(semantic_spans(source)[bid]),1)
        dash=body['text'].index('—')
        self.assertEqual(len({s['style'] for s in by_id[bid]['spans']
                              if s['start']<=dash<s['end']}),1)
        self.assertGreaterEqual(len({s['style'] for s in by_id[bid]['spans']}),2)
        definition_index=next(i for i,row in enumerate(rows,1) if row['role']=='definition')
        definition=rows[definition_index-1]
        term=definition['inline'][0]['quote']
        self.assertIn(term,body['text'])
        def style_at(index,position):
            for span in by_id[f'b-{index:06d}']['spans']:
                if span['start']<=position<span['end']:return span['style']
            raise AssertionError('missing target span')
        self.assertNotEqual(style_at(definition_index,definition['inline'][0]['start']),
                            style_at(body_index,body['text'].index(term)))
        self.assertEqual(definition['inline'][0]['role'],'defined_term')
        self.assertEqual(body['inline'],[])

    def test_i2_and_i1_keep_payload_but_diverge_in_source_emphasis(self):
        target=self.source/'heldout-target.docx';i2=self.source/'heldout-input-i2.docx'
        i1=self.source/'heldout-input-i1.docx'
        self.assertEqual(content_fingerprint(target),content_fingerprint(i2))
        self.assertEqual(content_fingerprint(target),content_fingerprint(i1))
        def run_count(path):
            root=parse_xml(load_package(path)['word/document.xml'])
            return len(root.xpath('.//w:r',namespaces=NS))
        self.assertGreater(run_count(i1),run_count(i2)*5)
        definition_index=next(i for i,row in enumerate(
            self.manifest['entries']['heldout-target']['rows'],1)
            if row['role']=='definition')
        bid=f'b-{definition_index:06d}'
        self.assertNotEqual(semantic_spans(i1)[bid],semantic_spans(i2)[bid])

    def test_oracle_training_restores_unseen_i1_i2_exactly(self):
        definitions={role:role.replace('_',' ') for role in self.truth['paragraph_roles']}
        inline={role:item['selector'] for role,item in self.truth['inline_roles'].items()
                if role!='plain'}
        samples=[];labels=[]
        for name in self.manifest['training']:
            source=self.source/f'{name}.docx';extracted=self.root/f'fit-{name}'
            content=extract_input(source,extracted)
            rows=self.manifest['entries'][name]['rows']
            samples.append({'source':source,'extracted':extracted,'content':content,
                            'semantics':annotations(source,rows)})
            labels.append({f'b-{i:06d}':row['role'] for i,row in enumerate(rows,1)})
        template_dir=self.root/'fitted-template'
        package,conflicts=build_package(samples,labels,definitions,template_dir,
                                        inline,span_grammar=True)
        self.assertEqual(conflicts,[])
        self.assertEqual(package['span_grammar']['status'],'complete')
        self.assertFalse(package['span_grammar']['source_typography_used'])
        grammar=json.dumps(package['span_grammar'],ensure_ascii=False)
        for secret in ('поток','сигнал','контур'):
            self.assertNotIn(secret,grammar)
        template=json.loads((template_dir/'rules.json').read_text())
        target=self.source/'heldout-target.docx'
        golden=render_pdf(target,self.root/'golden') if shutil.which('soffice') else None
        heldout_rows=self.manifest['entries']['heldout-target']['rows']
        assignments={f'b-{i:06d}':row['role'] for i,row in enumerate(heldout_rows,1)}
        for name in ('heldout-input-i2','heldout-input-i1'):
            with self.subTest(protocol=name):
                source=self.source/f'{name}.docx';extracted=self.root/f'extract-{name}'
                content=extract_input(source,extracted)
                self.assertEqual(len(content['blocks']),44)
                plan,issues=compile_plan(template,content,package,assignments,
                                         annotations(source,heldout_rows))
                self.assertEqual(issues,[])
                self.assertIsNotNone(plan)
                plan.update(template_sha256=digest((template_dir/'rules.json').read_bytes()),
                            input_sha256=digest((extracted/'content/content.json').read_bytes()))
                candidate=self.root/f'output-{name}.docx'
                render_catalogue(template_dir,extracted/'content',plan,candidate)
                self.assertEqual(content_fingerprint(target),content_fingerprint(candidate))
                self.assertTrue(audit(target,candidate)['property_exact'])
                if golden:
                    pdf=render_pdf(candidate,self.root/f'pdf-{name}')
                    self.assertTrue(compare_pixels(golden,pdf)['pixel_exact'])

    def test_harder_heldout_changes_structure_and_restores_i1_exactly(self):
        hard=self.manifest['entries']['heldout-hard-target']
        old=self.manifest['entries']['heldout-target']
        self.assertEqual(hard['paragraphs'],56)
        self.assertNotEqual(hard['paragraphs'],old['paragraphs'])
        self.assertEqual(hard['role_counts']['body'],33)
        self.assertEqual(hard['role_counts']['figure_container'],2)
        self.assertEqual(hard['role_counts']['figure_caption'],2)
        self.assertEqual(hard['role_counts']['equation'],1)
        training_text={row['text'] for name in self.manifest['training']
                       for row in self.manifest['entries'][name]['rows']}
        old_text={row['text'] for row in old['rows']}
        hard_text={row['text'] for row in hard['rows']
                   if row['text'] and row['role']!='abstract_heading'}
        self.assertTrue(hard_text.isdisjoint(training_text | old_text))
        target=self.source/'heldout-hard-target.docx'
        source=self.source/'heldout-hard-input-i1.docx'
        self.assertEqual(content_fingerprint(target),content_fingerprint(source))

        definitions={role:role.replace('_',' ') for role in self.truth['paragraph_roles']}
        inline={role:item['selector'] for role,item in self.truth['inline_roles'].items()
                if role!='plain'}
        samples=[];labels=[]
        for name in self.manifest['training']:
            reference=self.source/f'{name}.docx';extracted=self.root/f'hard-fit-{name}'
            content=extract_input(reference,extracted)
            rows=self.manifest['entries'][name]['rows']
            samples.append({'source':reference,'extracted':extracted,'content':content,
                            'semantics':annotations(reference,rows)})
            labels.append({f'b-{i:06d}':row['role'] for i,row in enumerate(rows,1)})
        template_dir=self.root/'hard-fitted-template'
        package,conflicts=build_package(samples,labels,definitions,template_dir,
                                        inline,span_grammar=True)
        self.assertEqual(conflicts,[])
        self.assertEqual(package['span_grammar']['status'],'complete')
        self.assertNotIn('вектор',json.dumps(package['span_grammar'],ensure_ascii=False))

        extracted=self.root/'hard-input-extracted'
        content=extract_input(source,extracted)
        self.assertEqual(len(content['blocks']),56)
        template=json.loads((template_dir/'rules.json').read_text())
        target_extracted=self.root/'hard-target-extracted'
        extract_input(target,target_extracted)
        target_template=json.loads((target_extracted/'template/rules.json').read_text())
        target_plan=json.loads((target_extracted/'oracle-plan.json').read_text())
        reference_plan=json.loads((samples[0]['extracted']/'oracle-plan.json').read_text())
        self.assertEqual(target_template['resource_sha256'],template['resource_sha256'])
        self.assertEqual(target_plan['section_style'],reference_plan['section_style'])
        assignments={f'b-{i:06d}':row['role'] for i,row in enumerate(hard['rows'],1)}
        plan,issues=compile_plan(template,content,package,assignments,
                                 annotations(source,hard['rows']))
        self.assertEqual(issues,[])
        self.assertIsNotNone(plan)
        plan.update(template_sha256=digest((template_dir/'rules.json').read_bytes()),
                    input_sha256=digest((extracted/'content/content.json').read_bytes()))
        candidate=self.root/'hard-output.docx'
        render_catalogue(template_dir,extracted/'content',plan,candidate)
        self.assertEqual(content_fingerprint(target),content_fingerprint(candidate))
        self.assertTrue(audit(target,candidate)['property_exact'])
        if shutil.which('soffice'):
            golden=render_pdf(target,self.root/'hard-golden')
            pdf=render_pdf(candidate,self.root/'hard-candidate')
            pixels=compare_pixels(golden,pdf)
            self.assertEqual((pixels['golden_pages'],pixels['candidate_pages']),(5,5))
            self.assertTrue(pixels['pixel_exact'])

    def test_identical_observable_context_remains_ambiguous(self):
        source=self.source/'negative-ambiguous.docx'
        extracted=self.root/'negative-extracted';content=extract_input(source,extracted)
        assignment={b['id']:'body' for b in content['blocks']}
        definitions={role:role.replace('_',' ') for role in self.truth['paragraph_roles']}
        package,conflicts=build_package(
            [{'source':source,'extracted':extracted,'content':content,
              'semantics':semantic_spans(source)}],[assignment],definitions,
            self.root/'negative-template',span_grammar=True)
        self.assertGreaterEqual(len(conflicts),1)
        self.assertTrue(all(c['kind']=='character' for c in conflicts))
        self.assertEqual(package['span_grammar']['status'],'ambiguous')
        template=json.loads((self.root/'negative-template/rules.json').read_text())
        plan,issues=compile_plan(template,content,package,assignment,semantic_spans(source))
        self.assertIsNone(plan)
        self.assertEqual(issues[0]['code'],'SPAN_GRAMMAR_AMBIGUOUS')


if __name__=='__main__':unittest.main()
