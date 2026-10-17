"""Executable Web 019 recovery scenarios; synthetic documents, no network."""
import io
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch
from behave import given, when, then
from docx import Document
from fastapi.testclient import TestClient
from articleflow.structure017 import inventory, suggest_roles, compile_document, inspect_templates
from articleflow.web017 import create_app


def setup(c):
    if hasattr(c, 'work019'): return
    temp=tempfile.TemporaryDirectory();c.add_cleanup(temp.cleanup);c.work019=Path(temp.name)
    c.doc019=Document();c.doc019.add_paragraph('Исследование тестового материала')
    c.doc019.add_paragraph('Иванов И. И.');c.doc019.add_paragraph('Аннотация')
    for text in ['Цель. Проверить структуру.', 'Результаты. Получено 42.', 'Практическая значимость. Контроль качества.', 'Постановка проблемы. Различия оформления.']:
        c.doc019.add_paragraph(text)
    c.doc019.add_paragraph('Ключевые слова: оформление');c.doc019.add_paragraph('Основной научный текст.')


def compile_test(c):
    setup(c);src=c.work019/'source.docx';c.doc019.save(src);c.source019=src.read_bytes()
    c.blocks019=inventory(src)['blocks'];c.roles019=suggest_roles(c.blocks019)[0]
    c.report019=compile_document(src,c.work019/'result.docx',assignments=c.roles019,approved=True,fonts_ok=True,editorial_output=c.work019/'editorial.docx')


@given('утверждённый шаблон требует постановку проблемы перед целью внутри аннотации')
@given('утверждённый шаблон требует постановку проблемы внутри аннотации')
@given('утверждённый шаблон требует авторов и практическую значимость')
def standard(c): setup(c)

@given('статья содержит подписанную постановку после аннотации и до ключевых слов')
def misplaced(c): setup(c)

@when('система строит структурный план статьи')
@when('система определяет роли')
@when('система собирает документ')
def build(c): compile_test(c)

@then('план связывает постановку с её исходным фрагментом')
def binding(c):
    b=next(b for b in c.blocks019 if b['text'].startswith('Постановка проблемы'))
    assert c.report019['assignments'][b['id']]=='abstract_problem'

@then('ставит её перед целью внутри аннотации')
def order(c):
    texts=[p.text for p in Document(c.work019/'result.docx').paragraphs]
    assert next(i for i,t in enumerate(texts) if t.startswith('Постановка')) < next(i for i,t in enumerate(texts) if t.startswith('Цель'))

@then('сохраняет научный текст и остальные исходные узлы')
def conserved(c):
    from collections import Counter
    assert Counter(p.text for p in c.doc019.paragraphs)==Counter(p.text for p in Document(c.work019/'result.docx').paragraphs)
    assert (c.work019/'source.docx').read_bytes()==c.source019

@given('статья содержит заголовок основной части «Проблема и постановка»')
def body_heading(c):
    setup(c)
    for p in c.doc019.paragraphs:
        if p.text.startswith('Постановка проблемы'):p._element.getparent().remove(p._element)
    c.doc019.add_paragraph('Проблема и постановка')

@then('заголовок основной части остаётся в основной части')
def stays(c):
    b=next(b for b in c.blocks019 if b['text']=='Проблема и постановка');assert c.roles019[b['id']]=='body'

@then('отсутствие постановки в аннотации отражается отдельным вопросом')
def absent_problem(c): assert 'abstract_problem' in c.report019['missing']

@given('в статье нет этих сведений')
def absent(c):
    setup(c)
    for p in c.doc019.paragraphs:
        if p.text.startswith(('Иванов','Практическая значимость')):p._element.getparent().remove(p._element)

@then('она вставляет явно помеченные места для заполнения')
def placeholders(c):
    texts=[p.text for p in Document(c.work019/'result.docx').paragraphs]
    assert '[ЗАПОЛНИТЬ: authors]' in texts and '[ЗАПОЛНИТЬ: abstract_practical]' in texts

@then('сообщает редактору, какие сведения нужны')
def needs(c): assert {'authors','abstract_practical'}<=set(c.report019['missing'])

@then('запрещает выдачу документа как готового')
def draft(c): assert c.report019['status']=='draft'

@given('статья содержит строку «Рабочая рукопись» до заголовка')
def editorial(c):
    setup(c);c.doc019.paragraphs[0].insert_paragraph_before('Рабочая рукопись')

@when('редактор подтверждает, что это редакционная заметка')
def confirm(c): compile_test(c)

@then('система не заменяет ею сведения об авторах')
def authors(c):
    b=next(b for b in c.blocks019 if b['text']=='Рабочая рукопись');assert c.roles019[b['id']]=='editorial'
    assert 'authors' not in c.report019['missing']

@then('сохраняет её в отдельном редакционном результате')
def separate(c): assert Document(c.work019/'editorial.docx').paragraphs[0].text=='Рабочая рукопись'

@then('оставляет исходный DOCX доступным')
def unchanged(c): assert (c.work019/'source.docx').read_bytes()==c.source019


def web(c):
    setup(c);mock=patch('articleflow.web017.font_audit',return_value={'exact':True,'families':{}});mock.start();c.add_cleanup(mock.stop)
    c.client019=TestClient(create_app(c.work019/'web'));c.add_cleanup(c.client019.close)
    c.headers019={'X-CSRF-Token':c.client019.get('/api/v017/config').json()['csrf_token']}


def uploaded(c, variants=False):
    web(c);files=[]
    for i in range(2 if variants else 1):
        c.doc019.styles['Normal'].font.name='Arial' if i==0 else 'Times New Roman'
        buffer=io.BytesIO();c.doc019.save(buffer);files.append(('files',(str(i)+'.docx',buffer.getvalue(),'application/octet-stream')))
    response=c.client019.post('/api/v017/templates',headers=c.headers019,data={'name':'Synthetic'},files=files)
    assert response.status_code==200;c.template019=response.json()['id']
    c.spec019=c.client019.get('/api/v017/templates/'+c.template019).json()['spec']

@given('редактор загрузил несколько эталонных DOCX одного шаблона')
def multi(c): uploaded(c,True)

@given('в эталонах различаются параметры одного обязательного слота')
def conflict(c): assert c.spec019['conflicts']

@when('система сравнивает наблюдения')
def inspect(c): assert c.spec019['samples']

@then('она показывает оба варианта с источником')
def evidence(c):
    variants=c.spec019['variants']['__base__'];assert len(variants)==2 and all(variants.values())

@then('не утверждает спорный вариант автоматически без достаточного правила')
def not_approved(c):
    assert not c.client019.get('/api/v017/templates/'+c.template019).json()['approved']
    assert c.client019.post('/api/v017/templates/'+c.template019+'/approve',headers=c.headers019,json={'selected':{}}).status_code==409

@then('подтверждённое решение создаёт новую версию шаблона')
def version(c):
    selected={r:next(iter(v)) for r,v in c.spec019['variants'].items()}
    response=c.client019.post('/api/v017/templates/'+c.template019+'/approve',headers=c.headers019,json={'selected':selected})
    assert response.status_code==200 and response.json()['version']==2

@given('утверждённый шаблон и пакет из нескольких статей')
def batch(c):
    uploaded(c);version(c)
    buffer=io.BytesIO();c.doc019.save(buffer);c.complete019=buffer.getvalue()

@given('в одной статье недостаёт обязательного поля')
def missing_batch(c): absent(c)

@when('система обрабатывает пакет')
def process(c):
    buffer=io.BytesIO();c.doc019.save(buffer)
    response=c.client019.post('/api/v017/batches',headers=c.headers019,data={'template_id':c.template019},files=[('files',('complete.docx',c.complete019)),('files',('missing.docx',buffer.getvalue()))])
    assert response.status_code==202;c.batch019=response.json()['id']
    c.jobs019=c.client019.get('/api/v017/batches/'+c.batch019).json()['jobs']

@then('остальные статьи продолжают обрабатываться')
def continued(c): assert len(c.jobs019)==2 and all(j['status']=='draft' for j in c.jobs019)

@then('архив содержит отдельный статус и отчёт для каждого документа')
def zipped(c):
    response=c.client019.post('/api/v017/batches/'+c.batch019+'/exports',headers=c.headers019)
    assert response.status_code==200
    data=c.client019.get(response.json()['url']).content
    with ZipFile(io.BytesIO(data)) as z:
        manifest=json.loads(z.read('manifest.json'));assert len(manifest['jobs'])==2
        assert len([n for n in z.namelist() if n.endswith('.json')])>=3

@then('статья с недостающим полем остаётся черновиком')
def incomplete(c):
    job=next(j for j in c.jobs019 if j['source_name']=='missing.docx');assert job['status']=='draft'
    assert c.client019.get('/api/v017/jobs/'+job['id']+'/files/final').status_code==409
