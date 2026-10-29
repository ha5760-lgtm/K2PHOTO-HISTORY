"""
K2 PHOTO History - 라인 셋업 일일 작업이력 관리
Confluence 표로 관리하던 일일 작업내용을 간단 입력 → SQLite 자동 저장 → AI 활용(JSONL export)
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
    ('COMMON', '공통', 'bi-people', '#64748b'),
    ('PROCESS', '공정개선', 'bi-graph-up-arrow', '#06a77d'),
    ('MINOR_STOP', '순간정지', 'bi-pause-circle', '#f59e0b'),
    ('SIMPLE', '간단작업', 'bi-check2-square', '#8b5cf6'),
]
CATEGORY_CODES = {c[0] for c in CATEGORIES}
DEFAULT_CATEGORY = 'SIMPLE'
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
    if conn.execute('SELECT COUNT(*) FROM equipment').fetchone()[0] == 0:
        conn.executemany('INSERT INTO equipment (name, vendor, category) VALUES (?, ?, ?)',
                         [(n, vendor_of(n), category_of(n)) for n in DEFAULT_EQUIPMENT])
    conn.commit()
    conn.close()


# ─── Helpers ──────────────────────────────────────────

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


def validate_payload(data, partial=False):
    errors = []
    if not partial or 'work_date' in data:
        try:
            date.fromisoformat(data.get('work_date') or '')
        except ValueError:
            errors.append('날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)')
    if not partial or 'content' in data:
        if not (data.get('content') or '').strip():
            errors.append('작업내용을 입력하세요')
    if data.get('category') and data['category'] not in CATEGORY_CODES:
        errors.append('알 수 없는 분류입니다')
    for k in ('start_time', 'end_time'):
        v = data.get(k)
        if v and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', v):
            errors.append(f'{k} 형식이 올바르지 않습니다 (HH:MM)')
    return errors


def build_record(data):
    content = data['content'].strip()
    summary = (data.get('summary') or '').strip()
    start, end = data.get('start_time') or None, data.get('end_time') or None
    duration = data.get('duration_min')
    if start and end:
        duration = calc_duration(start, end)
    return {
        'work_date': data['work_date'],
        'start_time': start,
        'end_time': end,
        'duration_min': int(duration) if duration not in (None, '') else None,
        'equipment': normalize_equipment(data.get('equipment')),
        'category': data.get('category') or DEFAULT_CATEGORY,
        'content': content,
        'summary': summary or auto_summary(content),
        'summary_auto': 0 if summary else 1,
        'author': (data.get('author') or '').strip() or None,
        'tags': (data.get('tags') or '').strip() or None,
    }


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
    if args.get('author'):
        sql += ' AND author = ?'; params.append(args['author'])
    if args.get('q'):
        sql += ' AND (content LIKE ? OR summary LIKE ? OR tags LIKE ?)'
        params += [f"%{args['q']}%"] * 3
    sql += " ORDER BY work_date DESC, COALESCE(start_time, '99:99') DESC, id DESC LIMIT ?"
    params.append(min(int(args.get('limit') or 500), 5000))
    conn = get_db()
    rows = attach_files(conn, [row_to_dict(r) for r in conn.execute(sql, params).fetchall()])
    conn.close()
    return rows


# ─── Pages ────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', categories=CATEGORIES, common=COMMON,
                           default_category=DEFAULT_CATEGORY)


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
    # 요약을 비우거나 자동요약 상태였다면 내용 기준으로 다시 자동요약
    if 'summary' not in data and row['summary_auto']:
        merged['summary'] = ''
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
    """메모 → 개조식 작업내용 / 요약 / 분류 / 호기 / 시간 자동 기입용 결과."""
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'error': '정리할 작업내용을 먼저 입력하세요'}), 400
    conn = get_db()
    known = [r[0] for r in conn.execute('SELECT name FROM equipment WHERE is_active = 1').fetchall()]
    conn.close()
    result = llm.organize(content, {
        'work_date': data.get('work_date'),
        'equipment': data.get('equipment') or [],
        'category': data.get('category'),
        'known_equipment': known,
        'categories': [(c, l) for c, l, *_ in CATEGORIES],
        'default_category': DEFAULT_CATEGORY,
        'common': COMMON,
    })
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
    conn.close()
    days = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    return jsonify({
        'total_count': total[0], 'total_minutes': total[1],
        'today_count': today_row[0], 'today_minutes': today_row[1],
        'week_count': week_row[0], 'week_minutes': week_row[1],
        'missing_time_count': no_time,
        'daily': [{'date': d, **daily.get(d, {'count': 0, 'minutes': 0})} for d in days],
        'by_category': by_category,
        'by_equipment': sorted(eq_counts.values(), key=lambda x: -x['count']),
    })


# ─── Export / Import ──────────────────────────────────

EXPORT_COLS = [('work_date', '날짜'), ('time', '작업시간'), ('equipment', '설비호기'),
               ('category', '분류'), ('content', '작업내용'), ('summary', '요약'), ('author', '작성자')]
CATEGORY_LABEL = {c: l for c, l, *_ in CATEGORIES}
LABEL_TO_CATEGORY = {l: c for c, l, *_ in CATEGORIES}


def export_row(r):
    t = f"{r['start_time'] or ''}~{r['end_time'] or ''}" if (r['start_time'] or r['end_time']) else ''
    return {'work_date': r['work_date'], 'time': t, 'equipment': r['equipment'],
            'category': CATEGORY_LABEL.get(r['category'], r['category']), 'content': r['content'],
            'summary': r['summary'] or '', 'author': r['author'] or ''}


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
            'date': r['work_date'],
            'start_time': r['start_time'], 'end_time': r['end_time'],
            'duration_min': r['duration_min'],
            'equipment': r['equipment_list'],
            'category': CATEGORY_LABEL.get(r['category'], r['category']),
            'author': r['author'],
            'summary': r['summary'],
            'images': [a['url'] for a in r['attachments']],
            'text': f"[{r['work_date']}{t}] [{r['equipment']}] "
                    f"[{CATEGORY_LABEL.get(r['category'], r['category'])}] {r['content']}",
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
    text = (text or '').strip()
    for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d', '%y.%m.%d', '%y-%m-%d'):
        try:
            return datetime.strptime(text.rstrip('.'), fmt).date().isoformat()
        except ValueError:
            pass
    m = re.fullmatch(r'(\d{1,2})[./-](\d{1,2})\.?(?:\s*\(.\))?', text)
    if m:
        return date(default_year, int(m[1]), int(m[2])).isoformat()
    return None


@app.route('/api/import', methods=['POST'])
def api_import():
    """Confluence 표를 복사(탭 구분)해서 붙여넣기 → 일괄 등록.
    컬럼 순서: 날짜 | 작업시간 | 설비호기 | 작업내용 | 요약 (분류/작성자는 옵션 값으로 일괄 지정)
    날짜 칸이 비어있으면 윗 행 날짜를 이어받음 (Confluence 셀 병합 대응)."""
    data = request.get_json(silent=True) or {}
    text = data.get('text') or ''
    dry_run = bool(data.get('dry_run'))
    year = int(data.get('year') or date.today().year)
    rows, errors, last_date = [], [], None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split('\t')]
        if n == 1 and ('날짜' in cols[0] or 'date' in cols[0].lower()):
            continue  # 헤더 행
        cols += [''] * (5 - len(cols))
        d = parse_date(cols[0], year) if cols[0] else last_date
        if not d:
            errors.append(f'{n}행: 날짜를 해석할 수 없습니다 ({cols[0]!r})'); continue
        if not cols[3]:
            errors.append(f'{n}행: 작업내용이 비어 있습니다'); continue
        last_date = d
        start, end = parse_time_range(cols[1])
        rows.append(build_record({
            'work_date': d, 'start_time': start, 'end_time': end,
            'equipment': cols[2], 'content': cols[3], 'summary': cols[4],
            'category': LABEL_TO_CATEGORY.get(data.get('category'), data.get('category') or DEFAULT_CATEGORY),
            'author': data.get('author'),
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
