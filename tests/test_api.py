def _create(client, **kw):
    body = {'work_date': '2026-10-27', 'start_time': '09:00', 'end_time': '11:30',
            'equipment': ['PAA7302'], 'category': 'SETUP', 'content': 'Stage leveling 확인\n상세 내용'}
    body.update(kw)
    return client.post('/api/logs', json=body)


def test_create_and_list(client):
    r = _create(client)
    assert r.status_code == 201
    log = r.get_json()
    assert log['duration_min'] == 150
    assert log['summary'] == 'Stage leveling 확인' and log['summary_auto'] == 1
    rows = client.get('/api/logs?date_from=2026-10-27&date_to=2026-10-27').get_json()
    assert [x['id'] for x in rows] == [log['id']]


def test_overnight_duration_and_common(client):
    log = _create(client, start_time='22:00', end_time='02:00', equipment=['공통', 'PAA7302']).get_json()
    assert log['duration_min'] == 240
    assert log['equipment'] == '공통'


def test_validation(client):
    assert _create(client, content='  ').status_code == 400
    assert _create(client, work_date='10/27').status_code == 400
    assert _create(client, start_time='25:00').status_code == 400
    assert _create(client, category='XX').status_code == 400


def test_equipment_filter_is_exact(client):
    _create(client, equipment=['PAA7302', 'PTA7302'])
    _create(client, equipment=['PAA73021'])
    rows = client.get('/api/logs?equipment=PAA7302').get_json()
    assert len(rows) == 1


def test_update_keeps_auto_summary_in_sync(client):
    log = _create(client).get_json()
    r = client.put(f"/api/logs/{log['id']}", json={'content': '새 내용 첫 줄\n둘째 줄'}).get_json()
    assert r['summary'] == '새 내용 첫 줄'
    r = client.put(f"/api/logs/{log['id']}", json={'summary': '직접 요약'}).get_json()
    assert r['summary'] == '직접 요약' and r['summary_auto'] == 0
    assert client.put('/api/logs/9999', json={}).status_code == 404


def test_delete(client):
    log = _create(client).get_json()
    assert client.delete(f"/api/logs/{log['id']}").status_code == 200
    assert client.delete(f"/api/logs/{log['id']}").status_code == 404


def test_import_confluence_table(client):
    text = ('날짜\t작업시간\t설비호기\t작업내용\t요약\n'
            '10/27\t09:00~11:30\tPAA7302\tleveling 확인\tleveling\n'
            '\t13:00 - 17:00\t공통\tHook-up 회의\t\n'
            'bad\t\t\t내용\t\n')
    r = client.post('/api/import', json={'text': text, 'year': 2026, 'dry_run': True}).get_json()
    assert r['parsed'] == 2 and r['imported'] == 0 and len(r['errors']) == 1
    assert r['preview'][1]['work_date'] == '2026-10-27'
    assert r['preview'][1]['start_time'] == '13:00'
    r = client.post('/api/import', json={'text': text, 'year': 2026}).get_json()
    assert r['imported'] == 2
    assert len(client.get('/api/logs').get_json()) == 2


def test_exports(client):
    _create(client, content='A | B 파이프')
    jsonl = client.get('/api/export.jsonl').get_data(as_text=True).strip().splitlines()
    assert len(jsonl) == 1 and '"PAA7302"' in jsonl[0]
    conf = client.get('/api/export/confluence').get_data(as_text=True)
    assert conf.startswith('|| 날짜') and 'A \\| B' in conf
    csv_text = client.get('/api/export.csv').get_data(as_text=True)
    assert '작업내용' in csv_text


def test_stats(client):
    from datetime import date
    _create(client, work_date=date.today().isoformat())
    s = client.get('/api/stats').get_json()
    assert s['today_count'] == 1 and s['today_minutes'] == 150
    assert len(s['daily']) == 14


def test_categories_and_legacy_migration(client):
    import sqlite3
    import app as k2
    meta = client.get('/api/meta').get_json()
    assert [c['label'] for c in meta['categories']] == ['설비 Down', '셋업', 'PM', '공통업무', '공정개선', '순간정지', '간단작업']
    assert meta['default_category'] == 'SIMPLE'
    log = client.post('/api/logs', json={'work_date': '2026-10-27', 'content': 'x'}).get_json()
    assert log['category'] == 'SIMPLE'
    conn = sqlite3.connect(k2.DATABASE)
    conn.execute("UPDATE work_logs SET category = 'CAL' WHERE id = ?", (log['id'],))
    conn.commit(); conn.close()
    k2.init_db()
    assert client.get('/api/logs').get_json()[0]['category'] == 'SETUP'


def test_rule_category_guess():
    import llm
    g = llm.guess_category
    assert g('PTH7301 COT spin motor alarm 발생, 설비 down → motor 교체') == 'DOWN'
    assert g('handler 순간정지 robot timeout 리셋 후 정상') == 'MINOR_STOP'
    assert g('주간 PM dev cup 세정') == 'PM'
    assert g('focus offset 조정으로 CD uniformity 개선') == 'PROCESS'
    assert g('PCW / CDA hook-up 점검') == 'SETUP'
    assert g('주간 회의 일정 공유') == 'COMMON'
    assert g('자료 정리') == 'SIMPLE'
