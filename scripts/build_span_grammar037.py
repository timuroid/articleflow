"""Generate an entirely authored DOCX family for transferable span-grammar tests.

Three references share one resource/style/section package. The first held-out
target uses unseen prose and has two independently corrupted inputs. A harder
second held-out target changes section and object multiplicities and has an I1
input. A separate negative control has no recoverable formatting rule.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from articleflow.docx_engine import NS, load_package, parse_xml, xml_bytes, paragraph_text
from articleflow.roundtrip022 import neutralize


FAMILY='synthetic-span-grammar-037'
CASES=(('reference-01','поток','FLUXA',11),
       ('reference-02','сигнал','SIGNALB',23),
       ('reference-03','контур','LOOPC',37),
       ('heldout-target','градиент','VECTORZ',71))
GROUND_TRUTH={
    'schema':'synthetic-span-grammar-ground-truth-037',
    'license':'CC0-1.0',
    'family':FAMILY,
    'document_defaults':{'font':'Times New Roman','size_pt':11,'line_spacing':1.25,
                         'section_cm':{'page_width':21,'page_height':29.7,
                                       'left':2.6,'right':2,'top':2,'bottom':2}},
    'paragraph_roles':{
        'title':{'alignment':'center','font_size_pt':15,'bold':True,'first_line_cm':0},
        'authors':{'alignment':'center','font_size_pt':10,'first_line_cm':0},
        'abstract_heading':{'alignment':'left','font_size_pt':11,'bold':True,'first_line_cm':0},
        'abstract_body':{'alignment':'justify','font_size_pt':11,'first_line_cm':0},
        'keywords':{'alignment':'left','font_size_pt':10,'first_line_cm':0},
        'section_heading':{'alignment':'left','font_size_pt':12,'bold':True,'first_line_cm':0},
        'body':{'alignment':'justify','font_size_pt':11,'first_line_cm':0.5},
        'definition':{'alignment':'justify','font_size_pt':11,'first_line_cm':0.5},
        'symbol_explanation':{'alignment':'justify','font_size_pt':11,'first_line_cm':0.5},
        'equation':{'alignment':'center','font_size_pt':11,'first_line_cm':0},
        'figure_container':{'alignment':'center','font_size_pt':11,'first_line_cm':0},
        'figure_caption':{'alignment':'center','font_size_pt':10,'first_line_cm':0},
    },
    'inline_roles':{
        'defined_term':{'selector':'semantic definition marker, not token identity or input typography',
                        'font':'Times New Roman','bold':True,'color':'17365D'},
        'latin_symbol':{'selector':'explicit symbol role and Latin text class',
                        'font':'Courier New','bold':False,'italic':False,'color':'006B5B'},
        'caption_label':{'selector':'caption label role','bold':True,'color':'000000'},
        'plain':{'selector':'all other text in its paragraph role'},
    },
    'character_class_rules':[
        {'paragraph_role':'body','inline_role':'plain','unicode_class':'dash',
         'selector':'every U+2014 em dash in ordinary body text',
         'color':'9C562C','bold':False,'italic':False},
    ],
    'rule_hierarchy':['document defaults','paragraph role','inline role','Unicode class'],
    'forbidden_predictors':['reference paragraph number','block ID','exact term spelling',
                            'corrupted input font','corrupted input size','corrupted input bold/italic',
                            'corrupted input color'],
    'special_objects':{'equation':'OMML opaque payload; preserve equations without rewriting',
                       'figure':'one authored PNG and a separate role-labelled caption'},
    'expected':{'reference_count':3,'heldout_content_seen_during_fit':False,
                'identical_resources_and_section':True,
                'same_word_different_target_style_explained_by_inline_role':True,
                'plain_semantic_span_contains_distinct_target_character_styles':True,
                'negative_control_status':'unresolved; identical observable context has two target styles'},
}


def sha256(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_write(path:Path,parts):
    """Freeze ZIP dates and order while obeying the DOCX loader ratio bound."""
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,'w') as archive:
        for name,data in sorted(parts.items()):
            compressor=zlib.compressobj(wbits=-15)
            compressed=len(compressor.compress(data)+compressor.flush())
            method=ZIP_STORED if len(data)>max(1,compressed)*100 else ZIP_DEFLATED
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type=method;info.external_attr=0o644<<16
            archive.writestr(info,data)


def style_variant_counts(path:Path):
    """Count exact direct property alternatives without learning a rule."""
    from articleflow.catalogue import Catalogue
    parts=load_package(path);root=parse_xml(parts['word/document.xml'])
    catalogue=Catalogue()
    for paragraph in root.findall('.//w:p',NS):
        catalogue.properties('paragraph',paragraph)
        for run in paragraph.findall('.//w:r',NS):
            catalogue.properties('character',run)
    return {kind:len(catalogue.styles[kind]) for kind in ('paragraph','character')}


def png_bytes()->bytes:
    """Small deterministic, author-drawn schematic; no external images."""
    width,height=96,64
    pixels=bytearray([255,255,255]*width*height)
    def box(x0,y0,x1,y1,color):
        for y in range(y0,y1):
            for x in range(x0,x1):
                pixels[(y*width+x)*3:(y*width+x)*3+3]=bytes(color)
    box(8,13,31,29,(38,94,156));box(65,35,88,51,(21,119,97))
    box(30,30,68,33,(78,88,110));box(62,27,68,37,(78,88,110))
    raw=b''.join(b'\x00'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(name,data):
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,level=6))+chunk(b'IEND',b'')


def defaults(document):
    section=document.sections[0]
    section.page_width=Cm(21);section.page_height=Cm(29.7)
    section.left_margin=Cm(2.6);section.right_margin=Cm(2)
    section.top_margin=Cm(2);section.bottom_margin=Cm(2)
    normal=document.styles['Normal']
    normal.font.name='Times New Roman';normal.font.size=Pt(11)
    normal.paragraph_format.line_spacing=1.25
    normal.paragraph_format.space_after=Pt(0)
    normal.paragraph_format.first_line_indent=Cm(.5)
    styles=document.styles.element
    common=styles.find(qn('w:docDefaults'))
    if common is None:
        common=OxmlElement('w:docDefaults');styles.insert(0,common)
    for child in list(common):common.remove(child)
    rp_default=OxmlElement('w:rPrDefault');rp=OxmlElement('w:rPr')
    fonts=OxmlElement('w:rFonts')
    for key in ('ascii','hAnsi','eastAsia','cs'):fonts.set(qn('w:'+key),'Times New Roman')
    rp.append(fonts);size=OxmlElement('w:sz');size.set(qn('w:val'),'22');rp.append(size)
    rp_default.append(rp);common.append(rp_default)
    pp_default=OxmlElement('w:pPrDefault');pp=OxmlElement('w:pPr')
    spacing=OxmlElement('w:spacing');spacing.set(qn('w:line'),'300')
    spacing.set(qn('w:lineRule'),'auto');spacing.set(qn('w:after'),'0')
    pp.append(spacing);pp_default.append(pp);common.append(pp_default)


def paragraph_format(p,role):
    f=p.paragraph_format
    f.alignment={'center':WD_ALIGN_PARAGRAPH.CENTER,
                 'left':WD_ALIGN_PARAGRAPH.LEFT,
                 'justify':WD_ALIGN_PARAGRAPH.JUSTIFY}[GROUND_TRUTH['paragraph_roles'][role]['alignment']]
    f.first_line_indent=Cm(GROUND_TRUTH['paragraph_roles'][role]['first_line_cm'])
    f.space_after=Pt(5 if role in {'body','definition','symbol_explanation'} else 7 if role=='section_heading' else 3)
    if role=='section_heading':f.space_before=Pt(10);f.keep_with_next=True
    if role in {'equation','figure_container'}:f.space_before=Pt(7)


def apply_target_run(run,role,inline,character_class=None):
    rp=GROUND_TRUTH['paragraph_roles'][role]
    if rp.get('font_size_pt')!=11:run.font.size=Pt(rp['font_size_pt'])
    if rp.get('bold'):run.bold=True
    if inline=='defined_term':
        run.bold=True;run.font.color.rgb=RGBColor(0x17,0x36,0x5D)
    elif inline=='latin_symbol':
        run.font.name='Courier New';run.font.color.rgb=RGBColor(0,0x6B,0x5B)
    elif inline=='caption_label':run.bold=True
    elif role=='body' and inline=='plain' and character_class=='dash':
        run.font.color.rgb=RGBColor(0x9C,0x56,0x2C)


def add_paragraph(document,rows,role,text,marks=()):
    p=document.add_paragraph();paragraph_format(p,role)
    marks=sorted(marks,key=lambda x:x['start']);cursor=0
    def fragment(value,inline):
        if not value:return
        if role=='body' and inline=='plain' and '—' in value:
            pieces=value.split('—')
            for index,piece in enumerate(pieces):
                if index:apply_target_run(p.add_run('—'),role,inline,'dash')
                if piece:apply_target_run(p.add_run(piece),role,inline)
        else:apply_target_run(p.add_run(value),role,inline)
    for mark in marks:
        if not 0<=cursor<=mark['start']<mark['end']<=len(text):raise ValueError('MARK_RANGE')
        if mark['start']>cursor:fragment(text[cursor:mark['start']],'plain')
        fragment(text[mark['start']:mark['end']],mark['role'])
        cursor=mark['end']
    if cursor<len(text):fragment(text[cursor:],'plain')
    rows.append({'paragraph':len(rows)+1,'role':role,'text':text,
                 'inline':[dict(mark) for mark in marks]})
    return p


def marked(text,token,role,occurrence=1):
    start=-1
    for _ in range(occurrence):
        start=text.find(token,start+1)
        if start<0:raise ValueError('MARK_ANCHOR')
    return {'start':start,'end':start+len(token),'role':role,'quote':token}


def add_equation(document,rows,expression='Q = a + b'):
    p=document.add_paragraph();paragraph_format(p,'equation')
    math=OxmlElement('m:oMath');run=OxmlElement('m:r');text=OxmlElement('m:t')
    text.text=expression;run.append(text);math.append(run);p._p.append(math)
    rows.append({'paragraph':len(rows)+1,'role':'equation','text':'','inline':[],
                 'object_kind':'math'})


def add_figure(document,rows):
    p=document.add_paragraph();paragraph_format(p,'figure_container')
    p.add_run().add_picture(io.BytesIO(png_bytes()),width=Cm(4))
    rows.append({'paragraph':len(rows)+1,'role':'figure_container','text':'','inline':[],
                 'object_kind':'drawing'})


def family_document(path,term,alias,seed):
    document=Document();defaults(document);rows=[]
    add_paragraph(document,rows,'title',f'Синтетический протокол канала {seed}')
    add_paragraph(document,rows,'authors',f'Условный автор {seed}; лаборатория тестовых документов')
    add_paragraph(document,rows,'abstract_heading','Аннотация')
    add_paragraph(document,rows,'abstract_body',
                  f'Для серии {seed} задана искусственная сеть из двух узлов. '
                  'Документ проверяет перенос правил оформления, сохранность формулы и расположение рисунка.')
    add_paragraph(document,rows,'keywords','Ключевые слова: условный канал; правило; макет; проверка.')
    for section,title in enumerate(('Введение','Метод наблюдения','Проверка результата'),1):
        add_paragraph(document,rows,'section_heading',f'{section}. {title}')
        definition=(f'Определение: {term} — условная сущность серии {seed}, '
                    'которая обозначает передачу значения между искусственными узлами.')
        add_paragraph(document,rows,'definition',definition,
                      [marked(definition,term,'defined_term')])
        symbol=(f'Метка {alias} обозначает внутренний канал схемы {section}. '
                'Её запись нужна лишь для проверки выделения внутри обычной строки.')
        add_paragraph(document,rows,'symbol_explanation',symbol,
                      [marked(symbol,alias,'latin_symbol')])
        for number in range(8):
            value=seed+section*13+number*3
            text=(f'В серии {seed} раздела {section} контрольная запись {number+1} '
                  f'описывает {term} — искусственный канал при условном уровне {value}. '
                  'Два искусственных узла передают величину по заранее заданной схеме. '
                  'Эта фраза не сообщает результатов исследования и служит только '
                  'для проверки повторяющегося абзацного оформления.')
            add_paragraph(document,rows,'body',text)
    add_equation(document,rows)
    add_figure(document,rows)
    caption=f'Рисунок 1 — Схема двух условных узлов для серии {seed}.'
    add_paragraph(document,rows,'figure_caption',caption,
                  [marked(caption,'Рисунок 1','caption_label')])
    add_paragraph(document,rows,'section_heading','4. Заключение')
    for number in range(2):
        add_paragraph(document,rows,'body',
                      f'Итоговая синтетическая запись {seed}.{number+1} повторно называет {term}. '
                      'Содержание намеренно не связано с реальной научной статьёй; '
                      'оно фиксирует длину, порядок и целостность документа.')
    document.save(path)
    stable_write(path,load_package(path))
    return rows


def hard_document(path):
    """New wording and non-training section/paragraph multiplicities."""
    document=Document();defaults(document);rows=[]
    term='вектор';alias='TENSORQ';seed=83
    add_paragraph(document,rows,'title','Синтетический контроль неповторяющейся структуры')
    add_paragraph(document,rows,'authors','Группа условных авторов; вторая серия')
    add_paragraph(document,rows,'abstract_heading','Аннотация')
    add_paragraph(document,rows,'abstract_body',
                  'Четыре части описывают игрушечную сеть с меняющимся числом записей. '
                  'Этот независимый документ проверяет, переносится ли оформление '
                  'без знания длины раздела и числа иллюстраций.')
    add_paragraph(document,rows,'keywords',
                  'Ключевые слова: искусственная сеть; диапазон; проверка; независимый пример.')
    sections=(('Контекст измерения',5),('Разметка узлов',9),
              ('Сопоставление каналов',6),('Пределы схемы',11))
    for section,(title,count) in enumerate(sections,1):
        add_paragraph(document,rows,'section_heading',f'{section}. {title}')
        definition=(f'Определение: {term} — условное имя перехода между узлами '
                    f'в части {section}; имя не является научным термином.')
        add_paragraph(document,rows,'definition',definition,
                      [marked(definition,term,'defined_term')])
        symbol=(f'Метка {alias} задаёт технический указатель части {section}. '
                'Соседние слова оставлены обычными ради проверки границы выделения.')
        add_paragraph(document,rows,'symbol_explanation',symbol,
                      [marked(symbol,alias,'latin_symbol')])
        for number in range(count):
            level=seed+section*19+number*7
            text=(f'Часть {section}, запись {number+1}: {term} — искусственный '
                  f'маршрут со значением {level}. Соседние узлы связаны '
                  'проверочным отношением, а порядок предложений изменён по '
                  'сравнению с обучающими примерами. Смысл здесь условный; '
                  'важны только границы текста и одинаковое правило оформления.')
            add_paragraph(document,rows,'body',text)
        if section==2:
            add_figure(document,rows)
            caption='Рисунок 1 — Дополнительная схема в середине контрольного документа.'
            add_paragraph(document,rows,'figure_caption',caption,
                          [marked(caption,'Рисунок 1','caption_label')])
    add_equation(document,rows,'R = c + d')
    add_figure(document,rows)
    caption='Рисунок 2 — Итоговая схема условной сети.'
    add_paragraph(document,rows,'figure_caption',caption,
                  [marked(caption,'Рисунок 2','caption_label')])
    add_paragraph(document,rows,'section_heading','5. Выводы')
    for number in range(2):
        add_paragraph(document,rows,'body',
                      f'Контрольное завершение {number+1} называет {term} — '
                      'условный маршрут без связи с реальной публикацией. '
                      'Параграф повторяет стиль основного текста после второго рисунка.')
    document.save(path);stable_write(path,load_package(path))
    return rows


def ambiguous_document(path):
    document=Document();defaults(document);rows=[]
    text='Повторяемая синтетическая запись содержит узел и значение 9.'
    for index in range(4):
        p=add_paragraph(document,rows,'body',text)
        if index==2:
            # Identical content, role and neighbours to paragraph 2; target differs.
            p.runs[0].font.size=Pt(14)
    document.save(path);stable_write(path,load_package(path))
    return rows


def corrupt_i1(source,target):
    """Destroy source typography and arbitrary run boundaries, retaining payload."""
    parts=load_package(source);root=parse_xml(parts['word/document.xml'])
    for paragraph in root.findall('.//w:p',NS):
        if paragraph.xpath('.//w:drawing | .//m:oMath',namespaces=NS):continue
        text=paragraph_text(paragraph)
        if not text:continue
        ppr=paragraph.find('w:pPr',NS)
        if ppr is not None:paragraph.remove(ppr)
        new_ppr=OxmlElement('w:pPr');indent=OxmlElement('w:ind')
        indent.set(qn('w:firstLine'),'0');new_ppr.append(indent)
        paragraph.insert(0,new_ppr)
        for child in list(paragraph)[1:]:paragraph.remove(child)
        cursor=0;piece=0
        while cursor<len(text):
            length=1+(piece%4);fragment=text[cursor:cursor+length]
            run=OxmlElement('w:r');rpr=OxmlElement('w:rPr')
            fonts=OxmlElement('w:rFonts');fonts.set(qn('w:ascii'),'Courier New' if piece%2 else 'Arial')
            fonts.set(qn('w:hAnsi'),'Courier New' if piece%2 else 'Arial');rpr.append(fonts)
            size=OxmlElement('w:sz');size.set(qn('w:val'),'18' if piece%3 else '28');rpr.append(size)
            if piece%3==0:rpr.append(OxmlElement('w:b'))
            if piece%4==0:rpr.append(OxmlElement('w:i'))
            color=OxmlElement('w:color');color.set(qn('w:val'),'AC3D3D' if piece%2 else '284F9D')
            rpr.append(color);run.append(rpr)
            node=OxmlElement('w:t');node.text=fragment
            node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            run.append(node);paragraph.append(run)
            cursor+=len(fragment);piece+=1
    parts['word/document.xml']=xml_bytes(root);stable_write(target,parts)


def build(output:Path):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise ValueError('OUTPUT_NOT_EMPTY')
    output.mkdir(parents=True,exist_ok=True)
    entries={}
    for name,term,alias,seed in CASES:
        path=output/f'{name}.docx';rows=family_document(path,term,alias,seed)
        entries[name]={'file':path.name,'sha256':sha256(path),'paragraphs':len(rows),
                       'style_variant_counts':style_variant_counts(path),
                       'role_counts':{role:sum(row['role']==role for row in rows)
                                      for role in sorted({row['role'] for row in rows})},
                       'inline_counts':{role:sum(mark['role']==role for row in rows for mark in row['inline'])
                                        for role in sorted({mark['role'] for row in rows for mark in row['inline']})},
                       'rows':rows,'split':'held_out' if name=='heldout-target' else 'train'}
    target=output/'heldout-target.docx'
    i2=output/'heldout-input-i2.docx';neutralize(target,i2)
    stable_write(i2,load_package(i2))
    i1=output/'heldout-input-i1.docx';corrupt_i1(target,i1)
    for name,file,protocol in (('heldout-input-i2',i2,'I2: source emphasis retained, geometry/font/size removed'),
                               ('heldout-input-i1',i1,'I1: bold/italic and run breaks deliberately corrupted')):
        entries[name]={'file':file.name,'sha256':sha256(file),'split':'held_out_input',
                       'protocol':protocol,'target':'heldout-target.docx'}
    hard=output/'heldout-hard-target.docx';hard_rows=hard_document(hard)
    entries['heldout-hard-target']={
        'file':hard.name,'sha256':sha256(hard),'paragraphs':len(hard_rows),
        'style_variant_counts':style_variant_counts(hard),
        'role_counts':{role:sum(row['role']==role for row in hard_rows)
                       for role in sorted({row['role'] for row in hard_rows})},
        'inline_counts':{role:sum(mark['role']==role for row in hard_rows for mark in row['inline'])
                         for role in sorted({mark['role'] for row in hard_rows for mark in row['inline']})},
        'rows':hard_rows,'split':'held_out_hard'}
    hard_i1=output/'heldout-hard-input-i1.docx';corrupt_i1(hard,hard_i1)
    entries['heldout-hard-input-i1']={
        'file':hard_i1.name,'sha256':sha256(hard_i1),'split':'held_out_input',
        'protocol':'I1: new content and structure; bold/italic and run breaks deliberately corrupted',
        'target':hard.name}
    negative=output/'negative-ambiguous.docx';rows=ambiguous_document(negative)
    entries['negative-ambiguous']={'file':negative.name,'sha256':sha256(negative),
                                   'paragraphs':len(rows),'style_variant_counts':style_variant_counts(negative),
                                   'rows':rows,'split':'negative_control',
                                   'expected':'needs_review: same input semantics, conflicting target rPr'}
    (output/'ground-truth.json').write_text(json.dumps(GROUND_TRUTH,ensure_ascii=False,indent=2)+'\n')
    manifest={'schema':'synthetic-span-grammar-manifest-037','family':FAMILY,
              'ground_truth':'ground-truth.json','source':'authored synthetic, no external text or images',
              'training':['reference-01','reference-02','reference-03'],
              'held_out':'heldout-target','held_out_hard':'heldout-hard-target',
              'negative_control':'negative-ambiguous',
              'entries':entries}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();result=build(args.output)
    print(json.dumps({'family':result['family'],'train':len(result['training']),
                      'paragraphs':[result['entries'][n]['paragraphs'] for n in result['training']],
                      'heldout_paragraphs':result['entries'][result['held_out']]['paragraphs'],
                      'hard_heldout_paragraphs':result['entries'][result['held_out_hard']]['paragraphs']},
                     ensure_ascii=False))


if __name__=='__main__':main()
