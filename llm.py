"""AI 작업내용 정리.

OpenAI 호환 /chat/completions (photo-ai-bot · equip-history 와 같은 LLM_API_URL / LLM_MODEL / LLM_API_KEY 설정).
LLM 미설정 또는 호출 실패 시 규칙 기반 정리로 폴백 → 버튼은 항상 동작.
"""
import json
import os
import re
import urllib.error
import urllib.request

EQUIP_RE = re.compile(r'\bP[A-Z]{2}\d{4}\b')
TIME_RE = re.compile(r'(\d{1,2}):?(\d{2})\s*[~\-–]\s*(\d{1,2}):?(\d{2})')
HHMM_RE = re.compile(r'([01]\d|2[0-3]):[0-5]\d')

# 분류 키워드 (규칙 기반). 앞쪽 분류가 우선.
CATEGORY_KEYWORDS = [
    ('MEETING', ['회의', '미팅', '협의', 'meeting', '공유회', '리뷰']),
    ('MOVE_IN', ['반입', '설치 위치', 'move-in', 'move in', '반출', 'marking', '레벨링 패드']),
    ('HOOKUP', ['hook-up', 'hookup', 'hook up', 'pcw', 'cda', 'exhaust', '배관', '유틸', 'drain', 'solvent', 'n2', '배기']),
    ('POWER_ON', ['power-on', 'power on', '전원', 'emo', 'interlock', '인터락']),
    ('SW', ['s/w', 'sw ', 'software', 'recipe', 'host', 'eap', '레시피', 'job ']),
    ('CAL', ['calibration', 'cal ', 'leveling', 'alignment', 'offset', '보정', 'focus', 'stage']),
    ('QUAL', ['qual', 'dummy', 'cd ', 'overlay', 'uniformity', '측정', 'run', '평가']),
]


def config():
    return {
        'url': (os.environ.get('LLM_API_URL') or '').strip().rstrip('/'),
        'key': (os.environ.get('LLM_API_KEY') or '').strip(),
        'model': os.environ.get('LLM_MODEL') or os.environ.get('LLM_MODEL_NAME') or 'grok-4-fast-non-reasoning',
        'timeout': int(os.environ.get('LLM_TIMEOUT_SECONDS') or 60),
    }


def is_enabled():
    c = config()
    return bool(c['url'] or c['key'])


def engine_name():
    return f"LLM ({config()['model']})" if is_enabled() else '규칙 기반 (LLM 미설정)'


# ─── 규칙 기반 ─────────────────────────────────────────

def _bulletize(text):
    lines = []
    for raw in re.split(r'\n|(?<=[.!?])\s+|(?<=다\.)\s*|\s*/\s+', text or ''):
        line = re.sub(r'\s+', ' ', raw).strip(' -•*·▶>\t.')
        if line and line not in lines:
            lines.append(line)
    return lines


def guess_category(text, default='ETC'):
    low = f' {(text or "").lower()} '
    best, best_hits = default, 0
    for code, words in CATEGORY_KEYWORDS:
        hits = sum(low.count(w) for w in words)
        if hits > best_hits:
            best, best_hits = code, hits
    return best


def rule_organize(content, known_equipment=(), category=None):
    text = content or ''
    found = list(dict.fromkeys(EQUIP_RE.findall(text.upper())))
    m = TIME_RE.search(text)
    start = end = None
    if m and int(m[1]) < 24 and int(m[3]) < 24:
        start, end = f'{int(m[1]):02d}:{m[2]}', f'{int(m[3]):02d}:{m[4]}'
    # 호기명·시간은 별도 필드로 빠지므로 본문에서 제거
    stripped = TIME_RE.sub(' ', text)
    stripped = re.sub(r'\bP[A-Z]{2}\d{4}\b\s*[:,]?', ' ', stripped, flags=re.I) if found else stripped
    lines = [l[0].upper() + l[1:] for l in _bulletize(stripped)] or _bulletize(text)
    follow = [l for l in lines if re.search(r'예정|필요|요청|내일|확인 필요|대기|follow', l, re.I)]
    issues = [l for l in lines if re.search(r'이슈|문제|불량|알람|alarm|에러|error|낮음|높음|누수|지연|fail|spec-out|spec out', l, re.I)
              or re.search(r'\bNG\b', l)]
    body = [l for l in lines if l not in follow]
    organized = '\n'.join(f'- {l}' for l in body)
    if follow:
        organized += ('\n' if organized else '') + '\n'.join(f'▶ 후속: {l}' for l in follow)
    summary = (body or lines or [''])[0]
    if found:
        summary = f"{', '.join(found[:2])} {summary}"
    if len(summary) > 40:
        summary = summary[:39] + '…'
    return {
        'content': organized or text.strip(),
        'summary': summary,
        'category': guess_category(text, category or 'ETC'),
        'equipment': found,
        'start_time': start, 'end_time': end,
        'issues': issues, 'next_actions': follow,
    }


# ─── LLM ──────────────────────────────────────────────

SYSTEM_PROMPT = """너는 삼성 반도체 K2 라인 포토(노광) 설비 셋업 엔지니어의 작업일지 정리 도우미다.
사용자가 대충 적은 메모를 Confluence 작업일지 한 행으로 정리한다.
규칙:
- 사실만 정리하고 없는 내용을 지어내지 않는다. 수치·호기명·부품명·벤더명은 원문 그대로 유지.
- content: 핵심 작업을 "- " 로 시작하는 간결한 개조식 줄로. 후속 조치/예정 사항은 "▶ 후속: " 으로 시작하는 줄로 맨 아래에.
- summary: 40자 이내 한 줄 요약 (명사형 종결, 예: "PAA7302 Stage leveling 1차 spec-in").
- category: 다음 코드 중 하나 {categories}
- equipment: 본문에 등장한 설비호기 목록 (예: PAA7302). 특정 호기가 없으면 ["공통"].
- start_time / end_time: 본문에 작업시간이 있으면 "HH:MM", 없으면 null.
- issues: 문제/이상 사항 목록, next_actions: 후속 조치 목록 (없으면 빈 배열).
반드시 JSON 객체 하나만 출력한다. 키: content, summary, category, equipment, start_time, end_time, issues, next_actions"""


def _extract_json(text):
    text = re.sub(r'^```(?:json)?|```$', '', (text or '').strip(), flags=re.M).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end < start:
        raise ValueError('LLM 응답에서 JSON 을 찾지 못했습니다')
    return json.loads(text[start:end + 1])


def _content_text(message_content):
    if isinstance(message_content, list):
        return ''.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in message_content)
    return message_content or ''


def chat(messages, temperature=0.2, max_tokens=1200):
    c = config()
    base = c['url'] or 'https://api.x.ai/v1'
    if base.endswith('/chat/completions'):
        base = base[:-len('/chat/completions')]
    headers = {'Content-Type': 'application/json'}
    if c['key']:
        headers['Authorization'] = f"Bearer {c['key']}"
    body = json.dumps({'model': c['model'], 'messages': messages,
                       'temperature': temperature, 'max_tokens': max_tokens}).encode()
    req = urllib.request.Request(f'{base}/chat/completions', data=body, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=c['timeout']) as res:
        data = json.loads(res.read().decode())
    return _content_text(data['choices'][0]['message'].get('content'))


def llm_organize(content, context):
    categories = ', '.join(f"{c}({l})" for c, l in context['categories'])
    user = (f"작업일: {context.get('work_date') or '-'}\n"
            f"현재 선택된 설비호기: {', '.join(context.get('equipment') or []) or '없음'}\n"
            f"등록된 설비호기: {', '.join(context.get('known_equipment') or [])}\n"
            f"현재 분류: {context.get('category') or '-'}\n"
            f"--- 메모 ---\n{content}")
    raw = chat([{'role': 'system', 'content': SYSTEM_PROMPT.format(categories=categories)},
                {'role': 'user', 'content': user}])
    return _extract_json(raw)


# ─── 정규화 ───────────────────────────────────────────

def _clean(result, fallback, category_codes, common):
    def str_list(v):
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    content = str(result.get('content') or '').strip() or fallback['content']
    summary = str(result.get('summary') or '').strip() or fallback['summary']
    category = result.get('category') if result.get('category') in category_codes else fallback['category']
    equipment = [e.upper() if e != common else common for e in str_list(result.get('equipment'))]
    equipment = [e for e in equipment if e == common or EQUIP_RE.fullmatch(e)]
    times = {}
    for k in ('start_time', 'end_time'):
        v = result.get(k)
        times[k] = v if isinstance(v, str) and HHMM_RE.fullmatch(v) else None
    return {'content': content, 'summary': summary[:120], 'category': category,
            'equipment': list(dict.fromkeys(equipment)), **times,
            'issues': str_list(result.get('issues')), 'next_actions': str_list(result.get('next_actions'))}


def organize(content, context):
    """메모 → 정리 결과 dict. engine/warning 포함."""
    fallback = rule_organize(content, context.get('known_equipment', ()), context.get('category'))
    codes = {c for c, _ in context['categories']}
    common = context.get('common', '공통')
    if not is_enabled():
        return {**_clean(fallback, fallback, codes, common), 'engine': 'rule'}
    try:
        return {**_clean(llm_organize(content, context), fallback, codes, common), 'engine': 'llm'}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
        print(f'[llm] organize failed, fallback to rule: {type(e).__name__}')
        return {**_clean(fallback, fallback, codes, common), 'engine': 'rule',
                'warning': 'LLM 호출 실패 → 규칙 기반으로 정리했습니다'}
