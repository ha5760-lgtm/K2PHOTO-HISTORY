// K2 PHOTO History - 라인 셋업 일일 작업이력

// ─── State ────────────────────────────────────────────
const state = {
    meta: { equipment: [], categories: [], authors: [] },
    selectedEquip: new Set(),
    category: 'SIMPLE',
    editingId: null,       // 입력 폼으로 수정 중인 기록 id (Daily Log 인라인 또는 팝업)
    dayLogs: [],
    historyLogs: [],
    charts: {},
    attachments: [],       // 입력 폼의 캡처 첨부
    aiUndo: null,
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
const catOf = (code) => state.meta.categories.find((c) => c.code === code) || { label: code, icon: 'bi-tag', color: '#64748b' };
const defaultCategory = () => state.meta.default_category || 'SIMPLE';
const catBadge = (code) => { const c = catOf(code); return `<span class="cat-badge" style="--cat:${c.color}"><i class="bi ${c.icon}"></i>${esc(c.label)}</span>`; };
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
const VIEW_TITLES = { history: 'Work History', daily: 'Daily Log', stats: 'Setup Dashboard', io: 'Import / Export', ai: 'AI Assistant' };
const DEFAULT_VIEW = 'history';
const currentView = () => Object.keys(VIEW_TITLES).find((v) => !$(`#view-${v}`).hidden) || DEFAULT_VIEW;

function switchView(view) {
    if (!VIEW_TITLES[view]) view = DEFAULT_VIEW;
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
    $('#importCategory').innerHTML = catOpts;
    $('#importCategory').value = defaultCategory();
    $('#filterEquip').innerHTML = `<option value="">전체</option><option value="${COMMON}">${COMMON}</option>` +
        state.meta.equipment.map((e) => `<option>${esc(e.name)}</option>`).join('');
}

function renderEquipChips() {
    const chip = (name, extra, inner) => `<span class="chip ${extra} ${state.selectedEquip.has(name) ? 'active' : ''}" data-equip="${esc(name)}" title="${esc(inner.title || '')}">${inner.html}</span>`;
    $('#equipChips').innerHTML = chip(COMMON, 'chip-common', { html: `<i class="bi bi-diagram-3"></i>${COMMON}`, title: '설비 공통 작업' }) +
        state.meta.equipment.map((e) => chip(e.name, e.category === 'Scanner' ? 'scanner' : '',
            { html: esc(e.name), title: `${e.vendor || ''} ${e.category || ''}` })).join('');
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

function setCategory(code, save = true) {
    state.category = code;
    $$('#categoryGrid .work-type-btn').forEach((b) => b.classList.toggle('active', b.dataset.category === code));
    if (save) saveDraft();
}

// ─── Entry form ───────────────────────────────────────
function updateDuration() {
    const m = minutesBetween($('#entryStart').value, $('#entryEnd').value);
    $('#durationDisplay').textContent = m == null ? '-' : fmtDur(m) || '0m';
    $('#entryWeekday').textContent = weekday($('#entryDate').value || today());
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
        attachment_ids: state.attachments.filter((a) => a.id).map((a) => a.id),
    };
}

function saveDraft() {
    if (state.editingId) return;
    const p = formPayload();
    const attachments = state.attachments.filter((a) => a.id).map(({ id, url, name }) => ({ id, url, name }));
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
    if (d.category) setCategory(d.category, false);
    state.attachments = (d.attachments || []).map((a) => ({ ...a, key: `a${a.id}`, status: 'done' }));
    renderAttachments();
    updateDuration();
}

function setEditUi(editing) {
    $('#entrySubmit').innerHTML = editing ? '<i class="bi bi-check-lg"></i> 수정 저장' : '<i class="bi bi-check-lg"></i> 저장';
    $('#entryCancelEdit').hidden = !editing || state.entryInModal;
    $('#entryDelete').hidden = !editing;
    $('#entrySubmitNext').hidden = editing || !state.entryInModal;
    $('#entryAiResult').hidden = true;
}

function clearForm(keepDate = true) {
    const date = $('#entryDate').value;
    $('#entryForm').reset();
    $('#entryDate').value = keepDate && date ? date : today();
    state.selectedEquip = new Set();
    setCategory(defaultCategory(), false);  // 수정 취소 시 임시보관을 덮어쓰지 않도록 저장하지 않음
    state.attachments = [];
    renderAttachments();
    renderEquipChips();
    updateDuration();
}

// 저장 완료 / 초기화: 폼과 임시보관 모두 비움
function resetForm(keepDate = true) {
    state.editingId = null;
    clearForm(keepDate);
    storage(DRAFT_KEY, null);
    setEditUi(false);
    renderDay();
}

// 수정 취소: 수정 전에 쓰던 임시보관 내용으로 복귀
function cancelEdit() {
    state.editingId = null;
    clearForm(false);
    restoreDraft();
    setEditUi(false);
    renderDay();
}

async function submitEntry(e, keepOpen = false) {
    e && e.preventDefault();
    const p = formPayload();
    if (!p.content.trim()) { $('#entryContent').focus(); toast('작업내용을 입력하세요', 'danger'); return; }
    if (!p.equipment.length) p.equipment = [COMMON];
    setIndicator('saving', '저장 중…');
    try {
        const wasEditing = !!state.editingId;
        if (wasEditing) {
            await api(`/api/logs/${state.editingId}`, { method: 'PUT', body: JSON.stringify(p) });
            toast('수정되었습니다');
        } else {
            await api('/api/logs', { method: 'POST', body: JSON.stringify(p) });
            toast('DB에 저장되었습니다');
        }
        resetForm();
        // 연속 입력: 다음 작업 시작시간 = 직전 종료시간
        if (!wasEditing && p.end_time) $('#entryStart').value = p.end_time;
        setIndicator('', `저장됨 ${new Date().toTimeString().slice(0, 5)}`);
        if (state.entryInModal && !keepOpen) entryModalObj.hide();
        else $('#entryContent').focus();
        refreshCurrent();
    } catch (err) {
        setIndicator('error', '저장 실패');
        toast(err.message, 'danger');
    }
}

function startEdit(log) {
    state.editingId = log.id;
    $('#entryDate').value = log.work_date;
    $('#entryStart').value = log.start_time || '';
    $('#entryEnd').value = log.end_time || '';
    $('#entryContent').value = log.content;
    $('#entrySummary').value = log.summary_auto ? '' : log.summary || '';
    state.selectedEquip = new Set(log.equipment_list);
    setCategory(log.category);
    state.attachments = log.attachments.map((a) => ({ ...a, key: `a${a.id}`, status: 'done' }));
    renderAttachments();
    renderEquipChips();
    updateDuration();
    setEditUi(true);
    renderDay();
    $('#entryContent').focus();
}

// ─── Entry popup (Work History 등에서 작업 입력) ──────
// Daily Log 의 #entryForm 을 그대로 팝업으로 옮겨 씀 → 입력 방식/단축키/임시보관이 동일
let entryModalObj;
function openEntryModal(log = null) {
    state.entryInModal = true;
    $('#entryModalBody').appendChild($('#entryForm'));
    if (log) startEdit(log);
    else if (state.editingId) cancelEdit();
    else setEditUi(false);
    updateDuration();
    $('#entryModalTitle').innerHTML = log
        ? `<i class="bi bi-pencil-square me-1"></i> Edit Work Log <small class="text-muted">${esc(log.work_date)}</small>`
        : '<i class="bi bi-plus-square me-1"></i> New Work Log <small class="text-muted">작업 입력</small>';
    entryModalObj = entryModalObj || new bootstrap.Modal('#entryModal');
    entryModalObj.show();
}

function onEntryModalHidden() {
    state.entryInModal = false;
    $('#entryHome').appendChild($('#entryForm'));
    if (state.editingId) cancelEdit(); else setEditUi(false);
}

function newLog() {
    if (currentView() === 'daily') {
        if (state.editingId) cancelEdit();
        $('#entryContent').focus();
    } else {
        openEntryModal();
    }
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
        const body = l.summary_auto ? l.content.split('\n').slice(1).join('\n').trim() : l.content;
        return `<div class="timeline-item ${state.editingId === l.id ? 'editing' : ''} ${state.freshIds && state.freshIds.has(l.id) ? 'fresh' : ''}">
            <div class="timeline-time">${l.start_time ? `${l.start_time}~${l.end_time || ''}` : '<span class="text-muted">시간 미입력</span>'}<small>${fmtDur(l.duration_min)}</small></div>
            <div>
                <div class="mb-1">${eqBadges(l.equipment_list)} ${catBadge(l.category)}</div>
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
        if (state.editingId === id) cancelEdit();
        if (state.entryInModal) entryModalObj.hide();
        refreshCurrent();
    } catch (err) { toast(err.message, 'danger'); }
}

function refreshCurrent() {
    const view = currentView();
    if (view === 'history') loadHistory();
    else if (view === 'stats') loadStats();
    else loadDay();
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
        return `<tr class="${first ? 'date-first' : ''}">
            <td class="date-cell">${first ? `${l.work_date.slice(5).replace('-', '/')}<small>${l.work_date.slice(0, 4)} (${weekday(l.work_date)})</small>` : ''}</td>
            <td class="font-mono">${l.start_time ? `${l.start_time}~${l.end_time || ''}` : '-'}<br><small class="text-muted">${fmtDur(l.duration_min)}</small></td>
            <td>${eqBadges(l.equipment_list)}</td>
            <td>${catBadge(l.category)}</td>
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

// ─── 캡처 붙여넣기 (Ctrl+V → 즉시 서버 저장) ─────────
let attSeq = 0;

function renderAttachments() {
    $('#entryAttachments').innerHTML = state.attachments.map((a) => `
        <div class="thumb ${a.status === 'uploading' ? 'uploading' : ''} ${a.status === 'failed' ? 'failed' : ''}" data-lightbox="${esc(a.url || a.localUrl)}" data-name="${esc(a.name || '')}" title="${esc(a.name || '')}">
            <img src="${esc(a.localUrl || a.url)}" alt="">
            ${a.status === 'done' ? '<span class="thumb-ok"><i class="bi bi-cloud-check"></i> 저장</span>' : ''}
            <button type="button" class="thumb-x" data-remove-att="${a.key}" title="삭제"><i class="bi bi-x-lg"></i></button>
        </div>`).join('');
}

async function uploadImages(files) {
    const images = [...files].filter((f) => f.type.startsWith('image/'));
    if (!images.length) return;
    // 기존 기록 수정 중이면 그 기록에 바로 연결 저장, 새 입력이면 저장 시 연결
    const logId = state.editingId;
    await Promise.all(images.map(async (file) => {
        const item = { key: `u${++attSeq}`, name: file.name, status: 'uploading', localUrl: URL.createObjectURL(file) };
        state.attachments.push(item);
        renderAttachments();
        const fd = new FormData();
        fd.append('file', file, file.name && file.name !== 'image.png' ? file.name : `capture.${(file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`);
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
        renderAttachments();
    }));
    saveDraft();
    if (logId) refreshCurrent();
    toast(logId ? '캡처가 기록에 바로 저장되었습니다' : '캡처가 서버에 저장되었습니다 (작업 저장 시 함께 연결)');
}

async function removeAttachment(key) {
    const item = state.attachments.find((a) => a.key === key);
    if (!item) return;
    if (item.id) {
        try { await api(`/api/attachments/${item.id}`, { method: 'DELETE' }); }
        catch (err) { toast(err.message, 'danger'); return; }
    }
    if (item.localUrl) URL.revokeObjectURL(item.localUrl);
    state.attachments = state.attachments.filter((a) => a !== item);
    renderAttachments();
    saveDraft();
    if (item.id && item.log_id) refreshCurrent();
}

// 입력 폼이 보이는 상태인가 (팝업 열림 또는 Daily Log 화면)
const entryActive = () => state.entryInModal || currentView() === 'daily';

function canPasteToEntry(target) {
    if (!entryActive() || $('#lightbox').classList.contains('show')) return false;
    // 다른 입력칸(검색/작성자 등)에서 붙여넣기는 무시, 폼 내부나 빈 곳이면 본문 첨부
    return !!target.closest('#entryForm') || !target.closest('input, textarea, select');
}

function clipboardImages(dt) {
    return [...(dt.items || [])].filter((i) => i.kind === 'file' && i.type.startsWith('image/')).map((i) => i.getAsFile()).filter(Boolean);
}

// ─── AI 정리 ──────────────────────────────────────────
const AI_FLASH = ['#entryContent', '#entrySummary', '#entryStart', '#entryEnd', '#equipChips', '#categoryGrid'];

function formValues() {
    return { content: $('#entryContent').value, summary: $('#entrySummary').value, category: state.category,
        equipment: [...state.selectedEquip], start_time: $('#entryStart').value, end_time: $('#entryEnd').value,
        work_date: $('#entryDate').value };
}

function setFormValues(v) {
    $('#entryContent').value = v.content; $('#entrySummary').value = v.summary;
    $('#entryStart').value = v.start_time || ''; $('#entryEnd').value = v.end_time || '';
    state.selectedEquip = new Set(v.equipment); setCategory(v.category); renderEquipChips(); updateDuration(); saveDraft();
}

async function runAi() {
    const cur = formValues();
    if (!cur.content.trim()) { toast('정리할 메모를 작업내용에 먼저 적어주세요', 'danger'); return; }
    const btn = $('[data-ai]');
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border"></span> 정리 중…';
    try {
        const r = await api('/api/ai/organize', { method: 'POST', body: JSON.stringify(cur) });
        state.aiUndo = cur;
        // 시간은 비어 있을 때만, 호기는 기존 선택 + AI 인식 결과 합집합, 분류는 AI 가 특정했을 때만 덮어씀
        const found = r.equipment.filter((e) => e !== COMMON);
        let equipment = cur.equipment.filter((e) => e !== COMMON);
        equipment = [...new Set([...equipment, ...found])];
        if (!equipment.length) equipment = cur.equipment.length || r.equipment.includes(COMMON) ? [COMMON] : [];
        setFormValues({
            ...cur,
            content: r.content,
            summary: r.summary,
            category: r.category !== defaultCategory() ? r.category : cur.category,
            equipment,
            start_time: cur.start_time || r.start_time || '',
            end_time: cur.end_time || r.end_time || '',
        });
        AI_FLASH.forEach((sel) => { const el = $(sel); el.classList.remove('ai-filled'); void el.offsetWidth; el.classList.add('ai-filled'); });
        const list = (title, items) => (items.length ? `<div class="mt-1"><b>${title}</b><ul>${items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul></div>` : '');
        const box = $('#entryAiResult');
        box.innerHTML = `<div class="ai-head"><i class="bi bi-stars"></i> AI 정리 완료
                <span class="text-muted fw-normal">· ${r.engine === 'llm' ? 'LLM' : '규칙 기반'}${r.warning ? ` (${esc(r.warning)})` : ''}</span>
                <button type="button" class="btn btn-sm btn-link ms-auto p-0" data-ai-undo><i class="bi bi-arrow-counterclockwise"></i> 되돌리기</button></div>
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

function undoAi() {
    if (!state.aiUndo) return;
    setFormValues(state.aiUndo);
    $('#entryAiResult').hidden = true;
    toast('AI 정리 전으로 되돌렸습니다');
}

// ─── 실시간 갱신 (5초 폴링) ───────────────────────────
async function pollVersion() {
    if (document.hidden) return;
    try {
        const { version } = await api('/api/version');
        $('#liveBadge').classList.remove('off');
        if (state.version && version !== state.version) {
            const view = currentView();
            if (view === 'daily') loadDay(true);
            else if (view === 'history') loadHistory();
            else if (view === 'stats') loadStats();
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
        return `<div class="cat-bar"><div class="cat-bar-head"><span><i class="bi ${cat.icon} me-1" style="color:${cat.color}"></i>${esc(cat.label)}</span><span class="text-muted">${c.count}건 · ${fmtHours(c.minutes)}</span></div>
            <div class="cat-bar-track"><div class="cat-bar-fill" style="width:${(c.count / max) * 100}%; background:${cat.color}"></div></div></div>`;
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
    renderThemePanel();
    if (currentView() === 'stats') loadStats();  // 차트 색 갱신
}

function renderThemePanel() {
    const T = window.K2Theme;
    if (!T) return;
    const cur = T.current();
    $('#accentSwatches').innerHTML = T.ACCENTS.map((a) =>
        `<button type="button" class="swatch ${a.hex === cur.accent ? 'active' : ''}" style="background:${a.hex}" data-accent="${a.hex}" title="${a.name}"></button>`).join('');
    $('#accentCustom').value = cur.accent;
    $('#accentHex').value = cur.accent;
    $('#sidebarStyles').innerHTML = T.SIDEBARS.map((s) =>
        `<button type="button" class="${s.key === cur.sidebar ? 'active' : ''}" data-sidebar-style="${s.key}">${s.label}</button>`).join('');
    const mode = document.documentElement.getAttribute('data-bs-theme');
    $$('#modeButtons [data-mode]').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
}

function setAccent(hex) {
    window.K2Theme.apply({ accent: hex });
    renderThemePanel();
    if (currentView() === 'stats') loadStats();
}

// ─── Init ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    applyTheme(storage('k2ph.theme') || 'light');
    $('.theme-panel').addEventListener('click', (e) => {
        const b = e.target.closest('[data-accent],[data-sidebar-style],[data-mode]');
        if (!b) return;
        if (b.dataset.accent) setAccent(b.dataset.accent);
        else if (b.dataset.sidebarStyle) { window.K2Theme.apply({ sidebar: b.dataset.sidebarStyle }); renderThemePanel(); }
        else if (b.dataset.mode) applyTheme(b.dataset.mode);
    });
    $('#accentCustom').addEventListener('input', (e) => setAccent(e.target.value));
    $('#accentHex').addEventListener('change', (e) => {
        const v = e.target.value.trim();
        if (/^#?[0-9a-f]{6}$/i.test(v)) setAccent(v.startsWith('#') ? v : `#${v}`);
        else { toast('#RRGGBB 형식으로 입력하세요', 'danger'); renderThemePanel(); }
    });
    $('#themeReset').addEventListener('click', () => {
        window.K2Theme.reset(); applyTheme('light');
        toast('기본 테마로 되돌렸습니다');
    });
    $('#globalAuthor').value = storage('k2ph.author') || '';
    $('#importYear').value = new Date().getFullYear();
    if (storage('k2ph.sidebar') === 'collapsed') $('#sidebar').classList.add('collapsed');

    // 이벤트 위임
    document.addEventListener('click', (e) => {
        const extra = e.target.closest('[data-remove-att],[data-lightbox],[data-ai],[data-ai-undo],[data-new-log]');
        if (extra) {
            const xs = extra.dataset;
            if (xs.removeAtt) { e.stopPropagation(); removeAttachment(xs.removeAtt); }
            else if (xs.lightbox) openLightbox(xs.lightbox, xs.name);
            else if ('newLog' in xs) newLog();
            else if ('aiUndo' in xs) undoAi();
            else if ('ai' in xs) runAi();
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
            updateDuration(); loadDay(); saveDraft();
        } else if (ds.editInline) startEdit(state.dayLogs.find((l) => l.id === +ds.editInline));
        else if (ds.edit) openEntryModal(state.historyLogs.find((l) => l.id === +ds.edit));
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
    $('#entryDate').addEventListener('change', () => { updateDuration(); loadDay(); });
    // 하이라이트 애니메이션은 1회만 (폼이 팝업↔Daily Log 로 이동할 때 재생되지 않도록)
    document.addEventListener('animationend', (e) => e.target.classList.remove('ai-filled', 'fresh'));
    $('#entryReset').addEventListener('click', () => resetForm());
    $('#entryCancelEdit').addEventListener('click', cancelEdit);
    $('#entrySubmitNext').addEventListener('click', (e) => submitEntry(e, true));
    $('#entryDelete').addEventListener('click', () => deleteLog(state.editingId));
    $('#entryModal').addEventListener('hidden.bs.modal', onEntryModalHidden);
    $('#entryModal').addEventListener('shown.bs.modal', () => $('#entryContent').focus());
    $('#copyDayConfluence').addEventListener('click', () => { const d = $('#entryDate').value; copyConfluence(`date_from=${d}&date_to=${d}`); });
    $('#copyConfluence').addEventListener('click', () => copyConfluence(historyParams()));
    $('#filterForm').addEventListener('submit', (e) => { e.preventDefault(); loadHistory(); });
    $('#filterReset').addEventListener('click', () => { $('#filterForm').reset(); loadHistory(); });
    $('#importPreview').addEventListener('click', () => runImport(true));
    $('#importRun').addEventListener('click', () => runImport(false));
    $('#globalAuthor').addEventListener('change', (e) => storage('k2ph.author', e.target.value.trim()));
    $('#themeToggle').addEventListener('click', () => {
        applyTheme(document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark');
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
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && entryActive()) submitEntry(e);
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#globalSearch').focus(); }
        if (e.altKey && e.key.toLowerCase() === 'a' && entryActive()) { e.preventDefault(); runAi(); }
        // N: 어디서든 작업 입력 (입력칸 밖에서)
        if (e.key.toLowerCase() === 'n' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.target.closest('input, textarea, select, [contenteditable]')
            && !document.querySelector('.modal.show')) { e.preventDefault(); newLog(); }
    });
    document.addEventListener('paste', (e) => {
        const files = clipboardImages(e.clipboardData);
        if (!files.length) return;
        // 엑셀/워드처럼 텍스트+이미지가 같이 오면 텍스트 붙여넣기를 우선
        if ((e.clipboardData.getData('text/plain') || '').trim()) return;
        if (!canPasteToEntry(e.target)) return;
        e.preventDefault();
        uploadImages(files);
    });
    $$('[data-drop]').forEach((zone) => {
        zone.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); zone.classList.add('drag-over'); } });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', (e) => {
            zone.classList.remove('drag-over');
            if (!e.dataTransfer.files.length) return;
            e.preventDefault();
            uploadImages(e.dataTransfer.files);
        });
    });
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
    switchView(location.hash.slice(1) || DEFAULT_VIEW);
});
