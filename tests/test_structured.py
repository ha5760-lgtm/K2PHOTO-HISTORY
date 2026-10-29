"""Confluence 표 형식(완료여부 / 날짜·근무 / 호기명 / 작업명 / EDM·CTTTM / 1.현상 2.조치사항 3.결론) 관련 테스트."""
import sqlite3


def _create(client, **kw):
    body = {'work_date': '2026-10-27', 'equipment': ['PTH7301'], 'title': 'COT spin motor 교체',
            'symptom': 'spin motor alarm', 'action': 'motor driver 교체', 'result': '정상 복구',
            'status': 'closed', 'shift': 'DAY', 'link': 'CTTTM-1234'}
    body.update(kw)
    return client.post('/api/logs', json=body)


def test_structured_create(client):
    log = _create(client).get_json()
    assert log['title'] == 'COT spin motor 교체' and log['title_auto'] == 0
    assert (log['status'], log['shift'], log['link']) == ('closed', 'DAY', 'CTTTM-1234')
    assert log['content'] == '1. 현상\nspin motor alarm\n\n2. 조치사항\nmotor driver 교체\n\n3. 결론\n정상 복구'


def test_title_auto_and_shift_from_time(client):
    log = _create(client, title='', shift=None, start_time='22:30', end_time='01:00').get_json()
    assert log['title'] == 'spin motor alarm' and log['title_auto'] == 1
    assert log['shift'] == 'GY' and log['duration_min'] == 150
    assert _create(client, shift=None, start_time='14:00').get_json()['shift'] == 'SW'
    assert _create(client, shift='주간').get_json()['shift'] == 'DAY'


def test_validation_structured(client):
    assert _create(client, title='', symptom='', action='', result='').status_code == 400
    assert _create(client, status='done').status_code == 400
    assert _create(client, shift='NIGHTX').status_code == 400


def test_legacy_content_is_parsed(client):
    log = client.post('/api/logs', json={'work_date': '2026-10-27',
                                         'content': '1. 현상: 알람\n2. 조치사항: 리셋\n3. 결론: 정상'}).get_json()
    assert (log['symptom'], log['action'], log['result']) == ('알람', '리셋', '정상')
    plain = client.post('/api/logs', json={'work_date': '2026-10-27', 'content': '그냥 메모'}).get_json()
    assert plain['symptom'] == '그냥 메모' and plain['title'] == '그냥 메모'


def test_status_toggle_and_filter(client):
    log = _create(client).get_json()
    r = client.put(f"/api/logs/{log['id']}", json={'status': 'ongoing'}).get_json()
    assert r['status'] == 'ongoing' and r['title'] == log['title']
    assert len(client.get('/api/logs?status=ongoing').get_json()) == 1
    assert client.get('/api/logs?status=closed').get_json() == []
    assert client.get('/api/stats').get_json()['ongoing_count'] == 1


def test_search_covers_title_and_link(client):
    _create(client)
    assert len(client.get('/api/logs?q=CTTTM-1234').get_json()) == 1
    assert len(client.get('/api/logs?q=driver').get_json()) == 1


def test_sort_by_shift_within_day(client):
    for sh in ('DAY', 'GY', 'SW'):
        _create(client, shift=sh, title=sh)
    assert [r['shift'] for r in client.get('/api/logs').get_json()] == ['GY', 'SW', 'DAY']


def test_migration_from_previous_schema(tmp_path, monkeypatch):
    import importlib
    db = tmp_path / 'old.db'
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE work_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, work_date TEXT NOT NULL, start_time TEXT,
            end_time TEXT, duration_min INTEGER, equipment TEXT NOT NULL DEFAULT '공통', category TEXT NOT NULL DEFAULT 'ETC',
            content TEXT NOT NULL, summary TEXT, summary_auto INTEGER DEFAULT 0, author TEXT, tags TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO work_logs (work_date, start_time, equipment, category, content, summary, created_at, updated_at)
            VALUES ('2026-10-20', '15:00', 'PAA7302', 'CAL', '- leveling 확인', 'leveling 1차', 'x', 'x');''')
    conn.commit(); conn.close()
    monkeypatch.setenv('K2PH_DB', str(db))
    monkeypatch.setenv('K2PH_UPLOADS', str(tmp_path / 'u'))
    import app as k2
    k2 = importlib.reload(k2)
    row = k2.app.test_client().get('/api/logs').get_json()[0]
    assert (row['title'], row['symptom'], row['shift'], row['status'], row['category']) == \
        ('leveling 1차', '- leveling 확인', 'SW', 'closed', 'SETUP')


def test_import_confluence_html_rows(client):
    rows = [['완료여부', '날짜/근무', '호기명', '작업명', 'EDM CTTTM LINK', '작업내용'],
            ['Closed', '10/27 DAY', 'PTH7301', 'Spin motor 교체', 'CTTTM-1', '1. 현상\nalarm\n2. 조치사항\n교체\n3. 결론\n정상'],
            ['On-going', '', 'PAA7302', 'Leveling 재측정', '', '1. 현상 spec-out\n2. 조치사항 offset 조정\n3. 결론 내일 재측정']]
    r = client.post('/api/import', json={'rows': rows, 'year': 2026}).get_json()
    assert r['imported'] == 2 and r['errors'] == []
    a, b = r['preview']
    assert (a['status'], a['work_date'], a['shift'], a['link'], a['action']) == ('closed', '2026-10-27', 'DAY', 'CTTTM-1', '교체')
    assert (b['status'], b['work_date'], b['shift'], b['result']) == ('ongoing', '2026-10-27', 'DAY', '내일 재측정')


def test_import_tsv_quoted_multiline_and_legacy_header(client):
    text = ('완료여부\t날짜/근무\t호기명\t작업명\tEDM CTTTM LINK\t작업내용\n'
            'Closed\t2026-10-28 SW\tPSH7306\tDrain 누수\t\t"1. 현상\n누수\n2. 조치사항\n배관 재체결"\n')
    r = client.post('/api/import', json={'text': text, 'dry_run': True}).get_json()
    assert r['parsed'] == 1 and r['preview'][0]['shift'] == 'SW' and r['preview'][0]['action'] == '배관 재체결'
    legacy = '날짜\t작업시간\t설비호기\t작업내용\t요약\n10/27\t09:00~11:30\tPAA7302\tleveling 확인\tleveling\n'
    r = client.post('/api/import', json={'text': legacy, 'year': 2026, 'dry_run': True}).get_json()
    p = r['preview'][0]
    assert (p['title'], p['symptom'], p['start_time'], p['shift']) == ('leveling', 'leveling 확인', '09:00', 'DAY')


def test_ai_organize_structured_input(client):
    r = client.post('/api/ai/organize', json={
        'symptom': 'pth7301 10:00-13:30 COT spin motor alarm 발생 설비 down. motor driver 교체 후 복구 dummy 5매 OK. '
                   '내일 vendor 원인 분석 회신 예정 CTTTM-240117'}).get_json()
    assert r['symptom'].startswith('COT spin motor alarm') and r['action'] == 'Motor driver 교체'
    assert '회신 예정' in r['result'] and r['status'] == 'ongoing'
    assert (r['category'], r['equipment'], r['link'], r['shift']) == ('DOWN', ['PTH7301'], 'CTTTM-240117', 'DAY')
