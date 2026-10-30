"""Confluence 표 붙여넣기 → AI 자동 정리 → 등록."""
import json

HEADER = ['완료여부', '날짜/근무', '호기명', '작업명', 'EDM CTTTM LINK', '작업내용']


def _rows(*body):
    return [HEADER, *body]


def test_ai_import_splits_unstructured_content_and_registers(client):
    rows = _rows(['', '10/27 GY', 'PTH7301', '', '',
                  'COT spin motor alarm 발생 설비 down. motor driver 교체 후 복구. vendor 회신 대기 CTTTM-240117'])
    r = client.post('/api/import', json={'rows': rows, 'year': 2026, 'ai': True}).get_json()
    assert r['imported'] == 1 and r['engine'] == 'rule' and r['errors'] == []
    log = client.get('/api/logs').get_json()[0]
    assert log['symptom'].startswith('COT spin motor alarm') and log['action'] == 'Motor driver 교체'
    assert '회신 대기' in log['result']
    assert (log['status'], log['shift'], log['category'], log['link']) == ('ongoing', 'GY', 'DOWN', 'CTTTM-240117')
    assert log['title'] == 'PTH7301 Motor driver 교체'


def test_table_values_win_over_ai(client):
    rows = _rows(['Closed', '10/27 DAY', 'PAA7302', 'Leveling 재측정', 'EDM-1',
                  '1. 현상\nspec-out\n2. 조치사항\noffset 조정\n3. 결론\n내일 재측정 예정'])
    r = client.post('/api/import', json={'rows': rows, 'year': 2026, 'ai': True}).get_json()
    p = r['preview'][0]
    assert (p['status'], p['title'], p['link'], p['symptom'], p['result']) == \
        ('closed', 'Leveling 재측정', 'EDM-1', 'spec-out', '내일 재측정 예정')


def test_reimport_same_table_is_skipped_and_undo(client):
    rows = _rows(['Closed', '10/27 DAY', 'PAA7302', 'A', '', '내용 A'], ['', '', 'PTA7302', 'B', '', '내용 B'])
    first = client.post('/api/import', json={'rows': rows, 'year': 2026, 'ai': True}).get_json()
    assert first['imported'] == 2
    again = client.post('/api/import', json={'rows': rows, 'year': 2026, 'ai': True}).get_json()
    assert again['imported'] == 0 and again['skipped'] == 2
    assert client.delete(f"/api/import/{first['batch']}").get_json()['deleted'] == 2
    assert client.get('/api/logs').get_json() == []


def test_llm_rows_batch(client, monkeypatch):
    import llm
    monkeypatch.setenv('LLM_API_URL', 'http://llm.local/v1')
    calls = []

    def fake_chat(messages, **kw):
        calls.append(messages[1]['content'])
        n = messages[1]['content'].count('### 행 ')
        base = 10 * (len(calls) - 1)
        return json.dumps([{'index': i, 'work_date': '2026-10-26', 'shift': 'sw', 'status': 'ongoing',
                            'equipment': ['pah7304'], 'title': f'LLM 작업 {base + i}', 'symptom': '현상', 'action': ['조치1', '조치2'],
                            'result': '결론', 'link': '', 'category': 'PM'} for i in range(n)], ensure_ascii=False)
    monkeypatch.setattr(llm, 'chat', fake_chat)
    rows = [['메모'], *[[f'아무 형식 메모 {i}'] for i in range(12)]]   # 머리글 인식 실패 + 날짜 없음 → LLM 이 채움
    r = client.post('/api/import', json={'rows': rows, 'ai': True}).get_json()
    assert r['engine'] == 'llm' and r['imported'] == 13 and len(calls) == 2      # 10행씩 묶어서 호출
    p = r['preview'][0]
    assert (p['work_date'], p['shift'], p['status'], p['equipment'], p['category']) == ('2026-10-26', 'SW', 'ongoing', 'PAH7304', 'PM')
    assert p['action'] == '- 조치1\n- 조치2' and '행 0' in calls[0] and '아무 형식 메모 0' in calls[0]


def test_llm_rows_failure_falls_back(client, monkeypatch):
    import llm
    monkeypatch.setenv('LLM_API_URL', 'http://llm.local/v1')
    monkeypatch.setattr(llm, 'chat', lambda *a, **k: 'not json')
    rows = _rows(['', '10/27', 'PAA7302', '', '', 'leveling 확인 후 정상'])
    r = client.post('/api/import', json={'rows': rows, 'year': 2026, 'ai': True}).get_json()
    assert r['imported'] == 1 and r['engine'] == 'rule' and 'LLM 정리 실패' in r['warning']


def test_no_date_without_ai_is_error(client):
    r = client.post('/api/import', json={'rows': [['메모'], ['날짜 없는 행']], 'dry_run': True}).get_json()
    assert r['parsed'] == 0 and r['errors']
