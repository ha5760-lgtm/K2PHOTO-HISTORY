"""
K2 PHOTO History - 라인 셋업 일일 작업이력 관리
Confluence 표(완료여부 | 날짜/근무 | 호기명 | 작업명 | EDM·CTTTM LINK | 작업내용: 1.현상 2.조치사항 3.결론)를
간단 입력 → SQLite 자동 저장 → AI 활용(JSONL export) 으로 대체
"""
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
import sqlite3
import os
import csv
import io
import re
import json as _json
import uuid
from datetime import datetime, timedelta, date
import llm
from sections import SECTIONS, SECTION_KEYS, parse_sections, compose_content

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.environ.get('K2PH_DB', os.path.join(BASE_DIR, 'k2photo_history.db'))
UPLOAD_DIR = os.environ.get('K2PH_UPLOADS', os.path.join(BASE_DIR, 'uploads'))
IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 캡처 1장 기준 넉넉히 20MB

COMMON = '공통'

# Naming: P(Photo) + vendor(T=TEL, A=ASML, S=SEMES, C=CANON) + type + 73(line) + unit (fdc-dashboard 와 동일)
DEFAULT_EQUIPMENT = [
    'PTA7302', 'PTH7304', 'PTH7301',  # TEL spinner
    'PSH7306',                         # SEMES spinner
    'PAA7302', 'PAH7304',              # ASML scanner
    'PCH7306',                         # CANON scanner
]
VENDOR_MAP = {'T': 'TEL', 'A': 'ASML', 'S': 'SEMES', 'C': 'CANON'}

# 작업 분류 (code, 표시명, 아이콘, 색상)
CATEGORIES = [
    ('DOWN', '설비 Down', 'bi-exclamation-octagon', '#ef476f'),
    ('SETUP', '셋업', 'bi-tools', '#4361ee'),
    ('PM', 'PM', 'bi-calendar-check', '#118ab2'),
    ('COMMON', '공통업무', 'bi-people', '#64748b'),
    ('PROCESS', '공정개선', 'bi-graph-up-arrow', '#06a77d'),
    ('MINOR_STOP', '순간정지', 'bi-pause-circle', '#f59e0b'),
    ('SIMPLE', '간단작업', 'bi-check2-square', '#8b5cf6'),
]
CATEGORY_CODES = {c[0] for c in CATEGORIES}
DEFAULT_CATEGORY = 'SIMPLE'

# 완료여부
STATUSES = [('ongoing', 'On-going'), ('closed', 'Closed')]
STATUS_CODES = {c for c, _ in STATUSES}
DEFAULT_STATUS = 'closed'

# 근무조 (code, 시작, 종료) — 3교대. 시작시간으로 자동 판정
SHIFTS = [('DAY', '06:00', '14:00'), ('SW', '14:00', '22:00'), ('GY', '22:00', '06:00')]
SHIFT_CODES = {c for c, *_ in SHIFTS}
SHIFT_ALIASES = {'DAY': 'DAY', 'D': 'DAY', '주간': 'DAY', 'SW': 'SW', 'S': 'SW', '스윙': 'SW',
                 'GY': 'GY', 'G': 'GY', '야간': 'GY', 'NIGHT': 'GY'}

# 이전 버전(셋업 단계 세분류) → 새 분류 자동 변환
LEGACY_CATEGORY_MAP = {
    'MOVE_IN': 'SETUP', 'HOOKUP': 'SETUP', 'POWER_ON': 'SETUP', 'SW': 'SETUP', 'CAL': 'SETUP', 'QUAL': 'SETUP',
    'MEETING': 'COMMON', 'ETC': 'SIMPLE',
}


def vendor_of(name):
    return VENDOR_MAP.get(name[1:2]) if name else None


def category_of(name):
    v = vendor_of(name)
    if v in ('TEL', 'SEMES'): return 'Spinner'
    if v in ('ASML', 'CANON'): return 'Scanner'
    return ''


# ─── DB ───────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            vendor TEXT,
            category TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS work_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            duration_min INTEGER,
            equipment TEXT NOT NULL DEFAULT '공통',
            category TEXT NOT NULL DEFAULT 'SIMPLE',
            status TEXT NOT NULL DEFAULT 'closed',
            shift TEXT,
            title TEXT,
            title_auto INTEGER DEFAULT 0,
            link TEXT,
            symptom TEXT,
            action TEXT,
            result TEXT,
            content TEXT NOT NULL,
            summary TEXT,
            summary_auto INTEGER DEFAULT 0,
            author TEXT,
            tags TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_logs_date ON work_logs(work_date DESC);
        CREATE INDEX IF NOT EXISTS idx_logs_equipment ON work_logs(equipment);
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER,
            filename TEXT NOT NULL,
            original_name TEXT,
            mime TEXT,
            size INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attach_log ON attachments(log_id);
    ''')
    for old, new in LEGACY_CATEGORY_MAP.items():
        conn.execute('UPDATE work_logs SET category = ? WHERE category = ?', (new, old))
    migrate_structured(conn)
    if conn.execute('SELECT COUNT(*) FROM equipment').fetchone()[0] == 0:
        conn.executemany('INSERT INTO equipment (name, vendor, category) VALUES (?, ?, ?)',
                         [(n, vendor_of(n), category_of(n)) for n in DEFAULT_EQUIPMENT])
    conn.commit()
    conn.close()


NEW_COLUMNS = {'status': "TEXT NOT NULL DEFAULT 'closed'", 'shift': 'TEXT', 'title': 'TEXT', 'title_auto': 'INTEGER DEFAULT 0',
               'link': 'TEXT', 'symptom': 'TEXT', 'action': 'TEXT', 'result': 'TEXT'}


def migrate_structured(conn):
    """이전 버전(내용+요약) DB → 완료여부/근무/작업명/현상·조치·결론 구조로 변환. 여러 번 실행해도 안전."""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(work_logs)').fetchall()}
    for name, ddl in NEW_COLUMNS.items():
        if name not in cols:
            conn.execute(f'ALTER TABLE work_logs ADD COLUMN {name} {ddl}')
    for r in conn.execute('SELECT id, content, summary, summary_auto, start_time FROM work_logs WHERE title IS NULL').fetchall():
        parsed = parse_sections(r['content']) or {'symptom': (r['content'] or '').strip()}
        parts = {k: parsed.get(k, '') for k in SECTION_KEYS}
        conn.execute('UPDATE work_logs SET title = ?, title_auto = ?, shift = COALESCE(shift, ?), '
                     'symptom = ?, action = ?, result = ? WHERE id = ?',
                     (r['summary'] or auto_summary(r['content']), r['summary_auto'] or 0, shift_of(r['start_time']),
                      parts['symptom'], parts['action'], parts['result'], r['id']))


# ─── Helpers ──────────────────────────────────────────

def shift_of(start_time):
    """HH:MM → DAY(06~14) / SW(14~22) / GY(22~06)."""
    m = re.fullmatch(r'(\d{1,2}):\d{2}', start_time or '')
    if not m:
        return None
    h = int(m[1])
    for code, start, end in SHIFTS:
        s, e = int(start[:2]), int(end[:2])
        if (s <= h < e) if s < e else (h >= s or h < e):
            return code
    return None


def normalize_shift(value):
    return SHIFT_ALIASES.get((value or '').strip().upper()) or SHIFT_ALIASES.get((value or '').strip())



def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def calc_duration(start, end):
    """HH:MM ~ HH:MM → 분. 자정 넘김(야간) 허용."""
    try:
        s = datetime.strptime(start, '%H:%M')
        e = datetime.strptime(end, '%H:%M')
    except (TypeError, ValueError):
        return None
    diff = int((e - s).total_seconds() // 60)
    return diff + 1440 if diff < 0 else diff


def auto_summary(content, limit=60):
    """요약 미입력 시 작업내용 첫 줄로 자동 요약 (추후 LLM 요약으로 교체)."""
    first = next((l.strip(' -•*\t') for l in (content or '').splitlines() if l.strip()), '')
    return first if len(first) <= limit else first[:limit - 1] + '…'


def normalize_equipment(value):
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r'[,/\s]+', value or '')
    items = [i.strip().upper() if i.strip() != COMMON else COMMON for i in items if i.strip()]
    if not items or COMMON in items:
        return COMMON
    return ', '.join(dict.fromkeys(items))


def row_to_dict(r):
    d = dict(r)
    d['equipment_list'] = [e.strip() for e in d['equipment'].split(',')]
    d.setdefault('attachments', [])
    return d


def attachment_dict(a):
    return {'id': a['id'], 'log_id': a['log_id'], 'url': f"/uploads/{a['filename']}",
            'name': a['original_name'], 'size': a['size']}


def attach_files(conn, rows):
    """rows(list of dict) 에 attachments 채움."""
    ids = [r['id'] for r in rows]
    if not ids:
        return rows
    by_log = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for a in conn.execute(f"SELECT * FROM attachments WHERE log_id IN ({','.join('?' * len(chunk))}) ORDER BY id",
                              chunk).fetchall():
            by_log.setdefault(a['log_id'], []).append(attachment_dict(a))
    for r in rows:
        r['attachments'] = by_log.get(r['id'], [])
    return rows


def fetch_log(conn, log_id):
    row = conn.execute('SELECT * FROM work_logs WHERE id = ?', (log_id,)).fetchone()
    return attach_files(conn, [row_to_dict(row)])[0] if row else None


def link_attachments(conn, log_id, ids):
    ids = [int(i) for i in (ids or []) if str(i).isdigit()]
    if ids:
        conn.execute(f"UPDATE attachments SET log_id = ? WHERE id IN ({','.join('?' * len(ids))}) "
                     "AND (log_id IS NULL OR log_id = ?)", [log_id, *ids, log_id])


def remove_attachment_files(conn, where, params):
    for a in conn.execute(f'SELECT filename FROM attachments WHERE {where}', params).fetchall():
        try:
            os.remove(os.path.join(UPLOAD_DIR, a['filename']))
        except OSError:
            pass
    conn.execute(f'DELETE FROM attachments WHERE {where}', params)


def section_parts(data):
    """payload → 현상/조치/결론. 구조 필드가 없으면 content(이전 형식/가져오기)를 해석."""
    if any(k in data for k in SECTION_KEYS):
        return {k: (data.get(k) or '').strip() for k in SECTION_KEYS}
    content = (data.get('content') or '').strip()
    parsed = parse_sections(content) or {'symptom': content}
    return {k: parsed.get(k, '') for k in SECTION_KEYS}


def validate_payload(data):
    errors = []
    try:
        date.fromisoformat(data.get('work_date') or '')
    except ValueError:
        errors.append('날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)')
    parts = section_parts(data)
    if not (data.get('title') or data.get('summary') or '').strip() and not any(parts.values()):
        errors.append('작업명 또는 작업내용을 입력하세요')
    if data.get('category') and data['category'] not in CATEGORY_CODES:
        errors.append('알 수 없는 분류입니다')
    if data.get('status') and data['status'] not in STATUS_CODES:
        errors.append('완료여부는 ongoing / closed 중 하나입니다')
    if data.get('shift') and not normalize_shift(data['shift']):
        errors.append('근무는 DAY / SW / GY 중 하나입니다')
    for k in ('start_time', 'end_time'):
        v = data.get(k)
        if v and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', v):
            errors.append(f'{k} 형식이 올바르지 않습니다 (HH:MM)')
    return errors


def build_record(data):
    parts = section_parts(data)
    title = (data.get('title') if 'title' in data else data.get('summary') or '') or ''
    title = title.strip()
    start, end = data.get('start_time') or None, data.get('end_time') or None
    duration = data.get('duration_min')
    if start and end:
        duration = calc_duration(start, end)
    auto_title = auto_summary(parts['symptom'] or parts['action'] or parts['result'])
    rec = {
        'work_date': data['work_date'],
        'status': data.get('status') if data.get('status') in STATUS_CODES else DEFAULT_STATUS,
        'shift': normalize_shift(data.get('shift')) or shift_of(start),
        'start_time': start,
        'end_time': end,
        'duration_min': int(duration) if duration not in (None, '') else None,
        'equipment': normalize_equipment(data.get('equipment')),
        'category': data.get('category') or DEFAULT_CATEGORY,
        'title': title or auto_title,
        'title_auto': 0 if title else 1,
        'link': (data.get('link') or '').strip() or None,
        **parts,
        'content': compose_content(parts),
        'author': (data.get('author') or '').strip() or None,
        'tags': (data.get('tags') or '').strip() or None,
    }
    # 이전 버전 호환 컬럼
    rec['summary'], rec['summary_auto'] = rec['title'], rec['title_auto']
    return rec


def query_logs(args):
    sql = 'SELECT * FROM work_logs WHERE 1=1'
    params = []
    if args.get('date_from'):
        sql += ' AND work_date >= ?'; params.append(args['date_from'])
    if args.get('date_to'):
        sql += ' AND work_date <= ?'; params.append(args['date_to'])
    if args.get('equipment'):
        eq = args['equipment']
        if eq == COMMON:
            sql += ' AND equipment = ?'; params.append(COMMON)
        else:
            sql += " AND (',' || REPLACE(equipment, ' ', '') || ',') LIKE ?"; params.append(f'%,{eq},%')
    if args.get('category'):
        sql += ' AND category = ?'; params.append(args['category'])
    if args.get('status'):
        sql += ' AND status = ?'; params.append(args['status'])
    if args.get('shift'):
        sql += ' AND shift = ?'; params.append(args['shift'])
    if args.get('author'):
        sql += ' AND author = ?'; params.append(args['author'])
    if args.get('q'):
        sql += ' AND (title LIKE ? OR content LIKE ? OR link LIKE ? OR tags LIKE ?)'
        params += [f"%{args['q']}%"] * 4
    # 같은 날짜 안에서는 근무 GY → SW → DAY (최근 순), 그다음 시작시간
    sql += (" ORDER BY work_date DESC, CASE shift WHEN 'GY' THEN 0 WHEN 'SW' THEN 1 WHEN 'DAY' THEN 2 ELSE 3 END,"
            " COALESCE(start_time, '') DESC, id DESC LIMIT ?")
    params.append(min(int(args.get('limit') or 500), 5000))
    conn = get_db()
    rows = attach_files(conn, [row_to_dict(r) for r in conn.execute(sql, params).fetchall()])
    conn.close()
    return rows


# ─── Pages ────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', categories=CATEGORIES, common=COMMON,
                           default_category=DEFAULT_CATEGORY, shifts=SHIFTS)


# ─── Meta ─────────────────────────────────────────────

@app.route('/api/meta')
def api_meta():
    conn = get_db()
    equipment = [dict(r) for r in conn.execute(
        'SELECT * FROM equipment WHERE is_active = 1 ORDER BY category DESC, name').fetchall()]
    authors = [r[0] for r in conn.execute(
        'SELECT DISTINCT author FROM work_logs WHERE author IS NOT NULL ORDER BY author').fetchall()]
    conn.close()
    return jsonify({
        'equipment': equipment,
        'authors': authors,
        'categories': [{'code': c, 'label': l, 'icon': i, 'color': col} for c, l, i, col in CATEGORIES],
        'default_category': DEFAULT_CATEGORY,
        'statuses': [{'code': c, 'label': l} for c, l in STATUSES],
        'default_status': DEFAULT_STATUS,
        'shifts': [{'code': c, 'start': st, 'end': en} for c, st, en in SHIFTS],
        'sections': [{'key': k, 'label': l} for k, l in SECTIONS],
        'common': COMMON,
        'ai_engine': llm.engine_name(),
        'ai_enabled': llm.is_enabled(),
    })


@app.route('/api/equipment', methods=['POST'])
def api_equipment_create():
    name = ((request.get_json(silent=True) or {}).get('name') or '').strip().upper()
    if not name or name == COMMON:
        return jsonify({'error': '호기명을 입력하세요'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO equipment (name, vendor, category) VALUES (?, ?, ?)',
                     (name, vendor_of(name), category_of(name)))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': '이미 등록된 호기입니다'}), 409
    conn.close()
    return jsonify({'name': name}), 201


# ─── Work Logs ────────────────────────────────────────

@app.route('/api/logs')
def api_logs():
    return jsonify(query_logs(request.args))


@app.route('/api/logs', methods=['POST'])
def api_logs_create():
    data = request.get_json(silent=True) or {}
    errors = validate_payload(data)
    if errors:
        return jsonify({'error': ' / '.join(errors)}), 400
    rec = build_record(data)
    ts = now_iso()
    rec['created_at'] = rec['updated_at'] = ts
    conn = get_db()
    cur = conn.execute(
        f"INSERT INTO work_logs ({', '.join(rec)}) VALUES ({', '.join('?' * len(rec))})",
        list(rec.values()))
    link_attachments(conn, cur.lastrowid, data.get('attachment_ids'))
    conn.commit()
    log = fetch_log(conn, cur.lastrowid)
    conn.close()
    return jsonify(log), 201


@app.route('/api/logs/<int:log_id>', methods=['PUT'])
def api_logs_update(log_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    row = conn.execute('SELECT * FROM work_logs WHERE id = ?', (log_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    merged = {**dict(row), **{k: v for k, v in data.items() if k != 'attachment_ids'}}
    # 작업명이 자동 생성 상태였다면 바뀐 내용 기준으로 다시 생성
    if 'title' not in data and 'summary' not in data and row['title_auto']:
        merged['title'] = ''
    elif 'title' not in data and 'summary' in data:
        merged['title'] = data['summary']
    # 이전 형식(content 만) 수정 요청이면 구조 필드를 content 에서 다시 해석
    if 'content' in data and not any(k in data for k in SECTION_KEYS):
        for k in SECTION_KEYS:
            merged.pop(k, None)
    errors = validate_payload(merged)
    if errors:
        conn.close()
        return jsonify({'error': ' / '.join(errors)}), 400
    rec = build_record(merged)
    rec['updated_at'] = now_iso()
    conn.execute(f"UPDATE work_logs SET {', '.join(f'{k} = ?' for k in rec)} WHERE id = ?",
                 [*rec.values(), log_id])
    link_attachments(conn, log_id, data.get('attachment_ids'))
    conn.commit()
    log = fetch_log(conn, log_id)
    conn.close()
    return jsonify(log)


@app.route('/api/logs/<int:log_id>', methods=['DELETE'])
def api_logs_delete(log_id):
    conn = get_db()
    cur = conn.execute('DELETE FROM work_logs WHERE id = ?', (log_id,))
    if cur.rowcount:
        remove_attachment_files(conn, 'log_id = ?', [log_id])
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'deleted': log_id})


# ─── Attachments (캡처 붙여넣기) ──────────────────────

@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename, max_age=86400)


@app.route('/api/attachments', methods=['POST'])
def api_attachment_upload():
    """Ctrl+V 캡처 즉시 업로드. log_id 를 주면 기존 기록에 바로 연결(저장), 없으면 입력 중 임시 첨부."""
    f = request.files.get('file')
    if not f:
        return jsonify({'error': '파일이 없습니다'}), 400
    mime = f.mimetype or ''
    ext = (f.filename.rsplit('.', 1)[-1].lower() if '.' in (f.filename or '') else mime.split('/')[-1]).replace('jpeg', 'jpg')
    if not mime.startswith('image/') or ext not in IMAGE_EXTS | {'jpg'}:
        return jsonify({'error': '이미지 파일만 붙여넣을 수 있습니다'}), 400
    log_id = request.form.get('log_id', type=int)
    conn = get_db()
    if log_id and not conn.execute('SELECT 1 FROM work_logs WHERE id = ?', (log_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'not found'}), 404
    sub = datetime.now().strftime('%Y%m')
    os.makedirs(os.path.join(UPLOAD_DIR, sub), exist_ok=True)
    filename = f'{sub}/{uuid.uuid4().hex}.{ext}'
    path = os.path.join(UPLOAD_DIR, filename)
    f.save(path)
    original = f.filename if f.filename and f.filename not in ('image.png', 'blob') else \
        f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    cur = conn.execute('INSERT INTO attachments (log_id, filename, original_name, mime, size, created_at) '
                       'VALUES (?, ?, ?, ?, ?, ?)',
                       (log_id, filename, original, mime, os.path.getsize(path), now_iso()))
    if log_id:
        conn.execute('UPDATE work_logs SET updated_at = ? WHERE id = ?', (now_iso(), log_id))
    conn.commit()
    a = conn.execute('SELECT * FROM attachments WHERE id = ?', (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify(attachment_dict(a)), 201


@app.route('/api/attachments/<int:att_id>', methods=['DELETE'])
def api_attachment_delete(att_id):
    conn = get_db()
    a = conn.execute('SELECT * FROM attachments WHERE id = ?', (att_id,)).fetchone()
    if not a:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    remove_attachment_files(conn, 'id = ?', [att_id])
    if a['log_id']:
        conn.execute('UPDATE work_logs SET updated_at = ? WHERE id = ?', (now_iso(), a['log_id']))
    conn.commit()
    conn.close()
    return jsonify({'deleted': att_id})


@app.route('/api/version')
def api_version():
    """실시간 갱신용: 다른 사람이 입력/수정/삭제하면 값이 바뀜 (프론트 5초 폴링)."""
    conn = get_db()
    r = conn.execute('SELECT COUNT(*), COALESCE(MAX(updated_at), \'\'), COALESCE(SUM(id), 0) FROM work_logs').fetchone()
    a = conn.execute('SELECT COUNT(*), COALESCE(MAX(id), 0) FROM attachments WHERE log_id IS NOT NULL').fetchone()
    conn.close()
    return jsonify({'version': f'{r[0]}-{r[1]}-{r[2]}-{a[0]}-{a[1]}'})


# ─── AI 정리 ──────────────────────────────────────────

@app.route('/api/ai/organize', methods=['POST'])
def api_ai_organize():
    """메모(현상 칸에 대충 적은 내용 등) → 작업명 / 1.현상 2.조치사항 3.결론 / 완료여부 / 근무 / 분류 / 호기 / 링크 자동 기입."""
    data = request.get_json(silent=True) or {}
    filled = [(label, (data.get(k) or '').strip()) for k, label in SECTIONS if (data.get(k) or '').strip()]
    if len(filled) > 1:
        memo = '\n'.join(f'[{label}] {text}' for label, text in filled)
    else:
        memo = filled[0][1] if filled else (data.get('content') or '').strip()
    if data.get('title'):
        memo = f"[작업명] {data['title'].strip()}\n{memo}".strip()
    if not memo:
        return jsonify({'error': '정리할 작업내용을 먼저 입력하세요'}), 400
    conn = get_db()
    known = [r[0] for r in conn.execute('SELECT name FROM equipment WHERE is_active = 1').fetchall()]
    conn.close()
    result = llm.organize(memo, {
        'work_date': data.get('work_date'),
        'equipment': data.get('equipment') or [],
        'category': data.get('category'),
        'start_time': data.get('start_time'),
        'known_equipment': known,
        'categories': [(c, l) for c, l, *_ in CATEGORIES],
        'default_category': DEFAULT_CATEGORY,
        'common': COMMON,
    })
    result['shift'] = result.get('shift') or shift_of(result.get('start_time') or data.get('start_time'))
    return jsonify(result)


# ─── Stats ────────────────────────────────────────────

@app.route('/api/stats')
def api_stats():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    since = (today - timedelta(days=13)).isoformat()
    conn = get_db()
    q = lambda sql, *p: conn.execute(sql, p).fetchall()
    total = q('SELECT COUNT(*), COALESCE(SUM(duration_min),0) FROM work_logs')[0]
    today_row = q('SELECT COUNT(*), COALESCE(SUM(duration_min),0) FROM work_logs WHERE work_date = ?',
                  today.isoformat())[0]
    week_row = q('SELECT COUNT(*), COALESCE(SUM(duration_min),0) FROM work_logs WHERE work_date >= ?',
                 week_start.isoformat())[0]
    daily = {r[0]: {'count': r[1], 'minutes': r[2]} for r in q(
        'SELECT work_date, COUNT(*), COALESCE(SUM(duration_min),0) FROM work_logs '
        'WHERE work_date >= ? GROUP BY work_date', since)}
    by_category = [dict(code=r[0], count=r[1], minutes=r[2]) for r in q(
        'SELECT category, COUNT(*), COALESCE(SUM(duration_min),0) FROM work_logs GROUP BY category ORDER BY 2 DESC')]
    eq_counts = {}
    for r in q('SELECT equipment, duration_min FROM work_logs WHERE work_date >= ?', since):
        for e in r[0].split(','):
            e = e.strip()
            c = eq_counts.setdefault(e, {'equipment': e, 'count': 0, 'minutes': 0})
            c['count'] += 1
            c['minutes'] += r[1] or 0
    no_time = q('SELECT COUNT(*) FROM work_logs WHERE duration_min IS NULL')[0][0]
    ongoing = q("SELECT COUNT(*) FROM work_logs WHERE status = 'ongoing'")[0][0]
    by_shift = {r[0]: r[1] for r in q('SELECT shift, COUNT(*) FROM work_logs WHERE work_date >= ? GROUP BY shift', since)}
    conn.close()
    days = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    return jsonify({
        'total_count': total[0], 'total_minutes': total[1],
        'today_count': today_row[0], 'today_minutes': today_row[1],
        'week_count': week_row[0], 'week_minutes': week_row[1],
        'missing_time_count': no_time,
        'ongoing_count': ongoing,
        'by_shift': [{'shift': c, 'count': by_shift.get(c, 0)} for c, *_ in SHIFTS],
        'daily': [{'date': d, **daily.get(d, {'count': 0, 'minutes': 0})} for d in days],
        'by_category': by_category,
        'by_equipment': sorted(eq_counts.values(), key=lambda x: -x['count']),
    })


# ─── Export / Import ──────────────────────────────────

# Confluence 표와 같은 순서
EXPORT_COLS = [('status', '완료여부'), ('date_shift', '날짜/근무'), ('equipment', '호기명'), ('title', '작업명'),
               ('link', 'EDM CTTTM LINK'), ('content', '작업내용'), ('category', '분류'), ('author', '작성자')]
CATEGORY_LABEL = {c: l for c, l, *_ in CATEGORIES}
LABEL_TO_CATEGORY = {l: c for c, l, *_ in CATEGORIES}
STATUS_LABEL = dict(STATUSES)


def export_row(r):
    return {'status': STATUS_LABEL.get(r['status'], r['status']),
            'date_shift': f"{r['work_date']} {r['shift'] or ''}".strip(),
            'equipment': r['equipment'], 'title': r['title'] or '', 'link': r['link'] or '',
            'content': r['content'], 'category': CATEGORY_LABEL.get(r['category'], r['category']),
            'author': r['author'] or ''}


@app.route('/api/export.csv')
def api_export_csv():
    buf = io.StringIO()
    buf.write('\ufeff')  # Excel 한글 깨짐 방지
    w = csv.writer(buf)
    w.writerow([h for _, h in EXPORT_COLS])
    for r in query_logs(request.args):
        er = export_row(r)
        w.writerow([er[k] for k, _ in EXPORT_COLS])
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=k2photo_history.csv'})


@app.route('/api/export.jsonl')
def api_export_jsonl():
    """AI 활용용: 레코드당 1줄 JSON (RAG 인덱싱 / 파인튜닝 / 요약 배치에 바로 투입)."""
    lines = []
    for r in query_logs(request.args):
        t = f" {r['start_time']}~{r['end_time']}" if r['start_time'] and r['end_time'] else ''
        lines.append(_json.dumps({
            'id': f"k2ph-{r['id']}",
            'status': r['status'],
            'date': r['work_date'],
            'shift': r['shift'],
            'title': r['title'],
            'symptom': r['symptom'], 'action': r['action'], 'result': r['result'],
            'link': r['link'],
            'start_time': r['start_time'], 'end_time': r['end_time'],
            'duration_min': r['duration_min'],
            'equipment': r['equipment_list'],
            'category': CATEGORY_LABEL.get(r['category'], r['category']),
            'author': r['author'],
            'images': [a['url'] for a in r['attachments']],
            'text': f"[{r['work_date']} {r['shift'] or ''}{t}] [{r['equipment']}] "
                    f"[{CATEGORY_LABEL.get(r['category'], r['category'])}] [{STATUS_LABEL.get(r['status'])}] "
                    f"{r['title']}\n{r['content']}",
        }, ensure_ascii=False))
    return Response('\n'.join(lines) + ('\n' if lines else ''), mimetype='application/x-ndjson',
                    headers={'Content-Disposition': 'attachment; filename=k2photo_history.jsonl'})


@app.route('/api/export/confluence')
def api_export_confluence():
    """Confluence wiki markup 표 (전환 기간 동안 기존 페이지에 붙여넣기용)."""
    esc = lambda s: (s or ' ').replace('|', '\\|').replace('\n', ' \\\\ ')
    out = ['|| ' + ' || '.join(h for _, h in EXPORT_COLS) + ' ||']
    for r in query_logs(request.args):
        er = export_row(r)
        out.append('| ' + ' | '.join(esc(er[k]) for k, _ in EXPORT_COLS) + ' |')
    return Response('\n'.join(out), mimetype='text/plain; charset=utf-8')


def parse_time_range(text):
    m = re.search(r'(\d{1,2}):?(\d{2})\s*[~\-–]\s*(\d{1,2}):?(\d{2})', text or '')
    if not m:
        return None, None
    return f'{int(m[1]):02d}:{m[2]}', f'{int(m[3]):02d}:{m[4]}'


def parse_date(text, default_year):
    """셀 안의 날짜를 찾아 ISO 로. '2026-10-27', '26.10.27', '10/27 (화) DAY' 등."""
    text = (text or '').strip()
    m = re.search(r'(\d{4}|\d{2})[./-](\d{1,2})[./-](\d{1,2})', text)
    try:
        if m:
            y = int(m[1]) + (2000 if len(m[1]) == 2 else 0)
            return date(y, int(m[2]), int(m[3])).isoformat()
        m = re.search(r'(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)', text) or re.search(r'(\d{1,2})월\s*(\d{1,2})일', text)
        if m:
            return date(default_year, int(m[1]), int(m[2])).isoformat()
    except ValueError:
        return None
    return None


def parse_shift(text):
    for tok in re.findall(r'[A-Za-z]+|주간|야간|스윙', text or ''):
        code = normalize_shift(tok)
        if code and (len(tok) > 1 or len(re.findall(r'[A-Za-z]+', text)) == 1):
            return code
    return None


def parse_status(text, default=DEFAULT_STATUS):
    t = (text or '').strip().lower()
    if re.search(r'on.?going|진행|미완|open|대기', t):
        return 'ongoing'
    if re.search(r'close|완료|종료|done', t):
        return 'closed'
    return default


# 헤더 키워드 → 필드 (앞쪽이 우선: '작업명' 이 '작업내용' 보다 먼저 판정돼야 함)
HEADER_RULES = [('status', ['완료', '상태', 'status']), ('date', ['날짜', 'date', '일자']), ('shift', ['근무', 'shift']),
                ('time', ['시간', 'time']), ('equipment', ['호기', '설비', 'eqp']), ('title', ['작업명', '제목', 'title', '요약']),
                ('link', ['edm', 'ctttm', 'link', '링크']), ('content', ['작업내용', '내용', 'content']),
                ('category', ['분류', 'category']), ('author', ['작성자', '담당', 'author'])]
DEFAULT_IMPORT_ORDER = ['status', 'date', 'equipment', 'title', 'link', 'content']


def map_header(cells):
    """헤더 행이면 {열번호: 필드} 반환, 아니면 None. '날짜/근무' 처럼 한 칸에 두 필드면 date 로 두고 shift 도 같이 해석."""
    mapping = {}
    for i, c in enumerate(cells):
        low = (c or '').strip().lower()
        for field, words in HEADER_RULES:
            if any(w in low for w in words) and field not in mapping.values():
                mapping[i] = field
                break
    return mapping if len(mapping) >= 2 and ('content' in mapping.values() or 'title' in mapping.values()) else None


def table_rows(data):
    """rows(HTML 표에서 추출한 2차원 배열) 우선, 없으면 탭 구분 텍스트(따옴표 안 줄바꿈 허용)."""
    if isinstance(data.get('rows'), list):
        return [[str(c or '') for c in r] for r in data['rows'] if isinstance(r, list)]
    return [r for r in csv.reader(io.StringIO(data.get('text') or ''), delimiter='\t')]


@app.route('/api/import', methods=['POST'])
def api_import():
    """Confluence 표 붙여넣기 → 일괄 등록.
    헤더(완료여부 | 날짜/근무 | 호기명 | 작업명 | EDM CTTTM LINK | 작업내용 …)를 자동 인식, 헤더가 없으면 그 순서로 간주.
    이전 형식(날짜 | 작업시간 | 설비호기 | 작업내용 | 요약)도 헤더로 인식. 날짜 칸이 비면 윗 행 날짜/근무를 이어받음."""
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get('dry_run'))
    year = int(data.get('year') or date.today().year)
    category = LABEL_TO_CATEGORY.get(data.get('category'), data.get('category') or DEFAULT_CATEGORY)
    mapping = None
    rows, errors, last_date, last_shift = [], [], None, None
    for n, cells in enumerate(table_rows(data), 1):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if mapping is None:
            header = map_header(cells)
            mapping = header or dict(enumerate(DEFAULT_IMPORT_ORDER))
            if header:
                continue
        f = {field: cells[i] if i < len(cells) else '' for i, field in mapping.items()}
        date_cell = f.get('date', '')
        d = parse_date(date_cell, year) if date_cell else last_date
        if not d:
            errors.append(f'{n}행: 날짜를 해석할 수 없습니다 ({date_cell!r})'); continue
        if not (f.get('content') or f.get('title')):
            errors.append(f'{n}행: 작업명/작업내용이 비어 있습니다'); continue
        start, end = parse_time_range(f.get('time') or '')
        shift = normalize_shift(f.get('shift')) or (parse_shift(date_cell) if date_cell else last_shift) or shift_of(start)
        last_date, last_shift = d, shift
        rows.append(build_record({
            'work_date': d, 'shift': shift, 'start_time': start, 'end_time': end,
            'status': parse_status(f.get('status')), 'equipment': f.get('equipment'),
            'title': f.get('title', ''), 'link': f.get('link'), 'content': f.get('content', ''),
            'category': LABEL_TO_CATEGORY.get(f.get('category'), category),
            'author': f.get('author') or data.get('author'),
        }))
    if not dry_run and rows:
        ts = now_iso()
        conn = get_db()
        for rec in rows:
            rec['created_at'] = rec['updated_at'] = ts
            conn.execute(f"INSERT INTO work_logs ({', '.join(rec)}) VALUES ({', '.join('?' * len(rec))})",
                         list(rec.values()))
        conn.commit()
        conn.close()
    return jsonify({'parsed': len(rows), 'imported': 0 if dry_run else len(rows),
                    'errors': errors, 'preview': rows[:20]})


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5070)), debug=True)
