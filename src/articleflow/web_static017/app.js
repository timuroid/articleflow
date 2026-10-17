const api = '/api/v017';
const state = { csrf: '', templates: [], batchId: null, timer: null };
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
  item.addEventListener('click', onClick);
  return item;
};
const message = (value, error = false) => {
  const target = $('message');
  target.textContent = value;
  target.className = error ? 'message error' : 'message';
  target.hidden = !value;
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
  for (const item of state.templates) {
    const card = node('div', 'item');
    const top = node('div');
    top.append(node('strong', '', item.name), node('span', `badge ${item.approved ? 'ready' : 'draft'}`, item.approved ? `Версия ${item.version} утверждена` : 'Требует проверки'));
    card.append(top);
    const count = item.spec.samples?.length || 0;
    card.append(node('p', '', `${count} эталонных DOCX · ${Object.keys(item.spec.conflicts || {}).length} спорных ролей`));
    card.append(button('Открыть шаблон', () => showTemplate(item.id)));
    list.append(card);
    if (item.approved) {
      const option = node('option', '', `${item.name} · версия ${item.version}`);
      option.value = item.id;
      select.append(option);
    }
  }
  if (!rows.length) list.append(node('p', 'help', 'Шаблонов пока нет. Начните с эталонного DOCX.'));
}
async function showTemplate(id) {
  const item = await request(`/templates/${id}`);
  const target = $('template-review');
  target.hidden = false;
  target.replaceChildren(node('h3', '', `${item.name} · версия ${item.version}`));
  const spec = item.spec;
  target.append(node('p', '', `Эталонов: ${spec.samples.length}. При разных вариантах оформления выберите правило вручную.`));
  if (item.approved) {
    target.append(node('p', '', 'Версия утверждена и неизменяема. Она доступна для новых пакетов.'));
    return;
  }
  const choices = {};
  for (const [role, variants] of Object.entries(spec.variants || {})) {
    const label = node('label', '', `Роль: ${role}`);
    const select = node('select');
    select.setAttribute('aria-label', `Вариант оформления для ${role}`);
    if (Object.keys(variants).length > 1) {
      const empty = node('option', '', 'Выберите вариант');
      empty.value = '';
      select.append(empty);
    }
    for (const [key, names] of Object.entries(variants)) {
      const option = node('option', '', `${key} · ${[...new Set(names)].join(', ')}`);
      option.value = key;
      select.append(option);
    }
    choices[role] = select;
    target.append(label, select);
  }
  target.append(button('Утвердить новую версию', async () => {
    const selected = Object.fromEntries(Object.entries(choices).map(([role, select]) => [role, select.value]));
    if (Object.values(selected).some((value) => !value)) { message('Выберите вариант для каждой спорной роли.', true); return; }
    try {
      const result = await request(`/templates/${id}/approve`, { method: 'POST', body: JSON.stringify({ selected }) });
      message(`Утверждена версия ${result.version}.`);
      await loadTemplates();
      await showTemplate(id);
    } catch (error) { message(`Не удалось утвердить шаблон: ${error.message}`, true); }
  }, 'button primary'));
}
async function renderBatch(id) {
  const batch = await request(`/batches/${id}`);
  const target = $('batch-view');
  target.replaceChildren(node('h3', '', `Пакет ${id.slice(0, 8)}`));
  const counts = {};
  for (const job of batch.jobs) counts[job.status] = (counts[job.status] || 0) + 1;
  target.append(node('p', 'help', Object.entries(counts).map(([status, count]) => `${status}: ${count}`).join(' · ')));
  for (const job of batch.jobs) {
    const card = node('div', 'item');
    const top = node('div');
    top.append(node('strong', '', job.source_name), node('span', `badge ${job.status}`, job.status));
    card.append(top);
    const count = job.report?.questions?.length || 0;
    card.append(node('p', '', `${count} вопросов · ревизия ${job.revision}`));
    card.append(button('Проверить', () => renderJob(job.id)));
    target.append(card);
  }
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
  const target = $('job-view');
  target.className = '';
  target.replaceChildren();
  const heading = node('div', 'item');
  const top = node('div');
  top.append(node('h3', '', job.source_name), node('span', `badge ${job.status}`, job.status));
  heading.append(top, node('p', '', `Ревизия ${job.revision}. Структурный просмотр не заменяет проверку страниц в Word.`));
  target.append(heading);
  const actions = node('div', 'actions');
  const links = [['source', 'Исходник'], ['report', 'Отчёт']];
  if (['draft', 'ready'].includes(job.status)) links.push(['draft', 'Черновик']);
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
      const option = node('option', '', role);
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
      await request(`/jobs/${id}/decisions`, { method: 'PATCH', body: JSON.stringify({ expected_revision: job.revision, assignments }) });
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
    const exact = config.font_audit.exact;
    $('font-notice').textContent = exact ? 'Arial и Times New Roman обнаружены. Итоговый DOCX всё равно проверьте визуально.' : 'Точные Arial и Times New Roman пока не подтверждены. Результаты остаются черновиками.';
    if (!exact) $('font-notice').classList.add('warn');
    await loadTemplates();
  } catch (error) { message(`Приложение недоступно: ${error.message}`, true); }
}
$('template-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector('button[type=submit]');
  submit.disabled = true;
  try {
    const result = await request('/templates', { method: 'POST', body: new FormData(event.currentTarget) });
    message('Наблюдения сохранены. Проверьте варианты и утвердите шаблон.');
    event.currentTarget.reset();
    await loadTemplates();
    await showTemplate(result.id);
  } catch (error) { message(`Эталон не обработан: ${error.message}`, true); }
  finally { submit.disabled = false; }
});
$('batch-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector('button[type=submit]');
  submit.disabled = true;
  try {
    const result = await request('/batches', { method: 'POST', body: new FormData(event.currentTarget) });
    state.batchId = result.id;
    message('Пакет принят. Статусы появятся ниже.');
    event.currentTarget.reset();
    await renderBatch(result.id);
  } catch (error) { message(`Пакет не принят: ${error.message}`, true); }
  finally { submit.disabled = false; }
});
boot();
