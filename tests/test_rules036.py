"""Context inference must not use reference IDs or source formatting."""
import json
import unittest

from articleflow.docx_engine import digest
from articleflow.rules023 import features, fit


def content(headings, entries):
    blocks=[];structure=[];assignments={}
    for index,(heading,entry) in enumerate(zip(headings,entries)):
        for position,(role,text) in enumerate([('heading',heading),('entry','Prelude 2026.'),
                                               ('entry',entry),('entry','Following 2026.')]):
            block_id=f'b-{index}-{role}-{position}'
            blocks.append({'id':block_id,'text':text,'atoms':[],'section_boundary':False,
                           'list_level':-1,'list_kind':'none','field_commands':''})
            structure.append({'kind':'paragraph','id':block_id})
            assignments[block_id]=role
    return {'blocks':blocks,'structure':structure},assignments


def examples(document,assignments,styles):
    paragraphs=features(document,assignments)['paragraph']
    return [{'kind':'paragraph','when':paragraphs[b['id']],
             'set':{'style':styles[b['id']]},'id':b['id'],
             'source_text_digest':digest(b['text'].encode())}
            for b in document['blocks'] if b['id'] in styles]


class RoleTransitionLanguageTests(unittest.TestCase):
    def test_identical_reference_under_two_heading_languages(self):
        document,assignments=content(['Список литературы','References'],
                                     ['Smith A. Article. 2026.','Smith A. Article. 2026.'])
        paragraph_ids=[b['id'] for b in document['blocks'] if b['id'].endswith('entry-2')]
        rows=examples(document,assignments,dict(zip(paragraph_ids,['ru-style','en-style'])))
        rules,conflicts=fit(rows)
        self.assertEqual(conflicts,[])
        self.assertEqual({r['when']['role_transition_language'] for r in rules},{'cyrillic','latin'})
        self.assertNotIn('Smith',json.dumps(rules))
        self.assertNotIn('source_text_digest',json.dumps(rules))
        self.assertTrue(all('b-' not in json.dumps(r) for r in rules))
        # Runtime IDs and entry wording may change; section language is stable.
        incoming,labels=content(['Источники','Sources'],
                                ['Jones B. Paper. 2027.','Jones B. Paper. 2027.'])
        matched=[]
        for b in incoming['blocks']:
            if not b['id'].endswith('entry-2'):continue
            selector=features(incoming,labels)['paragraph'][b['id']]
            matched.append(next(r['set']['style'] for r in rules
                                if all(selector.get(k)==v for k,v in r['when'].items())))
        self.assertEqual(matched,['ru-style','en-style'])

    def test_distinct_text_is_not_assumed_to_share_a_context_rule(self):
        document,assignments=content(['Описание','Description'],
                                     ['First formula','Second formula'])
        paragraph_ids=[b['id'] for b in document['blocks'] if b['id'].endswith('entry-2')]
        rows=examples(document,assignments,dict(zip(paragraph_ids,['style-a','style-b'])))
        rules,conflicts=fit(rows)
        self.assertEqual(rules,[])
        self.assertEqual(len(conflicts),1)

    def test_same_text_and_same_context_remains_ambiguous(self):
        document,assignments=content(['Список литературы','Источники'],
                                     ['Smith A. Article. 2026.','Smith A. Article. 2026.'])
        paragraph_ids=[b['id'] for b in document['blocks'] if b['id'].endswith('entry-2')]
        rows=examples(document,assignments,dict(zip(paragraph_ids,['style-a','style-b'])))
        rules,conflicts=fit(rows)
        self.assertEqual(rules,[])
        self.assertEqual(len(conflicts),1)

    def test_empty_layout_paragraph_does_not_erase_section_context(self):
        document,assignments=content(['Список литературы'],['Smith A. Article. 2026.'])
        target='b-0-entry-2'
        blank={'id':'blank','text':'','atoms':[],'section_boundary':False,
               'list_level':-1,'list_kind':'none','field_commands':''}
        document['blocks'].insert(2,blank)
        document['structure'].insert(2,{'kind':'paragraph','id':'blank'})
        assignments['blank']='spacer'
        self.assertEqual(features(document,assignments)['paragraph'][target]['role_transition_language'],
                         'cyrillic')
