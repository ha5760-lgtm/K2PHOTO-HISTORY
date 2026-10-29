import io
import json
import os

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')


def _upload(client, **form):
    return client.post('/api/attachments', data={'file': (io.BytesIO(PNG), 'image.png', 'image/png'), **form},
                       content_type='multipart/form-data')


def _log(client, **kw):
    body = {'work_date': '2026-10-27', 'equipment': ['PAA7302'], 'content': 'Stage leveling 확인'}
    body.update(kw)
    return client.post('/api/logs', json=body).get_json()


def test_paste_upload_then_link_on_save(client):
    a = _upload(client)
    assert a.status_code == 201
    a = a.get_json()
    assert a['log_id'] is None and a['url'].startswith('/uploads/') and a['name'].startswith('capture_')
    assert client.get(a['url']).data == PNG
    log = _log(client, attachment_ids=[a['id']])
    assert [x['id'] for x in log['attachments']] == [a['id']]
    rows = client.get('/api/logs').get_json()
    assert rows[0]['attachments'][0]['url'] == a['url']
    assert a['url'] in client.get('/api/export.jsonl').get_data(as_text=True)


def test_upload_to_existing_log_is_saved_immediately_and_bumps_version(client):
    log = _log(client)
    v1 = client.get('/api/version').get_json()['version']
    a = _upload(client, log_id=str(log['id'])).get_json()
    assert a['log_id'] == log['id']
    assert client.get('/api/version').get_json()['version'] != v1
    assert _upload(client, log_id='9999').status_code == 404


def test_reject_non_image(client):
    r = client.post('/api/attachments', data={'file': (io.BytesIO(b'x'), 'a.txt', 'text/plain')},
                    content_type='multipart/form-data')
    assert r.status_code == 400


def test_delete_attachment_and_cascade(client, tmp_path):
    log = _log(client)
    a1 = _upload(client, log_id=str(log['id'])).get_json()
    a2 = _upload(client, log_id=str(log['id'])).get_json()
    assert client.delete(f"/api/attachments/{a1['id']}").status_code == 200
    assert client.get(a1['url']).status_code == 404
    client.delete(f"/api/logs/{log['id']}")
    assert not os.path.exists(tmp_path / 'uploads' / a2['url'].removeprefix('/uploads/'))


def test_ai_organize_rule_fallback(client):
    memo = 'paa7302 13:00-17:30 wafer stage leveling 확인 Z offset 재조정함. 내일 재측정 예정'
    r = client.post('/api/ai/organize', json={'content': memo}).get_json()
    assert r['engine'] == 'rule'
    assert r['equipment'] == ['PAA7302']
    assert (r['start_time'], r['end_time']) == ('13:00', '17:30')
    assert r['category'] == 'SETUP'
    assert r['action'].startswith('Wafer stage leveling') and '재측정 예정' in r['result']
    assert r['status'] == 'ongoing'
    assert client.post('/api/ai/organize', json={'content': ' '}).status_code == 400


def test_ai_organize_llm(client, monkeypatch):
    import llm
    monkeypatch.setenv('LLM_API_URL', 'http://llm.local/v1')
    sent = {}

    def fake_chat(messages, **kw):
        sent['messages'] = messages
        return '```json\n' + json.dumps({
            'title': 'PAA7302 leveling', 'symptom': '', 'action': ['Stage leveling 확인'], 'result': '정상',
            'status': 'closed', 'category': 'SETUP',
            'equipment': ['paa7302', '엉뚱한값'], 'start_time': '25:00', 'end_time': None,
            'issues': [], 'next_actions': ['재측정']}, ensure_ascii=False) + '\n```'
    monkeypatch.setattr(llm, 'chat', fake_chat)
    r = client.post('/api/ai/organize', json={'content': '메모'}).get_json()
    assert r['engine'] == 'llm' and r['title'] == 'PAA7302 leveling'
    assert r['action'] == '- Stage leveling 확인' and r['status'] == 'closed'
    assert r['equipment'] == ['PAA7302'] and r['start_time'] is None
    assert 'PAA7302' in sent['messages'][1]['content']  # 등록 호기 목록 전달

    monkeypatch.setattr(llm, 'chat', lambda *a, **k: 'not json')
    r = client.post('/api/ai/organize', json={'content': 'PTA7302 power on'}).get_json()
    assert r['engine'] == 'rule' and 'warning' in r and r['category'] == 'SETUP'
