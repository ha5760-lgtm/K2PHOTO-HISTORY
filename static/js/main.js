// K2 PHOTO History - 라인 셋업 일일 작업이력

// ─── State ────────────────────────────────────────────
const state = {
    meta: { equipment: [], categories: [], authors: [] },
    selectedEquip: new Set(),
    category: 'ETC',
    editingId: null,       // 빠른 입력 폼으로 수정 중인 id
    modalId: null,         // 수정 모달 대상 id
    dayLogs: [],
    historyLogs: [],
    charts: {},
    attachments: { entry: [], edit: [] },   // 캡처 첨부 (scope 별)
    aiUndo: {},
    version: null,
};
const COMMON = window.COMMON || '공통';
const DRAFT_KEY = 'k2ph.draft';
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ─── Utils ────────────────────────────────────────────
const pad = (n) => String(n).padStart(2, '0');
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const today = () => isoDate(new Date());
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
const weekday = (s) => WEEKDAYS[new Date(s + 'T00:00:00').getDay()];
const fmtHours = (min) => (min ? `${Math.round((min / 60) * 10) / 10}h` : '0h');
const fmtDur = (min) => (min == null ? '' : min >= 60 ? `${Math.floor(min / 60)}h ${min % 60 ? (min % 60) + 'm' : ''}`.trim() : `${min}m`);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const catOf = (code) => state.meta.categories.find((c) => c.code === code) || { label: code, icon: 'bi-tag' };
const equipInfo = (name) => state.meta.equipment.find((e) => e.name === name);

function storage(key, value) {
    try {
        if (value === undefined) return localStorage.getItem(key);
        if (value === null) localStorage.removeItem(key);
        else localStorage.setItem(key, value);
    } catch (e) { return null; }
}

function highlight(text, q) {
    const safe = esc(text);
    if (!q) return safe;
    const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    return safe.replace(re, (m) => `<mark>${m}</mark>`);
}

function eqBadges(list) {
    return list.map((e) => {
        if (e === COMMON) return `<span class="eq-badge common">${COMMON}</span>`;
        const info = equipInfo(e);
        return `<span class="eq-badge ${info && info.category === 'Scanner' ? 'scanner' : ''}">${esc(e)}</span>`;
    }).join('');
}

function minutesBetween(s, e) {
    if (!s || !e) return null;
    const [sh, sm] = s.split(':').map(Number);
    const [eh, em] = e.split(':').map(Number);
    let d = eh * 60 + em - (sh * 60 + sm);
    return d < 0 ? d + 1440 : d;
}

function addMinutes(t, min) {
    const [h, m] = t.split(':').map(Number);
    const total = (h * 60 + m + min) % 1440;
    return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

let toastObj;
function toast(msg, type = 'success') {
    const el = $('#toast');
    el.className = `toast align-items-center border-0 text-bg-${type}`;
    $('#toastBody').textContent = msg;
    toastObj = toastObj || new bootstrap.Toast(el, { delay: 2200 });
    toastObj.show();
}

function setIndicator(mode, text) {
    const el = $('#saveIndicator');
    el.className = `save-indicator ${mode}`;
    const icon = { saving: 'bi-arrow-repeat', error: 'bi-cloud-slash', '': 'bi-cloud-check' }[mode];
    el.innerHTML = `<i class="bi ${icon}"></i> <span>${esc(text)}</span>`;
}

async function api(url, opts = {}) {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

// ─── Navigation ───────────────────────────────────────
const VIEW_TITLES = { daily: '일일 작업 입력', history: '작업 이력', stats: '셋업 현황', io: '가져오기 / 내보내기', ai: 'AI 활용' };

function switchView(view) {
    if (!VIEW_TITLES[view]) view = 'daily';
    $$('.view').forEach((v) => (v.hidden = v.id !== `view-${view}`));
    $$('.sidebar-nav-link').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
    $('#pageTitle').textContent = VIEW_TITLES[view];
    $('#sidebar').classList.remove('mobile-open');
    if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    if (view === 'daily') loadDay();
    if (view === 'history') loadHistory();
    if (view === 'stats') loadStats();
    if (view === 'ai') loadJsonlPreview();
}

// ─── Meta ─────────────────────────────────────────────
async function loadMeta() {
    state.meta = await api('/api/meta');
    $('#aiEngine').textContent = state.meta.ai_engine || '';
    renderEquipChips();
    const catOpts = state.meta.categories.map((c) => `<option value="${c.code}">${esc(c.label)}</option>`).join('');
    $('#filterCategory').innerHTML = `<option value="">전체</option>${catOpts}`;
    $('#editCategory').innerHTML = catOpts;
    $('#importCategory').innerHTML = catOpts;
    $('#importCategory').value = 'ETC';
    $('#filterEquip').innerHTML = `<option value="">전체</option><option value="${COMMON}">${COMMON}</option>` +
        state.meta.equipment.map((e) => `<option>${esc(e.name)}</option>`).join('');
}

function renderEquipChips() {
    const groups = {};
    state.meta.equipment.forEach((e) => (groups[e.category || '기타'] ||= []).push(e));
    let html = `<span class="chip chip-common ${state.selectedEquip.has(COMMON) ? 'active' : ''}" data-equip="${COMMON}"><i class="bi bi-diagram-3"></i>${COMMON}</span>`;
    Object.entries(groups).forEach(([g, list]) => {
        html += `<span class="chip-group-label">${esc(g)}</span>`;
        html += list.map((e) => `<span class="chip ${state.selectedEquip.has(e.name) ? 'active' : ''}" data-equip="${esc(e.name)}">${esc(e.name)} <small>${esc(e.vendor || '')}</small></span>`).join('');
    });
    $('#equipChips').innerHTML = html;
}

function toggleEquip(name) {
    if (name === COMMON) {
        state.selectedEquip = state.selectedEquip.has(COMMON) ? new Set() : new Set([COMMON]);
    } else {
        state.selectedEquip.delete(COMMON);
        state.selectedEquip.has(name) ? state.selectedEquip.delete(name) : state.selectedEquip.add(name);
    }
    renderEquipChips();
    saveDraft();
}

function setCategory(code) {
    state.category = code;
    $$('#categoryGrid .work-type-btn').forEach((b) => b.classList.toggle('active', b.dataset.category === code));
    saveDraft();
}

// ─── Entry form ───────────────────────────────────────
function updateDuration() {
    const m = minutesBetween($('#entryStart').value, $('#entryEnd').value);
    $('#durationDisplay').textContent = m == null ? '-' : fmtDur(m) || '0m';
}

function formPayload() {
    return {
        work_date: $('#entryDate').value,
        start_time: $('#entryStart').value || null,
        end_time: $('#entryEnd').value || null,
        equipment: [...state.selectedEquip],
        category: state.category,
        content: $('#entryContent').value,
        summary: $('#entrySummary').value,
        author: $('#globalAuthor').value,
        attachment_ids: state.attachments.entry.filter((a) => a.id).map((a) => a.id),
    };
}

function saveDraft() {
    if (state.editingId) return;
    const p = formPayload();
    const attachments = state.attachments.entry.filter((a) => a.id).map(({ id, url, name }) => ({ id, url, name }));
    storage(DRAFT_KEY, JSON.stringify({ ...p, author: undefined, attachment_ids: undefined, attachments }));
}

function restoreDraft() {
    let d = null;
    try { d = JSON.parse(storage(DRAFT_KEY) || 'null'); } catch (e) { d = null; }
    $('#entryDate').value = today();
    if (!d) return;
    $('#entryStart').value = d.start_time || '';
    $('#entryEnd').value = d.end_time || '';
    $('#entryContent').value = d.content || '';
    $('#entrySummary').value = d.summary || '';
    state.selectedEquip = new Set(d.equipment || []);
    if (d.category) setCategory(d.category);
    state.attachments.entry = (d.attachments || []).map((a) => ({ ...a, key: `a${a.id}`, status: 'done' }));
    renderAttachments('entry');
    updateDuration();
}

function resetForm(keepDate = true) {
    const date = $('#entryDate').value;
    $('#entryForm').reset();
    $('#entryDate').value = keepDate && date ? date : today();
    state.selectedEquip = new Set();
    state.editingId = null;
    $('#entrySubmit').innerHTML = '<i class="bi bi-check-lg"></i> 저장';
    $('#entryCancelEdit').hidden = true;
    state.attachments.entry = [];
    renderAttachments('entry');
    $('#entryAiResult').hidden = true;
    renderEquipChips();
    updateDuration();
    storage(DRAFT_KEY, null);
    renderDay();
}

async function submitEntry(e) {
    e && e.preventDefault();
    const p = formPayload();
    if (!p.content.trim()) { $('#entryContent').focus(); toast('작업내용을 입력하세요', 'danger'); return; }
    if (!p.equipment.length) p.equipment = [COMMON];
    setIndicator('saving', '저장 중…');
    try {
        const lastEnd = p.end_time;
        if (state.editingId) {
            await api(`/api/logs/${state.editingId}`, { method: 'PUT', body: JSON.stringify(p) });
            toast('수정되었습니다');
        } else {
            await api('/api/logs', { method: 'POST', body: JSON.stringify(p) });
            toast('DB에 저장되었습니다');
        }
        const wasEditing = !!state.editingId;
        resetForm();
        if (!wasEditing && lastEnd) $('#entryStart').value = lastEnd;
        setIndicator('', `저장됨 ${new Date().toTimeString().slice(0, 5)}`);
        await loadDay();
        $('#entryContent').focus();
    } catch (err) {
        setIndicator('error', '저장 실패');
        toast(err.message, 'danger');
    }
}

function startEditInForm(log) {
    state.editingId = log.id;
    $('#entryDate').value = log.work_date;
    $('#entryStart').value = log.start_time || '';
    $('#entryEnd').value = log.end_time || '';
    $('#entryContent').value = log.content;
    $('#entrySummary').value = log.summary_auto ? '' : log.summary || '';
    state.selectedEquip = new Set(log.equipment_list);
    setCategory(log.category);
    state.attachments.entry = log.attachments.map((a) => ({ ...a, key: `a${a.id}`, status: 'done' }));
    renderAttachments('entry');
    renderEquipChips();
    updateDuration();
    $('#entrySubmit').innerHTML = '<i class="bi bi-check-lg"></i> 수정 저장';
    $('#entryCancelEdit').hidden = false;
    renderDay();
    $('#entryContent').focus();
}

// ─── Daily view ───────────────────────────────────────
async function loadDay(markFresh = false) {
    const d = $('#entryDate').value || today();
    const prev = new Map(state.dayLogs.map((l) => [l.id, l.updated_at]));
    state.dayLogs = await api(`/api/logs?date_from=${d}&date_to=${d}`);
    state.freshIds = markFresh ? new Set(state.dayLogs.filter((l) => prev.get(l.id) !== l.updated_at).map((l) => l.id)) : new Set();
    renderDay();
}

function thumbsHtml(list) {
    if (!list || !list.length) return '';
    return `<div class="thumbs-sm">${list.map((a) => `<div class="thumb" data-lightbox="${esc(a.url)}" data-name="${esc(a.name || '')}"><img src="${esc(a.url)}" alt="" loading="lazy"></div>`).join('')}</div>`;
}

function renderDay() {
    const d = $('#entryDate').value || today();
    const logs = [...state.dayLogs].sort((a, b) => (a.start_time || '99').localeCompare(b.start_time || '99'));
    $('#entryWeekday').textContent = weekday(d);
    $('#dayTitle').textContent = d === today() ? `오늘 (${d.slice(5)} ${weekday(d)})` : `${d} (${weekday(d)})`;
    $('#dayCount').textContent = logs.length;
    $('#dayHours').textContent = fmtHours(logs.reduce((s, l) => s + (l.duration_min || 0), 0));
    $('#dayEquip').textContent = new Set(logs.flatMap((l) => l.equipment_list).filter((e) => e !== COMMON)).size;
    if (!logs.length) {
        $('#dayTimeline').innerHTML = '<div class="empty-state"><i class="bi bi-journal-plus"></i>아직 입력된 작업이 없습니다.<br><small>왼쪽에서 오늘 한 작업을 간단히 적어보세요.</small></div>';
        return;
    }
    $('#dayTimeline').innerHTML = logs.map((l) => {
        const c = catOf(l.category);
        const body = l.summary_auto ? l.content.split('\n').slice(1).join('\n').trim() : l.content;
        return `<div class="timeline-item ${state.editingId === l.id ? 'editing' : ''} ${state.freshIds && state.freshIds.has(l.id) ? 'fresh' : ''}">
            <div class="timeline-time">${l.start_time ? `${l.start_time}~${l.end_time || ''}` : '<span class="text-muted">시간 미입력</span>'}<small>${fmtDur(l.duration_min)}</small></div>
            <div>
                <div class="mb-1">${eqBadges(l.equipment_list)} <span class="cat-badge"><i class="bi ${c.icon}"></i>${esc(c.label)}</span></div>
                <div class="timeline-summary">${esc(l.summary)}${l.summary_auto ? '<span class="auto-tag">자동</span>' : ''}</div>
                ${body ? `<div class="timeline-content">${esc(body)}</div>` : ''}
                ${thumbsHtml(l.attachments)}
            </div>
            <div class="timeline-actions">
                <button class="btn btn-sm btn-light" data-edit-inline="${l.id}" title="수정"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-sm btn-light" data-copy="${l.id}" title="복제해서 새로 입력"><i class="bi bi-copy"></i></button>
                <button class="btn btn-sm btn-light text-danger" data-delete="${l.id}" title="삭제"><i class="bi bi-trash"></i></button>
            </div>
        </div>`;
    }).join('');
}

async function deleteLog(id) {
    if (!confirm('이 작업 기록을 삭제할까요?')) return;
    try {
        await api(`/api/logs/${id}`, { method: 'DELETE' });
        toast('삭제되었습니다');
        if (state.editingId === id) resetForm();
        refreshCurrent();
    } catch (err) { toast(err.message, 'danger'); }
}

function refreshCurrent() {
    const view = location.hash.slice(1) || 'daily';
    if (view === 'history') loadHistory(); else loadDay();
}

// ─── History view ─────────────────────────────────────
function historyParams() {
    const fd = new FormData($('#filterForm'));
    const p = new URLSearchParams();
    for (const [k, v] of fd.entries()) if (v) p.set(k, v);
    return p;
}

async function loadHistory() {
    const p = historyParams();
    state.historyLogs = await api(`/api/logs?${p}`);
    const q = p.get('q');
    let lastDate = null;
    const rows = state.historyLogs.map((l) => {
        const first = l.work_date !== lastDate;
        lastDate = l.work_date;
        const c = catOf(l.category);
        return `<tr class="${first ? 'date-first' : ''}">
            <td class="date-cell">${first ? `${l.work_date.slice(5).replace('-', '/')}<small>${l.work_date.slice(0, 4)} (${weekday(l.work_date)})</small>` : ''}</td>
            <td class="font-mono">${l.start_time ? `${l.start_time}~${l.end_time || ''}` : '-'}<br><small class="text-muted">${fmtDur(l.duration_min)}</small></td>
            <td>${eqBadges(l.equipment_list)}</td>
            <td><span class="cat-badge"><i class="bi ${c.icon}"></i>${esc(c.label)}</span></td>
            <td class="content-cell">${highlight(l.content, q)}${thumbsHtml(l.attachments)}</td>
            <td>${highlight(l.summary, q)}${l.summary_auto ? '<span class="auto-tag">자동</span>' : ''}</td>
            <td class="small">${esc(l.author || '')}</td>
            <td class="row-actions"><button class="btn btn-sm btn-light" data-edit="${l.id}"><i class="bi bi-pencil"></i></button></td>
        </tr>`;
    }).join('');
    $('#historyBody').innerHTML = rows || '<tr><td colspan="8"><div class="empty-state"><i class="bi bi-inbox"></i>조건에 맞는 기록이 없습니다.</div></td></tr>';
    const mins = state.historyLogs.reduce((s, l) => s + (l.duration_min || 0), 0);
    $('#historyCount').textContent = `${state.historyLogs.length}건 · 총 ${fmtHours(mins)}`;
}

function setRange(r) {
    const f = $('#filterForm');
    const now = new Date();
    if (r === 'all') { f.date_from.value = ''; f.date_to.value = ''; }
    else if (r === 'week') {
        const mon = new Date(now); mon.setDate(now.getDate() - ((now.getDay() + 6) % 7));
        f.date_from.value = isoDate(mon); f.date_to.value = today();
    } else {
        const from = new Date(now); from.setDate(now.getDate() - (Number(r) - 1));
        f.date_from.value = isoDate(from); f.date_to.value = today();
    }
    loadHistory();
}

// ─── Edit modal ───────────────────────────────────────
let modalObj;
function openEditModal(log) {
    state.modalId = log.id;
    $('#editDate').value = log.work_date;
    $('#editStart').value = log.start_time || '';
    $('#editEnd').value = log.end_time || '';
    $('#editEquip').value = log.equipment;
    $('#editCategory').value = log.category;
    $('#editContent').value = log.content;
    $('#editSummary').value = log.summary_auto ? '' : log.summary || '';
    $('#editSummary').placeholder = log.summary_auto ? `자동 요약: ${log.summary}` : '';
    state.attachments.edit = log.attachments.map((a) => ({ ...a, key: `a${a.id}`, status: 'done' }));
    renderAttachments('edit');
    $('#editAiResult').hidden = true;
    modalObj = modalObj || new bootstrap.Modal('#editModal');
    modalObj.show();
}

async function saveModal() {
    const body = {
        work_date: $('#editDate').value,
        start_time: $('#editStart').value || null,
        end_time: $('#editEnd').value || null,
        equipment: $('#editEquip').value,
        category: $('#editCategory').value,
        content: $('#editContent').value,
        summary: $('#editSummary').value,
    };
    try {
        await api(`/api/logs/${state.modalId}`, { method: 'PUT', body: JSON.stringify(body) });
        modalObj.hide();
        toast('수정되었습니다');
        refreshCurrent();
    } catch (err) { toast(err.message, 'danger'); }
}

// ─── 캡처 붙여넣기 (Ctrl+V → 즉시 서버 저장) ─────────
let attSeq = 0;
// entry 폼에서 기존 기록 수정 중이거나 수정 모달이면 해당 기록에 바로 연결 저장
const targetLogId = (scope) => (scope === 'edit' ? state.modalId : state.editingId);

function renderAttachments(scope) {
    const el = $(scope === 'edit' ? '#editAttachments' : '#entryAttachments');
    el.innerHTML = state.attachments[scope].map((a) => `
        <div class="thumb ${a.status === 'uploading' ? 'uploading' : ''} ${a.status === 'failed' ? 'failed' : ''}" data-lightbox="${esc(a.url || a.localUrl)}" data-name="${esc(a.name || '')}" title="${esc(a.name || '')}">
            <img src="${esc(a.localUrl || a.url)}" alt="">
            ${a.status === 'done' ? '<span class="thumb-ok"><i class="bi bi-cloud-check"></i> 저장</span>' : ''}
            <button type="button" class="thumb-x" data-remove-att="${scope}:${a.key}" title="삭제"><i class="bi bi-x-lg"></i></button>
        </div>`).join('');
}

function refreshLinked() {
    if (!$('#view-history').hidden) loadHistory(); else loadDay();
}

async function uploadImages(scope, files) {
    const images = [...files].filter((f) => f.type.startsWith('image/'));
    if (!images.length) return;
    await Promise.all(images.map(async (file) => {
        const item = { key: `u${++attSeq}`, name: file.name, status: 'uploading', localUrl: URL.createObjectURL(file) };
        state.attachments[scope].push(item);
        renderAttachments(scope);
        const fd = new FormData();
        fd.append('file', file, file.name && file.name !== 'image.png' ? file.name : `capture.${(file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`);
        const logId = targetLogId(scope);
        if (logId) fd.append('log_id', logId);
        setIndicator('saving', '캡처 업로드 중…');
        try {
            const res = await fetch('/api/attachments', { method: 'POST', body: fd });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            Object.assign(item, data, { status: 'done' });
            setIndicator('', `캡처 저장됨 ${new Date().toTimeString().slice(0, 5)}`);
        } catch (err) {
            item.status = 'failed';
            setIndicator('error', '업로드 실패');
            toast(`캡처 업로드 실패: ${err.message}`, 'danger');
        }
        renderAttachments(scope);
    }));
    if (scope === 'entry') saveDraft();
    if (targetLogId(scope)) refreshLinked();
    toast(targetLogId(scope) ? '캡처가 기록에 바로 저장되었습니다' : '캡처가 서버에 저장되었습니다 (작업 저장 시 함께 연결)');
}

async function removeAttachment(scope, key) {
    const list = state.attachments[scope];
    const item = list.find((a) => a.key === key);
    if (!item) return;
    if (item.id) {
        try { await api(`/api/attachments/${item.id}`, { method: 'DELETE' }); }
        catch (err) { toast(err.message, 'danger'); return; }
    }
    if (item.localUrl) URL.revokeObjectURL(item.localUrl);
    state.attachments[scope] = list.filter((a) => a !== item);
    renderAttachments(scope);
    if (scope === 'entry') saveDraft();
    if (item.id && item.log_id) refreshLinked();
}

function pasteScope(target) {
    if ($('#editModal').classList.contains('show')) return 'edit';
    if (!$('#view-daily').hidden) {
        // 다른 입력칸(검색/작성자 등)에서 붙여넣기는 무시, 폼 내부나 빈 곳이면 본문 첨부
        if (target.closest('#entryForm') || !target.closest('input, textarea, select')) return 'entry';
    }
    return null;
}

function clipboardImages(dt) {
    return [...(dt.items || [])].filter((i) => i.kind === 'file' && i.type.startsWith('image/')).map((i) => i.getAsFile()).filter(Boolean);
}

// ─── AI 정리 ──────────────────────────────────────────
const AI_FIELDS = {
    entry: {
        get: () => ({ content: $('#entryContent').value, summary: $('#entrySummary').value, category: state.category,
            equipment: [...state.selectedEquip], start_time: $('#entryStart').value, end_time: $('#entryEnd').value,
            work_date: $('#entryDate').value }),
        set: (v) => {
            $('#entryContent').value = v.content; $('#entrySummary').value = v.summary;
            $('#entryStart').value = v.start_time || ''; $('#entryEnd').value = v.end_time || '';
            state.selectedEquip = new Set(v.equipment); setCategory(v.category); renderEquipChips(); updateDuration(); saveDraft();
        },
        flash: ['#entryContent', '#entrySummary', '#entryStart', '#entryEnd', '#equipChips', '#categoryGrid'],
        box: '#entryAiResult',
    },
    edit: {
        get: () => ({ content: $('#editContent').value, summary: $('#editSummary').value, category: $('#editCategory').value,
            equipment: $('#editEquip').value.split(/[,\s]+/).filter(Boolean), start_time: $('#editStart').value,
            end_time: $('#editEnd').value, work_date: $('#editDate').value }),
        set: (v) => {
            $('#editContent').value = v.content; $('#editSummary').value = v.summary; $('#editCategory').value = v.category;
            $('#editEquip').value = v.equipment.join(', '); $('#editStart').value = v.start_time || ''; $('#editEnd').value = v.end_time || '';
        },
        flash: ['#editContent', '#editSummary', '#editCategory', '#editEquip', '#editStart', '#editEnd'],
        box: '#editAiResult',
    },
};

async function runAi(scope) {
    const f = AI_FIELDS[scope];
    const cur = f.get();
    if (!cur.content.trim()) { toast('정리할 메모를 작업내용에 먼저 적어주세요', 'danger'); return; }
    const btn = $(`[data-ai="${scope}"]`);
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border"></span> 정리 중…';
    try {
        const r = await api('/api/ai/organize', { method: 'POST', body: JSON.stringify(cur) });
        state.aiUndo[scope] = cur;
        // 시간은 비어 있을 때만, 호기는 기존 선택 + AI 인식 결과 합집합, 분류는 AI 가 특정했을 때만 덮어씀
        const found = r.equipment.filter((e) => e !== COMMON);
        let equipment = cur.equipment.filter((e) => e !== COMMON);
        equipment = [...new Set([...equipment, ...found])];
        if (!equipment.length) equipment = cur.equipment.length || r.equipment.includes(COMMON) ? [COMMON] : [];
        const next = {
            ...cur,
            content: r.content,
            summary: r.summary,
            category: r.category !== 'ETC' ? r.category : cur.category,
            equipment,
            start_time: cur.start_time || r.start_time || '',
            end_time: cur.end_time || r.end_time || '',
        };
        f.set(next);
        f.flash.forEach((sel) => { const el = $(sel); el.classList.remove('ai-filled'); void el.offsetWidth; el.classList.add('ai-filled'); });
        const list = (title, items) => (items.length ? `<div class="mt-1"><b>${title}</b><ul>${items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul></div>` : '');
        const box = $(f.box);
        box.innerHTML = `<div class="ai-head"><i class="bi bi-stars"></i> AI 정리 완료
                <span class="text-muted fw-normal">· ${r.engine === 'llm' ? 'LLM' : '규칙 기반'}${r.warning ? ` (${esc(r.warning)})` : ''}</span>
                <button type="button" class="btn btn-sm btn-link ms-auto p-0" data-ai-undo="${scope}"><i class="bi bi-arrow-counterclockwise"></i> 되돌리기</button></div>
            ${list('이슈', r.issues)}${list('후속 조치', r.next_actions)}
            <div class="text-muted mt-1">내용을 확인한 뒤 저장하세요.</div>`;
        box.hidden = false;
    } catch (err) {
        toast(`AI 정리 실패: ${err.message}`, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = label;
    }
}

function undoAi(scope) {
    const prev = state.aiUndo[scope];
    if (!prev) return;
    AI_FIELDS[scope].set(prev);
    $(AI_FIELDS[scope].box).hidden = true;
    toast('AI 정리 전으로 되돌렸습니다');
}

// ─── 실시간 갱신 (5초 폴링) ───────────────────────────
async function pollVersion() {
    if (document.hidden) return;
    try {
        const { version } = await api('/api/version');
        $('#liveBadge').classList.remove('off');
        if (state.version && version !== state.version) {
            if (!$('#view-daily').hidden) loadDay(true);
            else if (!$('#view-history').hidden) loadHistory();
            else if (!$('#view-stats').hidden) loadStats();
        }
        state.version = version;
    } catch (e) {
        $('#liveBadge').classList.add('off');
    }
}

let lightboxObj;
function openLightbox(url, name) {
    $('#lightboxImg').src = url;
    $('#lightboxOpen').href = url;
    $('#lightboxName').textContent = name || '';
    lightboxObj = lightboxObj || new bootstrap.Modal('#lightbox');
    lightboxObj.show();
}

// ─── Stats view ───────────────────────────────────────
async function loadStats() {
    const s = await api('/api/stats');
    $('#kTotal').textContent = s.total_count;
    $('#kTotalHours').textContent = fmtHours(s.total_minutes);
    $('#kWeek').textContent = `${s.week_count} / ${fmtHours(s.week_minutes)}`;
    $('#kMissing').textContent = s.missing_time_count;

    const css = getComputedStyle(document.documentElement);
    const primary = css.getPropertyValue('--primary').trim();
    const success = css.getPropertyValue('--success').trim();
    const textSec = css.getPropertyValue('--text-secondary').trim();
    const border = css.getPropertyValue('--border-color').trim();
    if (state.charts.daily) state.charts.daily.destroy();
    if (window.Chart) {
        state.charts.daily = new Chart($('#chartDaily'), {
            data: {
                labels: s.daily.map((d) => `${d.date.slice(5).replace('-', '/')}(${weekday(d.date)})`),
                datasets: [
                    { type: 'bar', label: '작업시간(h)', data: s.daily.map((d) => +(d.minutes / 60).toFixed(1)), backgroundColor: primary + 'cc', borderRadius: 4, yAxisID: 'y' },
                    { type: 'line', label: '건수', data: s.daily.map((d) => d.count), borderColor: success, backgroundColor: success, cubicInterpolationMode: 'monotone', yAxisID: 'y1' },
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { labels: { color: textSec, boxWidth: 12 } } },
                scales: {
                    x: { ticks: { color: textSec }, grid: { display: false } },
                    y: { position: 'left', ticks: { color: textSec }, grid: { color: border }, title: { display: true, text: '시간(h)', color: textSec } },
                    y1: { position: 'right', ticks: { color: textSec, precision: 0 }, grid: { display: false }, title: { display: true, text: '건수', color: textSec } },
                },
            },
        });
    }

    const max = Math.max(1, ...s.by_category.map((c) => c.count));
    $('#categoryBars').innerHTML = s.by_category.map((c) => {
        const cat = catOf(c.code);
        return `<div class="cat-bar"><div class="cat-bar-head"><span><i class="bi ${cat.icon} me-1"></i>${esc(cat.label)}</span><span class="text-muted">${c.count}건 · ${fmtHours(c.minutes)}</span></div>
            <div class="cat-bar-track"><div class="cat-bar-fill" style="width:${(c.count / max) * 100}%"></div></div></div>`;
    }).join('') || '<div class="empty-state">데이터 없음</div>';

    const byEq = Object.fromEntries(s.by_equipment.map((e) => [e.equipment, e]));
    const tiles = [COMMON, ...state.meta.equipment.map((e) => e.name)];
    $('#equipGrid').innerHTML = tiles.map((name) => {
        const e = byEq[name] || { count: 0, minutes: 0 };
        const info = equipInfo(name);
        return `<div class="equip-tile" data-goto-equip="${esc(name)}">
            <div class="name">${esc(name)}</div>
            <div class="meta">${info ? `${esc(info.vendor || '')} · ${esc(info.category || '')}` : '설비 공통 작업'}</div>
            <div class="num">${e.count}<small class="text-muted fs-6 fw-normal"> 건</small></div>
            <div class="meta">${fmtHours(e.minutes)}</div>
        </div>`;
    }).join('');
}

// ─── Import / Export ──────────────────────────────────
async function runImport(dryRun) {
    const text = $('#importText').value;
    if (!text.trim()) { toast('붙여넣을 표 내용이 없습니다', 'danger'); return; }
    try {
        const r = await api('/api/import', {
            method: 'POST',
            body: JSON.stringify({ text, dry_run: dryRun, year: $('#importYear').value, category: $('#importCategory').value, author: $('#globalAuthor').value }),
        });
        const errs = r.errors.length ? `<div class="alert alert-warning py-2 small mb-2">${r.errors.map(esc).join('<br>')}</div>` : '';
        const rows = r.preview.map((p) => `<tr><td>${p.work_date}</td><td class="font-mono">${p.start_time ? `${p.start_time}~${p.end_time}` : '-'}</td><td>${eqBadges(p.equipment.split(', '))}</td><td class="small">${esc(p.content)}</td><td class="small">${esc(p.summary)}</td></tr>`).join('');
        $('#importResult').innerHTML = `${errs}<div class="small mb-2">${dryRun ? `미리보기: <b>${r.parsed}</b>건 인식` : `<b class="text-success">${r.imported}건 저장 완료</b>`}</div>
            ${rows ? `<div class="table-responsive"><table class="table table-sm small mb-0"><thead><tr><th>날짜</th><th>시간</th><th>호기</th><th>내용</th><th>요약</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}`;
        if (!dryRun && r.imported) { toast(`${r.imported}건 가져왔습니다`); $('#importText').value = ''; }
    } catch (err) { toast(err.message, 'danger'); }
}

async function copyText(text, msg) {
    try { await navigator.clipboard.writeText(text); toast(msg); }
    catch (e) {
        const ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); ta.remove(); toast(msg);
    }
}

async function copyConfluence(params) {
    const res = await fetch(`/api/export/confluence?${params}`);
    await copyText(await res.text(), 'Confluence 표 마크업이 복사되었습니다 (Insert ▸ Markup 에 붙여넣기)');
}

async function loadJsonlPreview() {
    const res = await fetch('/api/export.jsonl?limit=5');
    const text = await res.text();
    $('#jsonlPreview').textContent = text.trim()
        ? text.trim().split('\n').map((l) => JSON.stringify(JSON.parse(l), null, 2)).join('\n\n')
        : '아직 데이터가 없습니다.';
}

// ─── Theme / Sidebar ──────────────────────────────────
function applyTheme(t) {
    document.documentElement.setAttribute('data-bs-theme', t);
    $('#themeToggle').innerHTML = t === 'dark'
        ? '<i class="bi bi-sun"></i><span class="theme-toggle-label">Light</span>'
        : '<i class="bi bi-moon-stars"></i><span class="theme-toggle-label">Dark</span>';
    storage('k2ph.theme', t);
}

// ─── Init ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    applyTheme(storage('k2ph.theme') || 'light');
    $('#globalAuthor').value = storage('k2ph.author') || '';
    $('#importYear').value = new Date().getFullYear();
    if (storage('k2ph.sidebar') === 'collapsed') $('#sidebar').classList.add('collapsed');

    // 이벤트 위임
    document.addEventListener('click', (e) => {
        const extra = e.target.closest('[data-remove-att],[data-lightbox],[data-ai],[data-ai-undo]');
        if (extra) {
            const xs = extra.dataset;
            if (xs.removeAtt) { e.stopPropagation(); const [sc, key] = xs.removeAtt.split(':'); removeAttachment(sc, key); }
            else if (xs.lightbox) openLightbox(xs.lightbox, xs.name);
            else if (xs.ai) runAi(xs.ai);
            else if (xs.aiUndo) undoAi(xs.aiUndo);
            return;
        }
        const t = e.target.closest('[data-view],[data-equip],[data-category],[data-dur],[data-time-preset],[data-date-shift],[data-edit],[data-edit-inline],[data-copy],[data-delete],[data-range],[data-goto-equip],[data-export]');
        if (!t) return;
        const ds = t.dataset;
        if (ds.view) { e.preventDefault(); switchView(ds.view); }
        else if (ds.equip) toggleEquip(ds.equip);
        else if (ds.category) setCategory(ds.category);
        else if (ds.dur) {
            const start = $('#entryStart').value || addMinutes(new Date().toTimeString().slice(0, 5), -Number(ds.dur));
            $('#entryStart').value = start;
            $('#entryEnd').value = addMinutes(start, Number(ds.dur));
            updateDuration(); saveDraft();
        } else if (ds.timePreset === 'now') {
            const now = new Date().toTimeString().slice(0, 5);
            if (!$('#entryStart').value) $('#entryStart').value = now; else $('#entryEnd').value = now;
            updateDuration(); saveDraft();
        } else if (ds.timePreset === 'day') {
            $('#entryStart').value = '08:00'; $('#entryEnd').value = '17:00'; updateDuration(); saveDraft();
        } else if (ds.dateShift) {
            const d = new Date(($('#entryDate').value || today()) + 'T00:00:00');
            if (ds.dateShift === 'today') $('#entryDate').value = today();
            else { d.setDate(d.getDate() + Number(ds.dateShift)); $('#entryDate').value = isoDate(d); }
            loadDay(); saveDraft();
        } else if (ds.editInline) startEditInForm(state.dayLogs.find((l) => l.id === +ds.editInline));
        else if (ds.edit) openEditModal(state.historyLogs.find((l) => l.id === +ds.edit));
        else if (ds.copy) {
            const l = state.dayLogs.find((x) => x.id === +ds.copy);
            resetForm();
            state.selectedEquip = new Set(l.equipment_list); setCategory(l.category); renderEquipChips();
            $('#entryContent').value = l.content; $('#entryContent').focus(); saveDraft();
        } else if (ds.delete) deleteLog(+ds.delete);
        else if (ds.range) setRange(ds.range);
        else if (ds.gotoEquip) {
            const f = $('#filterForm'); f.reset(); f.equipment.value = ds.gotoEquip; switchView('history');
        } else if (ds.export) { e.preventDefault(); location.href = `${ds.export}?${historyParams()}`; }
    });

    $('#entryForm').addEventListener('submit', submitEntry);
    $('#entryForm').addEventListener('input', saveDraft);
    ['#entryStart', '#entryEnd'].forEach((s) => $(s).addEventListener('change', updateDuration));
    $('#entryDate').addEventListener('change', loadDay);
    $('#entryReset').addEventListener('click', () => resetForm());
    $('#entryCancelEdit').addEventListener('click', () => resetForm());
    $('#copyDayConfluence').addEventListener('click', () => { const d = $('#entryDate').value; copyConfluence(`date_from=${d}&date_to=${d}`); });
    $('#copyConfluence').addEventListener('click', () => copyConfluence(historyParams()));
    $('#filterForm').addEventListener('submit', (e) => { e.preventDefault(); loadHistory(); });
    $('#filterReset').addEventListener('click', () => { $('#filterForm').reset(); loadHistory(); });
    $('#editSave').addEventListener('click', saveModal);
    $('#editDelete').addEventListener('click', () => { modalObj.hide(); deleteLog(state.modalId); });
    $('#importPreview').addEventListener('click', () => runImport(true));
    $('#importRun').addEventListener('click', () => runImport(false));
    $('#globalAuthor').addEventListener('change', (e) => storage('k2ph.author', e.target.value.trim()));
    $('#themeToggle').addEventListener('click', () => {
        applyTheme(document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark');
        if (!$('#view-stats').hidden) loadStats();
    });
    $('#sidebarToggle').addEventListener('click', () => {
        const c = $('#sidebar').classList.toggle('collapsed');
        storage('k2ph.sidebar', c ? 'collapsed' : 'open');
    });
    $('#mobileSidebarToggle').addEventListener('click', () => $('#sidebar').classList.toggle('mobile-open'));
    $('#addEquipLink').addEventListener('click', async (e) => {
        e.preventDefault();
        const name = prompt('추가할 설비호기 (예: PAA7308)');
        if (!name) return;
        try { await api('/api/equipment', { method: 'POST', body: JSON.stringify({ name }) }); await loadMeta(); toast(`${name.toUpperCase()} 추가됨`); }
        catch (err) { toast(err.message, 'danger'); }
    });
    $('#globalSearch').addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        const f = $('#filterForm'); f.reset(); f.q.value = e.target.value; switchView('history');
    });
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !$('#view-daily').hidden) submitEntry(e);
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#globalSearch').focus(); }
    });
    document.addEventListener('keydown', (e) => {
        if (!e.altKey || e.key.toLowerCase() !== 'a') return;
        const sc = $('#editModal').classList.contains('show') ? 'edit' : !$('#view-daily').hidden ? 'entry' : null;
        if (sc) { e.preventDefault(); runAi(sc); }
    });
    document.addEventListener('paste', (e) => {
        const files = clipboardImages(e.clipboardData);
        if (!files.length) return;
        // 엑셀/워드처럼 텍스트+이미지가 같이 오면 텍스트 붙여넣기를 우선
        if ((e.clipboardData.getData('text/plain') || '').trim()) return;
        const scope = pasteScope(e.target);
        if (!scope) return;
        e.preventDefault();
        uploadImages(scope, files);
    });
    $$('[data-drop]').forEach((zone) => {
        zone.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); zone.classList.add('drag-over'); } });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', (e) => {
            zone.classList.remove('drag-over');
            if (!e.dataTransfer.files.length) return;
            e.preventDefault();
            uploadImages(zone.dataset.drop, e.dataTransfer.files);
        });
    });
    $('#editModal').addEventListener('hidden.bs.modal', () => { state.modalId = null; });
    setInterval(pollVersion, 5000);
    pollVersion();
    window.addEventListener('hashchange', () => switchView(location.hash.slice(1)));

    try {
        await loadMeta();
    } catch (err) {
        setIndicator('error', 'DB 연결 실패');
    }
    restoreDraft();
    renderEquipChips();
    switchView(location.hash.slice(1) || 'daily');
});
