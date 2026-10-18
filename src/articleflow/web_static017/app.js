const api = '/api/v017';
const state = { csrf: '', templates: [], batchId: null, timer: null, llm: false };
const currentPage = location.pathname === '/templates' ? 'templates' : location.pathname === '/history' ? 'history' : 'documents';

const roleLabels = {udc:'УДК',title:'Название статьи',authors:'Авторы',affiliation:'Организация',city:'Город',email:'Электронная почта',abstract_heading:'Заголовок аннотации',abstract_problem:'Постановка проблемы',abstract_goal:'Цель',abstract_results:'Результаты',abstract_practical:'Практическая значимость',abstract_remainder:'Неразобранная часть аннотации',keywords:'Ключевые слова','keywords.heading':'Заголовок ключевых слов',body:'Основной текст','body.table':'Таблицы','body.table_caption':'Подписи таблиц','body.figure':'Иллюстрации','body.figure_caption':'Подписи иллюстраций',editorial:'Редакторские заметки',__base__:'Основное оформление документа',__document__:'Размер страницы и поля'};
const jobStatus = {queued:'В очереди',processing:'Обрабатывается',draft:'Нужна проверка',ready:'Готово',error:'Ошибка',failed:'Ошибка',needs_review:'Нужна проверка'};
const roleName = role => roleLabels[role] || (role.startsWith('body.heading.') ? `Заголовок уровня ${role.split('.').pop()}` : role);
const $ = (id) => document.getElementById(id);
const node = (tag, className = '', value = '') => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (value) item.textContent = value;
  return item;
};
const button = (label, onClick, className = 'button') => {
  const item = node('button', className, label);
  item.type = 'button';
  item.addEventListener('click', async () => {
    item.disabled = true; item.setAttribute('aria-busy', 'true');
    try { await onClick(); } catch (error) { message(error.message, true); }
    finally { item.disabled = false; item.removeAttribute('aria-busy'); }
  });
  return item;
};
const table = (headers) => {
  const element = node('table', 'data-table');
  const head = node('thead');
  const row = node('tr');
  for (const title of headers) {
    const cell = node('th', '', title);
    cell.scope = 'col';
    row.append(cell);
  }
  head.append(row);
  const body = node('tbody');
  element.append(head, body);
  return { element, body };
};
const cell = (row, value, className = '') => {
  const item = node('td', className, value);
  row.append(item);
  return item;
};
const message = (value, error = false) => {
  for (const target of [$('message'), $('dialog-message')]) {
    target.textContent = value;
    target.className = error ? 'message error' : 'message';
    target.hidden = !value;
  }
};
async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(api + path, { ...options, headers, cache: 'no-store' });
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : (payload.detail?.code || response.statusText);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}
async function loadTemplates() {
  const rows = await request('/templates');
  state.templates = rows.map((row) => ({ ...row, spec: JSON.parse(row.spec_json) }));
  const list = $('template-list');
  list.replaceChildren();
  const select = $('batch-template');
  select.replaceChildren(node('option', '', 'Выберите утверждённый шаблон'));
  select.firstChild.value = '';
  const { element, body } = table(['Название', 'Версия', 'Эталоны', 'Статус', 'Создан', 'Действие']);
  for (const item of state.templates) {
    const row = node('tr');
    cell(row, item.name);
    cell(row, String(item.version));
    cell(row, String(item.spec.samples?.length || 0));
    const status = cell(row, '');
    status.append(node('span', `badge ${item.approved ? 'ready' : 'draft'}`, item.approved ? 'Утверждён' : 'Требует проверки'));
    cell(row, new Date(item.created_at).toLocaleDateString('ru-RU'));
    cell(row, '').append(button('Открыть', () => showTemplate(item.id)));
    body.append(row);
    if (item.approved) {
      const option = node('option', '', `${item.name} · версия ${item.version}`);
      option.value = item.id;
      select.append(option);
    }
  }
  if (rows.length) list.append(element);
  else list.append(node('p', 'empty', 'Шаблонов пока нет. Создайте первый из эталонных DOCX.'));
}
async function showTemplate(id) {
  if (currentPage !== 'templates') { window.location.href = `/templates?template=${encodeURIComponent(id)}`; return; }
  const item = await request(`/templates/${id}`);
  const target = $('template-review');
  target.hidden = false;
  target.replaceChildren(node('h3', '', `${item.name} · версия ${item.version}`));
  const spec = item.spec;
  target.append(node('p', '', spec.external_import
    ? `Эталонов: ${spec.samples.length}. Внешняя разметка импортирована как черновик. Перенос на новые документы ещё не проверен.`
    : `Эталонов: ${spec.samples.length}. Сначала запустите проверку всех страниц. Спорные варианты оформления сохраняются для проверки.`));
  const validation = node('div', 'review stack'); validation.setAttribute('aria-live','polite'); target.append(validation);
  const stageNames = {inventory:'Инвентаризация документа',compact_experiment:'Проверка профилей ролей',enrich_catalogue:'Сохранение полных свойств',catalogue_experiment:'Сравнение всех страниц',negative_controls:'Проверка обнаружения ошибок',production_roundtrip:'Проверка рабочего сборщика на исходном и очищенном тексте',finished:'Цикл завершён'};
  const statusNames = {passed:'Рабочий шаблон прошёл контроль',needs_review:'Шаблон не прошёл проверку',unavailable:'Проверка недоступна',interrupted:'Запуск прерван',queued:'В очереди',running:'Выполняется'};
  async function showRun(runId) {
    const run = await request(`/template-runs/${runId}`); const r=run.report;
    if(r.schema==='external-semantic-import-037') {
      validation.replaceChildren(node('strong','','Внешняя разметка: требуется проверка'));
      validation.append(node('p','help',`Размечено ${r.paragraphs} абзацев в ${r.references.length} эталонах. Противоречий: ${r.training_conflicts}. Вызовов модели: ${r.model_calls}.`));
      validation.append(node('p','help','Совпадение с эталонами и перенос на новый документ не подтверждены. Импорт сам по себе не делает шаблон доступным для пакетной обработки.'));
      for(const q of r.questions||[]) validation.append(node('p','',`Вопрос о «${q.role}»: ${q.question}`));
      if(r.conflicts?.length) {
        const details=node('details');details.append(node('summary','',`Противоречивые правила (${r.conflicts.length})`));
        for(const [index,conflict] of r.conflicts.entries()) {
          const row=node('div','item');
          const when=Object.entries(conflict.when||{}).map(([key,value])=>`${key}: ${value}`).join(', ');
          row.append(node('strong','',`${index+1}. ${conflict.kind} · ${conflict.variants||'?'} варианта`));
          if(when)row.append(node('p','help',when));
          for(const example of conflict.examples||[]) {
            const place=[example.document&&`эталон ${example.document}`,example.id&&`блок ${example.id}`,
              example.range&&`символы ${example.range.join('–')}`].filter(Boolean).join(', ');
            if(place)row.append(node('p','help',place));
          }
          details.append(row);
        }
        validation.append(details);
      }
      return;
    }
    if(r.schema==='external-import-test-037') {
      const label={queued:'Пробное оформление в очереди',running:'Модель оформляет пробный DOCX',
        needs_review:'Пробный документ готов к проверке',failed:'Пробное оформление не удалось'};
      validation.replaceChildren(node('strong','',label[run.status]||run.status));
      validation.append(node('p','help','Этот запуск проверяет один новый документ и не утверждает шаблон для пакетной обработки.'));
      if(r.application_status)validation.append(node('p','',`Сборщик: ${r.application_status}. Неразрешённых мест: ${r.unresolved?.length||0}. Вызовов модели: ${r.model_invocations??'не подтверждено'}.`));
      if(r.code)validation.append(node('p','error',`Причина остановки: ${r.code}`));
      for(const issue of r.unresolved||[])validation.append(node('p','help',`${issue.code||issue.kind||'Неразрешённое место'}${issue.id?` · ${issue.id}`:''}`));
      if(r.visual_diagnostics)validation.append(node('p','help',`Проверка всех страниц: ${r.visual_diagnostics.status}. Замечаний: ${r.visual_diagnostics.issues?.length||0}. Это не проверка соответствия новому содержимому шаблона.`));
      if(r.result_available)for(const [kind,title] of [['docx','Скачать пробный DOCX'],['pdf','Открыть пробный PDF']]){
        const link=node('a','button',title);link.href=`${api}/import-tests/${runId}/files/${kind}`;link.target='_blank';link.rel='noopener';validation.append(link);
      }
      if(['queued','running'].includes(run.status) && target.contains(validation))setTimeout(()=>showRun(runId).catch(e=>message(e.message,true)),2000);
      return;
    }
    if(r.schema==='external-import-verification-037') {
      const label={queued:'Проверка эталонов в очереди',running:'Сверяем восстановление эталонов',
        needs_review:'Восстановление эталонов не прошло проверку',
        reference_replay_passed:'Восстановление эталонов прошло проверку'};
      validation.replaceChildren(node('strong','',label[run.status]||run.status));
      validation.append(node('p','help','Проверяется воспроизведение очищенных эталонов: роли, внутритекстовые метки, свойства DOCX, все страницы и контрольные ошибки. Независимый новый документ этим не сертифицирован.'));
      for(const sample of r.samples||[]) {
        const pixels=sample.pixels?.pixel_exact===true?'все пиксели совпали':'совпадение не подтверждено';
        const properties=sample.format?.property_exact===true?'OOXML-свойства совпали':'свойства не подтверждены';
        validation.append(node('p',sample.passed?'success':'help',`Эталон ${sample.document}: роли ${sample.role_correct??'—'}/${sample.role_total??'—'}, внутритекстовые диапазоны ${sample.inline_correct??'—'}/${sample.inline_total??'—'}; ${properties}; ${pixels}. ${sample.code||''}`));
      }
      if(r.negative_controls?.length)validation.append(node('p','help',`Контрольных ошибок обнаружено: ${r.negative_controls.filter(c=>c.detected).length}/${r.negative_controls.length}.`));
      if(r.code)validation.append(node('p','error',`Причина остановки: ${r.code}`));
      if(run.status==='reference_replay_passed' && !item.approved) {
        validation.append(node('p','help','Эталонные копии восстановлены точно в проверенном движке. Перенос на независимый документ остаётся непроверенным; утверждение — отдельное решение редактора.'));
        const imported=(await request(`/template-runs/${spec.external_import.run_id}`)).report;
        const answers={};
        for(const q of imported.questions||[]) {
          const label=node('label','',q.question),select=node('select');
          for(const [value,title] of [['','Выберите ответ'],['yes','Блок обязателен'],['no','Блок необязателен']]){
            const option=node('option','',title);option.value=value;select.append(option);
          }
          label.append(select);validation.append(label);answers[q.role]=select;
        }
        validation.append(button('Утвердить для пакетной обработки',async()=>{
          if(Object.values(answers).some(select=>!select.value)){message('Ответьте на вопросы о блоках.',true);return;}
          const chosen=Object.fromEntries(Object.entries(answers).map(([role,select])=>[role,select.value==='yes']));
          const result=await request(`/templates/${id}/approve-import`,{method:'POST',body:JSON.stringify({run_id:runId,answers:chosen})});
          await loadTemplates();await showTemplate(id);message(`Утверждена версия ${result.version}; перенос на независимые документы отдельно не измерен.`);
        },'button primary'));
      }
      if(['queued','running'].includes(run.status) && target.contains(validation))setTimeout(()=>showRun(runId).catch(e=>message(e.message,true)),2000);
      return;
    }
    if(r.schema==='teacher-student-023') {
      const names={queued:'Обучение в очереди',running:'Агент обучает шаблон',reference_verified:'Совпадение на эталонах подтверждено',needs_review:'Нужна доработка',interrupted:'Обучение прервано',unavailable:'Обучение недоступно'};
      validation.replaceChildren(node('strong','',names[run.status]||run.status));
      const stages={awaiting_optional_answer:'Можно уточнить требования; затем агент продолжит сам',engine_selecting_replay:'Выбираем лучшую проверенную попытку',engine_baseline:'Воспроизводим ошибку движка',engine_proposing_patch:'Готовим исправление сборщика',engine_testing_patch:'Проверяем исправление в изоляции',engine_rechecking:'Повторяем полный цикл с исправленным движком',provider_wait:'Модель временно недоступна. Повторяем запрос с сохранением шаблона',preflight:'Проверяем точную пересборку и адаптируем чтение',extracting:'Читаем структуру и оформление',teacher:'Создаём правила большой моделью',compiling:'Проверяем совместимость правил',student:'Восстанавливаем документ малой моделью',comparing:'Сравниваем все страницы',stress_testing:'Проверяем изменённое оформление и порядок блоков',negative_controls:'Проверяем обнаружение ошибок',finished:'Проверка завершена'};
      if(!r.engine_repair || r.engine_repair.status==='not_configured') Object.keys(stages).filter(k=>k.startsWith('engine_')).forEach(k=>delete stages[k]);
      const timeline=node('ol','pipeline');
      const current=Object.keys(stages).indexOf(r.stage==='finished' && run.status!=='reference_verified' ? r.last_stage : r.stage);
      Object.entries(stages).forEach(([key,label],index)=>{const item=node('li',index===current?'active':'',label);if(index===current)item.setAttribute('aria-current','step');timeline.append(item);});
      validation.append(timeline);
      if(r.engine_repair?.total_probes) validation.append(node('p','help',`Исправление движка: проверено ${r.engine_repair.completed_probes||0} из ${r.engine_repair.total_probes} случаев на текущем этапе.`));
      if(r.limits) validation.append(node('p','help',`Прошло ${Math.round((r.elapsed_seconds||0)/60)} мин. Проверяем эталоны и изменённые копии; результат появится после завершения проверок.`));
      for(const prep of r.preparation||[]) validation.append(node('p','help',`Эталон ${prep.document}: ${prep.status||'проверяется'}; попыток чтения ${prep.attempts.length}. ${prep.attempts.map(a=>a.code||a.status||'в работе').join(' → ')}`));
      const bestIteration=r.iterations?.find(row=>row.number===r.best_training_iteration);
      const latestQuestions=r.questions||bestIteration?.questions||r.iterations?.at(-1)?.questions||[];
      if(r.best_training_iteration && run.status!=='reference_verified') validation.append(node('p','help',`Лучшая проверенная разметка: итерация ${r.best_training_iteration}, конфликтов ${r.best_training_conflicts}. Неудачные поздние попытки сохранены в истории.`));
      if(r.question_window?.status==='waiting') validation.append(node('p','help',`Можно ответить в течение ${Math.max(0,Math.ceil(r.question_window.deadline_unix-Date.now()/1000))} с. Без ответа агент продолжит анализ; это не подтверждение требований.`));
      if(r.question_window?.status==='continued_without_answer') validation.append(node('p','help','Ответ не получен. Агент продолжил самостоятельно; требования не подтверждены.'));
      if(latestQuestions.length && run.status!=='reference_verified') {validation.append(node('h4','','Вопросы агента'));for(const q of latestQuestions) validation.append(node('p','',q.question));validation.append(node('p','help','Ответ можно передать как уточнение. После завершения цикла используйте повторную проверку ниже.'));}

      if(r.published_version) {validation.append(node('p','success',`Шаблон автоматически сохранён: версия ${r.published_version}.`));if(spec.agent023?.run_id!==runId)validation.append(button('Обновить список шаблонов',async()=>{await loadTemplates();await showTemplate(id);}));}
      if(['queued','running'].includes(run.status)) {
        let pane=target.querySelector('[data-learning-feedback]');
        if(!pane || pane.dataset.learningFeedback!==runId) {
          if(pane)pane.remove();pane=node('details','review');pane.dataset.learningFeedback=runId;
          pane.append(node('summary','','Уточнить требования во время работы'));
          const label=node('label','','Дополнение для следующей итерации');const input=node('textarea');input.rows=3;input.maxLength=12000;label.append(input);pane.append(label);
          pane.append(node('p','help','Например: сведения о финансировании необязательны. Уже выполняющийся запрос не меняется. Если цикл завершится раньше, уточнение понадобится в новом запуске.'));
          pane.dataset.revision=String(r.feedback_revision_received||0);
          pane.append(button('Передать уточнение',async()=>{const result=await request(`/template-runs/${runId}/feedback`,{method:'POST',body:JSON.stringify({text:input.value,expected_revision:Number(pane.dataset.revision)})});pane.dataset.revision=String(result.revision);message('Уточнение сохранено. Оно будет прочитано перед следующей итерацией.');}));
          target.insertBefore(pane,validation.nextSibling);
        }
        validation.append(node('p','help',`Уточнения: принято ${r.feedback_revision_received||0}, учтено ${r.feedback_revision_applied||0}.`));
      } else {const pane=target.querySelector('[data-learning-feedback]');if(pane)pane.remove();}
      for(const iteration of r.iterations||[]) {
        validation.append(node('p','',`Итерация ${iteration.number}: проверено документов ${iteration.applications.length}; противоречивых правил ${iteration.conflicting_groups ?? '—'}.`));
        if(iteration.conflict_properties?.length){const details=node('details');details.append(node('summary','','Какие свойства расходятся'));details.append(node('p','help',iteration.conflict_properties.join(', ')));validation.append(details);}
        if(iteration.conflict_evidence?.total){
          const evidence=iteration.conflict_evidence;const details=node('details');details.append(node('summary','','Места, требующие уточнения'));
          details.append(node('p','help','Все различия сохранены. Для переноса на новые документы нужно объяснить, когда выбирать каждый вариант.'));
          for(const group of evidence.groups){
            details.append(node('p','',`${group.kind} · ${group.when.role||'контекст'} · вариантов: ${group.variants??'неизвестно'}`));
            if(group.differing_properties.length)details.append(node('p','help',group.differing_properties.join(', ')));
            if(Object.keys(group.property_variants||{}).length){
              const variants=node('details');variants.append(node('summary','','Точные значения вариантов'));
              for(const [style,values] of Object.entries(group.property_variants)){variants.append(node('strong','',style));for(const [property,value] of Object.entries(values))variants.append(node('p','help',`${property}: ${value}`));}
              details.append(variants);
            }
            for(const location of group.locations){
              details.append(node('p','',`Документ ${location.document}, абзац ${location.paragraph}${location.range?`, символы [${location.range.join(', ')})`:''}: ${location.excerpt}`));
              const fragment=node('p','conflict-fragment');fragment.append(document.createTextNode(location.before||''),node('mark','',location.excerpt),document.createTextNode(location.after||''));details.append(fragment);
              details.append(button('Уточнить этот вариант',()=>{const pane=target.querySelector('[data-learning-feedback]');const input=pane?.querySelector('textarea')||target.querySelector('[data-template-context]');if(!input){message('Для сохранения уточнения настройте модель и начните новый цикл обучения.',true);return;}if(input){input.value+=`${input.value?'\n':''}Документ ${location.document}, абзац ${location.paragraph}, роль ${group.when.role||group.kind}: `;if(pane)pane.open=true;input.focus();}message('Опишите смысловое условие выбора этого варианта. Номер абзаца служит ссылкой на пример, а не правилом шаблона.');}));
              const link=node('a','','Открыть эталон PDF');link.href=`${api}/template-runs/${runId}/agent-preview/${location.document}/reference`;link.target='_blank';link.rel='noopener';details.append(link);
            }
            if(!group.location_complete)details.append(node('p','help','Места показаны не для всех вариантов; требуется дополнительная диагностика.'));
          }
          if(evidence.truncated)details.append(node('p','help',`Показаны первые ${evidence.groups.length} из ${evidence.total} конфликтов.`));
          validation.append(details);
        }
        for(const test of iteration.stress||[]) validation.append(node('p',test.passed?'success':'help',`Проверка ${test.variant}, документ ${test.document}: ${test.passed?'совпало':test.code||test.status}.`));
        for(const [index,a] of iteration.applications.entries()) {
          const pixels=a.pixels;
          const outcome=a.status==='failed' ? `Ответ модели отклонён: ${a.code||'неверный формат'}. Сборка не выполнялась.` :
            pixels ? `Совпали ${pixels.matched_page_diagnostics.filter(p=>p.pixel_exact).length}/${pixels.golden_pages} страниц.` :
            `Неоднозначных назначений: ${a.unresolved?.length||0}.`;
          const roles=Number.isInteger(a.role_correct)&&Number.isInteger(a.role_total) ? `роли ${a.role_correct}/${a.role_total}. ` : '';
          validation.append(node('p',a.passed?'':'help',`Документ ${index+1}: ${roles}${outcome}`));
        }
      }
      for(let i=1;i<=(r.training_documents||0);i++) for(const [mode,label] of [['reference','Эталон'],['result','Результат']]) {
        const link=node('a','button',`${label} ${i} · PDF`);link.href=`${api}/template-runs/${runId}/agent-preview/${i}/${mode}`;link.target='_blank';link.rel='noopener';validation.append(link);
      }
      if(r.code) {
        const reasons={SEMANTIC_PLATEAU:'Повторная попытка не изменила назначения блоков и спорные правила. Нужен дополнительный эталон или уточнение условия выбора оформления.',TRAINING_CONFLICTS:'В эталоне есть варианты оформления, для которых пока нет однозначного правила.'};
        validation.append(node('p','error',`Причина остановки: ${reasons[r.code]||r.code}. История попыток сохранена.`));
      }
      if(r.publication_blocked) validation.append(node('p','error',`Шаблон не сохранён: ${r.publication_blocked}. Для неприменённого уточнения запустите новый цикл, указав его в дополнительных требованиях.`));
      if(run.status==='reference_verified' && !r.published_version && spec.agent023?.run_id!==runId) {
        validation.append(node('p','help','Проверено восстановление эталонов. Точное совпадение для любого нового текста этим не гарантируется.'));
        const answers={};
        for(const q of r.questions||[]) {
          const label=node('label','',q.question);const select=node('select');
          for(const [value,title] of [['','Выберите ответ'],['yes','Блок обязателен'],['no','Блок необязателен']]) {const option=node('option','',title);option.value=value;select.append(option);}
          label.append(select);validation.append(label);answers[q.role]=select;
          for(const evidence of q.evidence||[]) {
            validation.append(node('p','help',evidence.excerpt));
            const link=node('a','',`Показать в эталоне ${evidence.document}${evidence.page ? `, страница ${evidence.page}` : ''}`);
            link.href=`${api}/template-runs/${runId}/agent-preview/${evidence.document}/reference${evidence.page ? `#page=${evidence.page}` : ''}`;
            link.target='_blank';link.rel='noopener';validation.append(link);
          }
        }
        validation.append(button('Сохранить проверенный шаблон',async()=>{
          if(r.mode!=='automatic' && Object.values(answers).some(s=>!s.value)){message('Ответьте на вопросы об обязательных блоках.',true);return;}
          const result=await request(`/templates/${id}/approve-agent`,{method:'POST',body:JSON.stringify({run_id:runId,answers:Object.fromEntries(Object.entries(answers).filter(([,s])=>s.value).map(([r,s])=>[r,s.value==='yes']))})});
          await loadTemplates();await showTemplate(id);message(`Сохранена версия ${result.version}.`);
        },'button primary'));
      }
      if(['queued','running'].includes(run.status) && target.contains(validation)) setTimeout(()=>showRun(runId).catch(e=>message(e.message,true)),2000);
      return;
    }
    validation.replaceChildren(node('strong','',run.status==='passed' && r.acceptance_contract!=='production-roundtrip-022-v1' ? 'Старая проверка: рабочий шаблон не подтверждён' : (statusNames[run.status] || run.status)), node('p','',stageNames[r.stage] || 'Подготовка'));
    for (const [index,sample] of (r.samples || []).entries()) {
      const final=sample.attempts?.find(a=>a.strategy==='complete_property_catalogue');
      const compact=sample.attempts?.find(a=>a.strategy==='compact_role_profiles');
      if(final?.pixels) validation.append(node('p','',`Каталог свойств, образец ${index+1}: ${final.pixels.golden_pages} страниц; совпадение ${final.pixels.pixel_exact ? 'точное' : 'не достигнуто'}. Это отдельная проверка хранения свойств.`));
      if(compact?.status==='failed') validation.append(node('p','help','Упрощённые профили потеряли часть оформления. Полный каталог сохранён; применение к новой статье требует отдельной проверки.'));
      const runtime=sample.attempts?.find(a=>a.strategy==='production_roundtrip');
      for(const row of runtime?.rows || []) validation.append(node('p',row.status==='passed'?'':'error',`Рабочий сборщик (${row.input==='neutralized'?'текст без оформления':'исходный документ'}): ${row.pixels.matched_page_diagnostics.filter(p=>p.pixel_exact).length}/${row.pixels.golden_pages} страниц совпали; получено ${row.pixels.candidate_pages} страниц. ${row.status==='passed'?'Проверка пройдена.':'Шаблон не прошёл проверку.'}`));
      if(runtime?.rows?.length) for(const [mode,label] of [['reference','Исходный эталон PDF'],['original','Результат рабочего сборщика PDF'],['neutralized','Сборка из текста без оформления PDF']]) {const link=node('a','button',label);link.href=`${api}/template-runs/${runId}/comparison/${index+1}/${mode}`;link.target='_blank';link.rel='noopener';validation.append(link);}
      if(runtime?.code) validation.append(node('p','error',`Рабочий шаблон не проверен: ${runtime.code}`));
      if(final?.status==='passed') {
        const link=node('a','button','Посмотреть восстановленный образец'); link.href=`${api}/template-runs/${runId}/preview/${index+1}`; link.target='_blank'; link.rel='noopener'; validation.append(link);
      }
    }
    if(run.status==='passed' && r.acceptance_contract==='production-roundtrip-022-v1') {
      const link=node('a','button','Скачать полный каталог шаблона');link.href=`${api}/template-runs/${runId}/catalogue`;validation.append(link);
      validation.append(node('p','help','Точное восстановление образца подтверждает полноту извлечения. Оно не измеряет точность выбора оформления для нового текста.'));
    }
    for(const select of target.querySelectorAll('select[data-role]')) {const choice=r.recommendations?.[select.dataset.role]?.selected;if(!select.value && choice) select.value=choice;}
    if(r.code) validation.append(node('p','error',`Причина остановки: ${r.code}`));
    if(['queued','running'].includes(run.status) && target.isConnected && target.contains(validation)) setTimeout(()=>showRun(runId).catch(e=>message(e.message,true)),1800);
  }
  if(!spec.pending_agent) target.append(button('Проверить без внешней модели',async()=>{
    await request(`/templates/${id}/refine`,{method:'POST'}); await showTemplate(id);
  },'button primary'));
  const runs=await request(`/templates/${id}/runs`);if(runs.length) await showRun(runs[0].id);
  if (state.llm) {
    const consentLabel = node('label');
    const consent = node('input'); consent.type = 'checkbox';
    consentLabel.append(consent, document.createTextNode(' Разрешаю передать текст эталонов в OpenRouter для анализа ролей'));
    const contextLabel=node('label','','Дополнительные требования к шаблону (необязательно)');
    const context=node('textarea');context.dataset.templateContext='true';context.rows=3;context.maxLength=12000;contextLabel.append(context);
    const modeLabel=node('label','','Режим извлечения');const mode=node('select');
    for(const [value,text] of [['automatic','Автоматический — без обязательных ответов'],['assisted','С уточнениями — подтвердить требования перед сохранением']]) {const option=node('option','',text);option.value=value;mode.append(option);}modeLabel.append(mode);
    const analyze = button(item.approved ? 'Исправить по замечанию и проверить новую версию' : 'Создать и проверить шаблон', async () => {
      if (!consent.checked) { message('Для анализа нужно разрешение на отправку текста эталонов.', true); return; }
      analyze.disabled = true; target.setAttribute('aria-busy', 'true'); message('Модель анализирует эталоны. Это может занять несколько минут.');
      try { await request(`/templates/${id}/learn`, { method: 'POST', body: JSON.stringify({ consent_external: true,context:context.value,mode:mode.value,validation_job_id:target.querySelector('[data-validation-job]')?.value||null }) }); await showTemplate(id); message('Обучение запущено. Агент сравнит все страницы и доработает правила при ошибках.'); }
      catch (error) { message(`Анализ не завершён: ${error.message}`, true); }
      finally { analyze.disabled = false; target.removeAttribute('aria-busy'); }
    });
    const jobLabel=node('label','','ID документа с замечанием (необязательно)');const jobInput=node('input');jobInput.placeholder='Документ должен относиться к этому шаблону';jobInput.dataset.validationJob='true';jobLabel.append(jobInput);
    target.append(modeLabel,contextLabel,jobLabel,consentLabel,analyze);
  }
  if(item.approved && spec.agent023) {
    target.append(node('p','','Проверенный шаблон сохранён. Для оформления новых документов включите модель и разрешите передачу текста.'));
    const details=node('details');details.append(node('summary','','Уточнить обязательные блоки'));const answers={};
    details.append(node('p','help','Если блок встречался в эталоне, но отсутствует в новой статье, система спросит об этом. Здесь можно заранее указать, какие блоки обязательны или необязательны. Изменение создаст новую версию.'));
    for(const [role,description] of Object.entries(spec.agent023.roles)) {
      const label=node('label','',description);const select=node('select');
      for(const [value,text] of [['','Спрашивать при отсутствии'],['yes','Обязателен'],['no','Необязателен']]) {const option=node('option','',text);option.value=value;select.append(option);}
      if(role in spec.agent023.answers) select.value=spec.agent023.answers[role]?'yes':'no';
      label.append(select);details.append(label);answers[role]=select;
    }
    details.append(button('Сохранить требования',async()=>{
      await request(`/templates/${id}/requirements`,{method:'POST',body:JSON.stringify({expected_version:item.version,answers:Object.fromEntries(Object.entries(answers).filter(([,s])=>s.value).map(([r,s])=>[r,s.value==='yes']))})});
      await loadTemplates();await showTemplate(id);message('Требования сохранены в новой версии шаблона.');
    }));target.append(details);return;
  }
  if(spec.external_import && !item.approved) {
    const imported=spec.external_import;
    if(runs[0]?.id!==imported.run_id)target.append(button('Показать исходный отчёт импорта',()=>showRun(imported.run_id)));
    const latestTest=runs.find(row=>JSON.parse(row.report_json).schema==='external-import-test-037');
    if(latestTest)target.append(button('Показать последнее пробное оформление',()=>showRun(latestTest.id)));
    const latestVerification=runs.find(row=>JSON.parse(row.report_json).schema==='external-import-verification-037');
    if(latestVerification)target.append(button('Показать проверку эталонов',()=>showRun(latestVerification.id)));
    if(imported.training_conflicts)target.append(node('p','help','Пробное оформление заблокировано: сначала устраните противоречивые правила в семантической разметке и импортируйте новую версию.'));
    else if(state.llm) {
      const verify=node('div','review');verify.append(node('h4','','Проверить эталоны перед утверждением'));
      verify.append(node('p','help','Малая модель получит очищенные копии всех эталонов. Система сравнит роли, выделения, точные свойства DOCX и все страницы, затем проверит обнаружение намеренных ошибок. Это несколько вызовов модели — по одному на эталон.'));
      const verifyLabel=node('label'),verifyConsent=node('input');verifyConsent.type='checkbox';
      verifyLabel.append(verifyConsent,document.createTextNode(' Разрешаю передать очищенные эталоны в OpenRouter'));verify.append(verifyLabel);
      verify.append(button('Запустить проверку эталонов',async()=>{
        if(!verifyConsent.checked){message('Для проверки нужно разрешить отправку эталонов.',true);return;}
        await request(`/templates/${id}/verify-import`,{method:'POST',body:JSON.stringify({consent_external:true})});
        await showTemplate(id);message('Проверка эталонов запущена. Утверждение станет доступно только после точного совпадения.');
      },'button primary'));target.append(verify);
      const form=node('form','review');
      form.append(node('h4','','Проверить импорт на новом документе'));
      const label=node('label','','Новый DOCX для пробного оформления');
      const input=node('input');input.type='file';input.name='file';input.accept='.docx';input.required=true;label.append(input);form.append(label);
      const consentLabel=node('label');const consent=node('input');consent.type='checkbox';consent.name='consent_external';consent.value='true';consent.required=true;
      consentLabel.append(consent,document.createTextNode(' Разрешаю передать текст этого DOCX в OpenRouter'));form.append(consentLabel);
      form.append(node('p','help','Один вызов малой модели без автоматического исправления ответа. Даже удачный результат останется черновиком.'));
      const submit=node('button','button primary','Оформить пробный документ');submit.type='submit';form.append(submit);
      form.addEventListener('submit',async event=>{
        event.preventDefault();submit.disabled=true;
        try {await request(`/templates/${id}/test-import`,{method:'POST',body:new FormData(form)});
          message('Пробное оформление запущено. Проверьте результат и диагностику.');await showTemplate(id);
        } catch(error){message(`Пробное оформление не запущено: ${error.message}`,true);}
        finally{submit.disabled=false;}
      });
      target.append(form);
    }
    return;
  }
  if(runs[0] && JSON.parse(runs[0].report_json).schema==='teacher-student-023') return;
  if (item.approved && spec.extraction_validation?.status === 'passed' && spec.extraction_validation?.acceptance_contract === 'production-roundtrip-022-v1') {
    target.append(node('p', '', 'Версия утверждена и неизменяема. Она доступна для новых пакетов.'));
    return;
  }
  target.append(node('h4', '', 'Обязательные сведения'));
  const required = {};
  for (const role of ['title','authors','affiliation','city','email','abstract_problem','abstract_goal','abstract_results','abstract_practical','keywords']) {
    const label = node('label'); const input = node('input'); input.type = 'checkbox';
    input.checked = (spec.structure?.required || []).includes(role); required[role] = input;
    label.append(input, document.createTextNode(' '+roleName(role))); target.append(label);
  }
  const choices = {};
  for (const [role, variants] of Object.entries(spec.variants || {})) {
    const label = node('label', '', roleName(role));
    const select = node('select');
    select.setAttribute('aria-label', `Вариант оформления: ${roleName(role)}`);
    if (Object.keys(variants).length > 1) {
      const empty = node('option', '', 'Выберите вариант');
      empty.value = '';
      select.append(empty);
    }
    for (const [key, names] of Object.entries(variants)) {
      const option = node('option', '', `Вариант ${Object.keys(variants).indexOf(key)+1} · ${[...new Set(names)].join(', ')}`);
      option.value = key;
      select.append(option);
    }
    const recommendation=runs[0] ? JSON.parse(runs[0].report_json).recommendations?.[role]?.selected : null;
    if(spec.selected?.[role] && variants[spec.selected[role]]) select.value=spec.selected[role];
    else if(recommendation && variants[recommendation]) select.value=recommendation;
    select.dataset.role=role;
    choices[role] = select;
    target.append(label, select);
    const details = node('details'); details.append(node('summary', '', 'Свойства вариантов и исходные блоки'));
    for (const key of Object.keys(variants)) {
      const value = spec.styles?.[role]?.[key] || {};
      const raw = (value.pPr || '') + (value.rPr || '') + (value.section || '');
      const xml = new DOMParser().parseFromString('<properties>' + raw + '</properties>', 'application/xml');
      const properties = [...xml.querySelectorAll('*')].filter(e => e.attributes.length && !['pPr','rPr','sectPr'].includes(e.localName)).map(e => `${e.localName}: ${[...e.attributes].filter(a=>!a.name.startsWith('xmlns')).map(a=>`${a.localName}=${a.value}`).join(', ')}`).filter(t=>!t.endsWith(': '));
      const evidence = spec.samples.flatMap(s => s.observations.filter(o=>o.role===role && o.style_key===key).map(o=>`${s.name} / ${o.block_id}`));
      details.append(node('p', 'help', `${key}: ${properties.join('; ')}. Источники: ${evidence.join(', ') || [...new Set(variants[key])].join(', ')}`));
    }
    target.append(details);
  }
  target.append(button('Утвердить новую версию', async () => {
    message('Проверяю шаблон и все страницы. Результат появится после завершения цикла.');
    const selected = Object.fromEntries(Object.entries(choices).map(([role, select]) => [role, select.value]));
    if (Object.values(selected).some((value) => !value)) { message('Выберите вариант для каждой спорной роли.', true); return; }
    try {
      const result = await request(`/templates/${id}/approve`, { method: 'POST', body: JSON.stringify({ selected, required: Object.keys(required).filter(role=>required[role].checked) }) });
      message(`Утверждена версия ${result.version}.`);
      await loadTemplates();
      await showTemplate(id);
    } catch (error) { message(`Не удалось утвердить шаблон: ${error.message}`, true); }
  }, 'button primary'));
}
async function loadBatches() {
  const rows = await request('/batches'); const target = $('batch-history'); target.replaceChildren();
  if (!rows.length) { target.append(node('p', 'empty', 'Проверок пока нет. Загрузите документы, чтобы начать.')); return; }
  const { element, body } = table(['Дата', 'Шаблон', 'Документов', 'Действие']);
  for (const item of rows) {
    const row = node('tr');
    cell(row, new Date(item.created_at).toLocaleString('ru-RU'));
    cell(row, item.template_name);
    cell(row, String(item.job_count));
    cell(row, '').append(button('Открыть проверку', async () => {
      state.batchId = item.id;
      window.history.replaceState(null, '', `/history?batch=${encodeURIComponent(item.id)}`);
      await renderBatch(item.id);
    }));
    body.append(row);
  }
  target.append(element);
}
async function renderBatch(id) {
  const batch = await request(`/batches/${id}`);
  const target = $('batch-view');
  target.hidden = false;
  target.replaceChildren(node('h3', '', `Пакет ${id.slice(0, 8)}`));
  const counts = {};
  for (const job of batch.jobs) counts[job.status] = (counts[job.status] || 0) + 1;
  target.append(node('p', 'help', Object.entries(counts).map(([status, count]) => `${status}: ${count}`).join(' · ')));
  const { element, body } = table(['Документ', 'Статус', 'Вопросы', 'Ревизия', 'Действие']);
  for (const job of batch.jobs) {
    const row = node('tr');
    cell(row, job.source_name);
    cell(row, '').append(node('span', `badge ${job.status}`, jobStatus[job.status] || job.status));
    cell(row, String(job.report?.questions?.length || 0));
    cell(row, String(job.revision));
    cell(row, '').append(button('Проверить', () => renderJob(job.id)));
    body.append(row);
  }
  target.append(element);
  target.append(button('Создать ZIP-снимок', async () => {
    try {
      const result = await request(`/batches/${id}/exports`, { method: 'POST' });
      const ready = result.manifest.jobs.filter((job) => job.status === 'ready').length;
      message(`ZIP готов: ${ready} готовых DOCX из ${result.manifest.jobs.length}. Manifest содержит статус каждого.`);
      window.location.href = result.url;
    } catch (error) { message(`ZIP не создан: ${error.message}`, true); }
  }));
  if (batch.jobs.some((job) => ['queued', 'processing'].includes(job.status))) {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => renderBatch(id).catch((error) => message(error.message, true)), 1800);
  }
}
async function renderJob(id) {
  const job = await request(`/jobs/${id}`);
  $('job-panel').hidden = false;
  const target = $('job-view');
  target.className = '';
  target.replaceChildren();
  const heading = node('div', 'item');
  const top = node('div');
  top.append(node('h3', '', job.source_name), node('span', `badge ${job.status}`, jobStatus[job.status] || job.status));
  heading.append(top, node('p', '', `Ревизия ${job.revision}. Откройте PDF для проверки страниц.`));
  const visual=job.report?.visual_validation;
  if(visual) {
    const count=visual.final?.pages?.length || 0;
    heading.append(node('p','',`Визуальный контроль: ${visual.status==='passed' ? 'физические проверки пройдены' : 'нужна проверка'} · ${count} страниц.`));
    if(visual.final) {const preview=node('a','button','Открыть PDF');preview.href=`${api}/jobs/${id}/preview`;preview.target='_blank';preview.rel='noopener';heading.append(preview);}
    for(const issue of visual.final?.issues || []) heading.append(node('p','error',`Страница ${issue.page}: ${issue.code}`));
  }
  target.append(heading);
  const actions = node('div', 'actions');
  const links = [['source', 'Исходник'], ['report', 'Отчёт']];
  if (['draft', 'ready'].includes(job.status) && job.report?.result_available!==false) links.push(['draft', 'Черновик']);
  if (job.status === 'ready') links.push(['final', 'Готовый DOCX']);
  if (job.report?.editorial_blocks) links.push(['editorial', 'Редакторские заметки']);
  for (const [kind, label] of links) {
    const link = node('a', 'button', label);
    link.href = `${api}/jobs/${id}/files/${kind}`;
    actions.append(link);
  }
  target.append(actions);
  const grid = node('div', 'results-grid');
  const questionPane = node('div', 'questions');
  questionPane.append(node('h3', '', 'Что нужно проверить'));
  const questions = job.report?.questions || (job.status === 'error' ? [job.report?.code || 'Ошибка обработки'] : []);
  if (questions.length) {
    const list = node('ul');
    for (const text of questions) list.append(node('li', '', text));
    questionPane.append(list);
  } else questionPane.append(node('p', '', 'Блокирующих вопросов нет. Проверьте DOCX визуально.'));
  if(job.report?.schema==='application-023') {
    if(job.report.structure_moves?.length) {const details=node('details');details.append(node('summary','',`Переставлено блоков: ${job.report.structure_moves.length}`));const list=node('ul');for(const m of job.report.structure_moves)list.append(node('li','',`${roleName(m.role)}: позиция ${m.from+1} → ${m.to+1}`));details.append(list);questionPane.append(details);}
    if(job.report.unconfirmed_missing?.length)questionPane.append(node('p','help','В эталонах также встречались: '+job.report.unconfirmed_missing.map(roleName).join(', ')+'. Их обязательность не установлена.'));

    questionPane.append(node('p','help','Обязательность блоков можно уточнить в шаблоне. Недостающий текст добавьте в исходную статью и загрузите её снова; это будет отдельная обработка с моделью.'));
    questionPane.append(button('Открыть требования шаблона',()=>showTemplate(job.report.template_id)));
    target.append(questionPane);target.scrollIntoView({behavior:'smooth',block:'start'});return;
  }
  const suppliedInputs = {};
  const supplied = JSON.parse(job.supplied_json || '{}');
  for (const slot of [...new Set([...(job.report?.missing || []), ...Object.keys(supplied)])]) {
    const label = node('label', '', `Заполнить: ${roleName(slot)}`);
    const input = node('textarea'); input.maxLength = 10000; input.value = supplied[slot] || '';
    input.setAttribute('aria-label', `Сведения для ${roleName(slot)}`); suppliedInputs[slot] = input;
    questionPane.append(label, input);
  }
  const blockPane = node('div');
  blockPane.append(node('h3', '', 'Исходные блоки и роли'));
  const blocks = node('div', 'blocks');
  const selectors = {};
  for (const block of job.blocks) {
    const card = node('div', 'block');
    card.append(node('small', '', `${block.id} · ${block.kind}`), node('p', '', block.text || '(нет обычного текста)'));
    const select = node('select');
    select.setAttribute('aria-label', `Роль блока ${block.id}`);
    for (const role of [...['editorial'], ...['udc','title','authors','affiliation','city','email','abstract_heading','abstract_problem','abstract_goal','abstract_results','abstract_practical','abstract_remainder','keywords','body']]) {
      const option = node('option', '', roleName(role));
      option.value = role;
      select.append(option);
    }
    select.value = job.report?.assignments?.[block.id] || job.assignments?.[block.id] || 'body';
    selectors[block.id] = select;
    card.append(select);
    blocks.append(card);
  }
  blockPane.append(blocks);
  blockPane.append(button('Сохранить решения и собрать новую ревизию', async () => {
    try {
      const assignments = Object.fromEntries(Object.entries(selectors).map(([bid, select]) => [bid, select.value]));
      await request(`/jobs/${id}/decisions`, { method: 'PATCH', body: JSON.stringify({ expected_revision: job.revision, assignments, supplied: Object.fromEntries(Object.entries(suppliedInputs).filter(([,input])=>input.value.trim()).map(([slot,input])=>[slot,input.value])) }) });
      message('Новая ревизия собрана. Предыдущая сохранена.');
      await renderJob(id);
      if (state.batchId) await renderBatch(state.batchId);
    } catch (error) { message(`Решения не сохранены: ${error.message}`, true); }
  }, 'button primary'));
  grid.append(questionPane, blockPane);
  target.append(grid);
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
async function boot() {
  try {
    const config = await request('/config');
    state.csrf = config.csrf_token;
    state.llm = config.llm_enabled;
    $('mode').textContent = state.llm ? 'Модель доступна · с проверкой бюджета' : 'Локальная проверка · без модели';
    $('use-llm').disabled = !state.llm;
    $('external-consent').disabled = !state.llm;
    const exact = config.font_audit.exact;
    $('font-notice').textContent = exact ? 'Arial и Times New Roman обнаружены. Итоговый DOCX всё равно проверьте визуально.' : 'Точные Arial и Times New Roman пока не подтверждены. Результаты остаются черновиками.';
    if (!exact) $('font-notice').classList.add('warn');
    await loadTemplates();
    if (currentPage === 'history') {
      await loadBatches();
      const batch = new URLSearchParams(location.search).get('batch');
      if (batch) { state.batchId = batch; await renderBatch(batch); }
    }
    if (currentPage === 'templates') {
      const template = new URLSearchParams(location.search).get('template');
      if (template) await showTemplate(template);
    }
  } catch (error) { message(`Приложение недоступно: ${error.message}`, true); }
}
$('template-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type=submit]');
  submit.disabled = true;
  try {
    const consent=$('creation-consent').checked;
    if(!consent || !state.llm) {message('Для автоматического создания шаблона настройте модель и разрешите обработку эталонов.',true);return;}
    const result = await request('/templates', { method: 'POST', body: new FormData(form) });
    await request(`/templates/${result.id}/learn`,{method:'POST',body:JSON.stringify({consent_external:true,mode:'automatic'})});
    message('Агент начал проверку. Результат и все причины остановки появятся в карточке шаблона.');
    form.reset(); $('template-dialog').close();
    await loadTemplates();
    await showTemplate(result.id);
  } catch (error) { message(`Эталон не обработан: ${error.message}`, true); }
  finally { submit.disabled = false; }
});
$('semantic-import-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form=event.currentTarget;const submit=form.querySelector('button[type=submit]');
  submit.disabled=true;
  try {
    const result=await request('/templates/import-semantic',{method:'POST',body:new FormData(form)});
    form.reset();$('template-dialog').close();await loadTemplates();await showTemplate(result.id);
    message(`Разметка импортирована как черновик. Противоречий: ${result.report.training_conflicts}. Проверьте вопросы и правила.`);
  } catch(error) {message(`Импорт не выполнен: ${error.message}`,true);}
  finally {submit.disabled=false;}
});
$('batch-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type=submit]');
  submit.disabled = true;
  try {
    const result = await request('/batches', { method: 'POST', body: new FormData(form) });
    window.location.href = `/history?batch=${encodeURIComponent(result.id)}`;
  } catch (error) { message(`Пакет не принят: ${error.message}`, true); }
  finally { submit.disabled = false; }
});
const pageText = {
  templates: ['Шаблоны документов', 'Создавайте и проверяйте шаблоны оформления по эталонным DOCX.'],
  documents: ['Загрузить документы', 'Оформляйте новые DOCX по утверждённому шаблону.'],
  history: ['История проверок', 'Просматривайте результаты, замечания и предыдущие исправления.'],
};
$('page-title').textContent = pageText[currentPage][0];
$('page-description').textContent = pageText[currentPage][1];
document.title = `${pageText[currentPage][0]} — ArticleFlow`;
document.querySelector(`[data-view="${currentPage}"]`).hidden = false;
document.querySelector(`nav [data-page="${currentPage}"]`).setAttribute('aria-current', 'page');
$('create-template').addEventListener('click', () => { message(''); $('template-dialog').showModal(); $('import-name').focus(); });
$('close-template-dialog').addEventListener('click', () => $('template-dialog').close());
$('template-dialog').addEventListener('click', event => { if (event.target === $('template-dialog')) $('template-dialog').close(); });
$('experimental-extraction').addEventListener('click', () => {
  const form = $('template-form');
  form.hidden = !form.hidden;
  $('experimental-extraction').setAttribute('aria-expanded', String(!form.hidden));
  if (!form.hidden) $('template-name').focus();
});
boot();
