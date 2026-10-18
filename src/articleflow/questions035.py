"""Optional bounded question window. Timeout is never an answer or approval."""
import json
import time


def conflict_signature(conflict):
    """Target contrast independent of teacher role names and wording."""
    targets=tuple(sorted({json.dumps(example.get('set'),sort_keys=True,ensure_ascii=False)
                          for example in conflict.get('examples',[]) if example.get('set')}))
    return (conflict.get('kind'),targets) if len(targets)>1 else None


def clarify(conflicts,evidence,roles,persistent,*,limit=3):
    """Ask about recurring, located contradictions; never choose a style.

    Only the user-facing report receives target variants.  The compiled
    template and small model do not receive source style IDs as predictors.
    """
    if not 1<=limit<=3:raise ValueError('QUESTION_LIMIT')
    def surface(text):
        value=str(text).strip()
        if not value:return 'space'
        if '@' in value and ' ' not in value:return 'email'
        if set(value)<={'-','–','—','−'}:return 'dash'
        if not any(c.isalnum() for c in value):return 'punctuation'
        if any('\u0400'<=c<='\u052f' for c in value):return 'cyrillic_prose'
        if any('a'<=c.lower()<='z' for c in value):return 'latin_prose'
        if any('\u4e00'<=c<='\u9fff' for c in value):return 'cjk'
        return 'other'
    def difference(conflict,locations):
        variants=conflict.get('property_variants',{})
        styles=[place.get('target',{}).get('style') for place in locations]
        values=[variants.get(style,{}) for style in styles]
        if not all(isinstance(row,dict) for row in values):return ''
        parts=[]
        for path in conflict.get('differing_properties',[])[:2]:
            left,right=(row.get(path,'не задано') for row in values)
            if left==right:continue
            if path.endswith('/sz/@val') and all(str(v).isdigit() for v in (left,right)):
                label='размер шрифта';left=f'{int(left)/2:g} пт';right=f'{int(right)/2:g} пт'
            elif path.endswith('/color/@val'):
                label='цвет текста'
            else:
                label=f'свойство {path}'
            parts.append(f'{label}: А — {left}, Б — {right}')
        return ' Различие: '+ '; '.join(parts)+'.' if parts else ''
    candidates=[]
    for index,conflict in enumerate(conflicts):
        if conflict_signature(conflict) not in persistent:continue
        role=conflict.get('when',{}).get('role')
        if role not in roles or index>=len(evidence.get('groups',[])):continue
        locations=evidence['groups'][index].get('locations',[])
        if len(locations)<2:continue
        chosen=[];seen=set()
        for location in locations:
            target=json.dumps(location.get('target'),sort_keys=True,ensure_ascii=False)
            if target in seen:continue
            seen.add(target);chosen.append(location)
            if len(chosen)==2:break
        if len(chosen)<2:continue
        same_block=chosen[0].get('block_id')==chosen[1].get('block_id') and chosen[0].get('document')==chosen[1].get('document')
        same_surface=surface(chosen[0].get('excerpt'))==surface(chosen[1].get('excerpt'))
        meaningful=same_surface and surface(chosen[0].get('excerpt')) in {'cyrillic_prose','latin_prose','email'}
        candidates.append((not same_block,not meaningful,not same_surface,
                           conflict.get('kind')!='character',-len(conflict.get('examples',[])),index,role,chosen,conflict))
    result=[];used_roles=set()
    for _,_,_,_,_,index,role,locations,conflict in sorted(candidates):
        if role in used_roles:continue
        used_roles.add(role)
        def where(place):
            span=place.get('range')
            range_text=f', символы {span[0]}–{span[1]}' if isinstance(span,list) and len(span)==2 else ''
            excerpt=str(place.get('excerpt','')).replace('\n',' ').strip()[:42]
            return f'док. {place["document"]}, абз. {place["paragraph"]}{range_text} («{excerpt}»)'
        question=(f'Для блока «{role}» эталон задаёт два разных оформления при одинаковых текущих признаках: '
                  f'вариант А — {where(locations[0])}; вариант Б — {where(locations[1])}. '
                  f'{difference(conflict,locations)} '
                  'Один вариант ошибочен? Если оба верны, опишите общее правило выбора по смыслу или структуре.')
        result.append({'role':role,'question':question[:600],
                       'source':'persistent_training_conflict',
                       'conflict_index':index,
                       'evidence':[{'variant':variant,'document':place['document'],
                                    'block_id':place['block_id'],'paragraph':place['paragraph'],
                                    'range':place.get('range'),'excerpt':str(place.get('excerpt',''))[:120],
                                    'target':place.get('target')}
                                   for variant,place in zip(('A','B'),locations)]})
        if len(result)==limit:break
    return result


def wait(questions, initial, provider, emit, *, seconds=30, clock=time.monotonic, wall=time.time, sleep=time.sleep):
    started=clock();deadline=wall()+seconds
    state={'status':'waiting','deadline_unix':deadline,'seconds':seconds,'questions':questions,'initial_revision':initial['revision']}
    emit(dict(state))
    while clock()-started<seconds:
        latest=provider()
        if latest['revision']>initial['revision']:
            state.update(status='answered',waited_seconds=round(clock()-started,3),received_revision=latest['revision']);emit(dict(state));return latest,state
        sleep(min(.25,max(0,seconds-(clock()-started))))
    state.update(status='continued_without_answer',waited_seconds=round(clock()-started,3));emit(dict(state));return initial,state
