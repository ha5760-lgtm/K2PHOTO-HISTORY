"""AI 작업내용 정리.

OpenAI 호환 /chat/completions (photo-ai-bot · equip-history 와 같은 LLM_API_URL / LLM_MODEL / LLM_API_KEY 설정).
LLM 미설정 또는 호출 실패 시 규칙 기반 정리로 폴백 → 버튼은 항상 동작.
"""
import json
import os
import re
import urllib.error
import urllib.request

from sections import parse_sections

EQUIP_RE = re.compile(r'\bP[A-Z]{2}\d{4}\b')
TIME_RE = re.compile(r'(\d{1,2}):?(\d{2})\s*[~\-–]\s*(\d{1,2}):?(\d{2})')
HHMM_RE = re.compile(r'([01]\d|2[0-3]):[0-5]\d')

# 분류 키워드 (규칙 기반). 히트 수가 같으면 앞쪽 분류가 우선 → 장애성 분류를 먼저, 회의·교육(공통업무)은 셋업보다 먼저.
CATEGORY_KEYWORDS = [
    ('MINOR_STOP', ['순간정지', '순간 정지', '일시정지', '일시 정지', 'minor stop', 'choko', '쵸코', '리셋', 'reset', '재시작', 'restart',
                    'hang', '멈춤', 'jam', '재기동']),
    ('DOWN', ['down', '다운', '고장', '알람', 'alarm', '에러', 'error', '트러블', 'trouble', 'bm', '교체', 'fail', '불량', '누수', 'leak',
              '이상', '복구']),
    ('PM', ['pm', '정기', '예방', '정기점검', '세정', '클리닝', 'cleaning', '소모품', '필터 교환', 'lamp 교환']),
    ('PROCESS', ['공정개선', '개선', 'cd ', 'overlay', 'uniformity', 'focus', 'dose', '수율', 'defect', '최적화', 'margin', 'recipe 변경',
                 'recipe 최적화']),
    ('COMMON', ['회의', '미팅', '협의', 'meeting', '교육', '보고', '공유', '인수인계', '안전']),
    ('SETUP', ['셋업', 'setup', 'set-up', '반입', '설치', 'hook-up', 'hookup', 'pcw', 'cda', 'exhaust', '배관', '유틸', 'power-on', 'power on',
               '전원', 'emo', 'interlock', 's/w', 'software', 'recipe', 'host', 'eap', 'calibration', 'leveling', 'alignment', 'offset',
               'qual', 'dummy', '보정']),
]

CATEGORY_HINTS = {
    'DOWN': '설비 고장·알람으로 생산 불가, 부품 교체/복구 작업',
    'SETUP': '신규 설비 반입·설치·Hook-up·Power-on·S/W·Calibration·Qual 등 라인 셋업',
    'PM': '정기/예방 보전, 세정, 소모품 교체',
    'COMMON': '특정 설비가 아닌 공통 업무 (회의, 교육, 보고, 인수인계)',
    'PROCESS': 'CD/Overlay/Focus 등 공정 성능 개선, recipe 최적화',
    'MINOR_STOP': '짧은 정지 후 리셋·재시작으로 바로 복구된 순간정지',
    'SIMPLE': '위에 해당하지 않는 간단한 작업',
}


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


def guess_category(text, default='SIMPLE'):
    low = f' {(text or "").lower()} '
    best, best_hits = default, 0
    for code, words in CATEGORY_KEYWORDS:
        hits = sum(low.count(w) for w in words)
        if hits > best_hits:
            best, best_hits = code, hits
    return best


ACTION_RE = re.compile(r'교체|조치|조정|리셋|reset|세정|청소|클리닝|cleaning|재시작|restart|재기동|보정|수리|교환|설치|연결|변경|'
                       r'투입|실시|적용|점검|tuning|튜닝|조임|재장착|재부팅|reboot|clean|download|등록|삭제|업데이트|update', re.I)
RESULT_RE = re.compile(r'정상|복구|완료|\bOK\b|spec.?in|해결|예정|대기|모니터링|필요|재발|회신|생산 재개|양호|이상 ?없음|\bpass\b|'
                       r'추후|내일|재측정|결론', re.I)
PENDING_RE = re.compile(r'예정|대기|모니터링|필요|재발 시|미완|진행 ?중|회신|follow|추후|내일|재측정|확인 중|open', re.I)
CLOSED_RE = re.compile(r'정상|복구|완료|\bOK\b|spec.?in|해결|생산 재개|양호|이상 ?없음|\bpass\b|close', re.I)
LINK_RE = re.compile(r'https?://\S+|\b(?:CTTTM|EDM)[-_ #]?\w*\d+\w*\b', re.I)


def _join(lines):
    lines = [l for l in lines if l]
    if len(lines) <= 1:
        return lines[0] if lines else ''
    return '\n'.join(f'- {l}' for l in lines)


def classify_sentences(lines):
    """문장 단위로 현상 / 조치사항 / 결론 분류. 'A 교체 후 복구' 처럼 섞인 문장은 '후' 에서 나눔."""
    parts = {'symptom': [], 'action': [], 'result': []}
    for line in lines:
        has_a, has_r = bool(ACTION_RE.search(line)), bool(RESULT_RE.search(line))
        m = re.search(r'^(.*\S)\s+후[,\s]+(.+)$', line)
        chunks = [c.strip() for c in re.split(r',\s+', line) if c.strip()]
        if has_a and has_r and m and ACTION_RE.search(m[1]) and RESULT_RE.search(m[2]):
            parts['action'].append(m[1].strip())
            parts['result'].append(m[2].strip(' ,'))
        elif has_a and has_r and len(chunks) > 1:
            # 'A 확인, B 재조정, spec-in 확인' → 쉼표 단위로 다시 분류
            sub = classify_sentences(chunks)
            for k in parts:
                if sub[k]:
                    parts[k].append(', '.join(sub[k]))
        elif has_r and (PENDING_RE.search(line) or not has_a):
            parts['result'].append(line)
        elif has_a and (parts['symptom'] or parts['action'] or len(lines) == 1 or not re.search(r'발생|알람|alarm|에러|error|down|불량|이상', line, re.I)):
            parts['action'].append(line)
        else:
            parts['symptom'].append(line)
    return parts


def short_title(text, limit=40):
    """단어 경계에서 자르기 (말줄임표 없이)."""
    text = re.sub(r'\s+', ' ', text or '').strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut if len(cut) >= limit // 2 else text[:limit]


def judge_status(text, default=None):
    if PENDING_RE.search(text or ''):
        return 'ongoing'
    if CLOSED_RE.search(text or ''):
        return 'closed'
    return default


def rule_organize(content, known_equipment=(), category=None):
    text = content or ''
    found = list(dict.fromkeys(EQUIP_RE.findall(text.upper())))
    m = TIME_RE.search(text)
    start = end = None
    if m and int(m[1]) < 24 and int(m[3]) < 24:
        start, end = f'{int(m[1]):02d}:{m[2]}', f'{int(m[3]):02d}:{m[4]}'
    links = list(dict.fromkeys(LINK_RE.findall(text)))
    # 호기명·시간·링크는 별도 필드로 빠지므로 본문에서 제거
    stripped = TIME_RE.sub(' ', text)
    for l in links:
        stripped = stripped.replace(l, ' ')
    stripped = re.sub(r'\bP[A-Z]{2}\d{4}\b\s*[:,]?', ' ', stripped, flags=re.I) if found else stripped
    cap = lambda l: l[0].upper() + l[1:] if l else l
    given = parse_sections(stripped)
    title = ''
    if given:
        # 사용자가 이미 칸을 나눠 썼으면 그 구분을 존중하고 정리만 함
        title = re.sub(r'\s+', ' ', given.pop('title', '') or '').strip()
        parts = {k: [cap(l) for l in _bulletize(v)] for k, v in given.items()}
        if not parts['action'] and not parts['result'] and parts['symptom']:
            parts = classify_sentences(parts['symptom'])
    else:
        parts = classify_sentences([cap(l) for l in _bulletize(stripped)] or _bulletize(text))
    follow = [l for l in parts['result'] if PENDING_RE.search(l)]
    if not title:
        # Confluence 작업명처럼 '호기 + 한 일' (조치가 있으면 조치, 없으면 현상)
        head = (parts['action'] or parts['symptom'] or parts['result'] or [''])[0]
        head = re.split(r',\s|\s후\s|→', head)[0].strip()
        title = f"{', '.join(found[:2])} {head}".strip() if found else head
    title = short_title(title)
    return {
        'title': title,
        'symptom': _join(parts['symptom']),
        'action': _join(parts['action']),
        'result': _join(parts['result']),
        'status': judge_status(' '.join(parts['result']) or text),
        'category': guess_category(text, category or 'SIMPLE'),
        'equipment': found,
        'link': ' '.join(links),
        'start_time': start, 'end_time': end,
        'next_actions': follow,
    }


# ─── LLM ──────────────────────────────────────────────

SYSTEM_PROMPT = """너는 삼성 반도체 K2 라인 포토(노광) 설비 엔지니어의 작업이력 정리 도우미다.
사용자가 대충 적은 메모를 Confluence 작업이력 표 한 행(완료여부 | 날짜/근무 | 호기명 | 작업명 | EDM CTTTM LINK | 작업내용)으로 정리한다.
작업내용은 반드시 1. 현상 / 2. 조치사항 / 3. 결론 세 칸으로 나눈다.
규칙:
- 사실만 정리하고 없는 내용을 지어내지 않는다. 수치·호기명·부품명·알람코드·벤더명은 원문 그대로 유지. 해당 내용이 없으면 빈 문자열.
- title: 작업명. 30자 이내, 명사형 (예: "PTH7301 COT spin motor 교체").
- symptom: 1. 현상 — 무엇이 언제 어떻게 발생했나 (알람, 불량, 요청 배경).
- action: 2. 조치사항 — 실제로 한 작업. 여러 개면 "- " 개조식 줄.
- result: 3. 결론 — 결과와 현재 상태, 남은 후속 조치 (예: "정상 복구, 생산 재개" / "Vendor 원인 분석 회신 대기").
- status: 결론 기준으로 끝났으면 "closed", 후속 조치·모니터링·회신 대기가 남았으면 "ongoing".
- category: 다음 코드 중 하나 (설명 참고)
{categories}
- equipment: 본문에 등장한 설비호기 목록 (예: PAA7302). 특정 호기가 없으면 ["공통"].
- link: 본문에 있는 EDM / CTTTM 번호나 URL (없으면 빈 문자열).
- start_time / end_time: 본문에 작업시간이 있으면 "HH:MM", 없으면 null.
- next_actions: 남은 후속 조치 목록 (없으면 빈 배열).
입력에 [현상] [조치사항] [결론] [작업명] 표시가 있으면 사용자가 나눈 구분을 우선 존중한다.
반드시 JSON 객체 하나만 출력한다. 키: title, symptom, action, result, status, category, equipment, link, start_time, end_time, next_actions"""


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
    categories = '\n'.join(f"  {c} ({l}): {CATEGORY_HINTS.get(c, '')}" for c, l in context['categories'])
    user = (f"작업일: {context.get('work_date') or '-'}\n"
            f"현재 선택된 설비호기: {', '.join(context.get('equipment') or []) or '없음'}\n"
            f"등록된 설비호기: {', '.join(context.get('known_equipment') or [])}\n"
            f"현재 분류: {context.get('category') or '-'}\n"
            f"현재 작업시간: {context.get('start_time') or '-'}\n"
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

    def text(key):
        v = result.get(key)
        if isinstance(v, list):
            v = '\n'.join(f'- {x}' for x in str_list(v))
        return str(v or '').strip()

    sections = {k: text(k) for k in ('symptom', 'action', 'result')}
    if not any(sections.values()):
        sections = {k: fallback[k] for k in sections}
    category = result.get('category') if result.get('category') in category_codes else fallback['category']
    equipment = [e.upper() if e != common else common for e in str_list(result.get('equipment'))]
    equipment = [e for e in equipment if e == common or EQUIP_RE.fullmatch(e)]
    times = {}
    for k in ('start_time', 'end_time'):
        v = result.get(k)
        times[k] = v if isinstance(v, str) and HHMM_RE.fullmatch(v) else None
    status = result.get('status') if result.get('status') in ('ongoing', 'closed') else fallback['status']
    return {'title': (text('title') or fallback['title'])[:120], **sections, 'status': status,
            'category': category, 'equipment': list(dict.fromkeys(equipment)), 'link': text('link') or fallback['link'],
            **times, 'next_actions': str_list(result.get('next_actions'))}


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


# ─── Confluence 표 여러 행 일괄 정리 ──────────────────

ROWS_PROMPT = """너는 삼성 반도체 K2 라인 포토(노광) 설비 엔지니어의 작업이력 정리 도우미다.
Confluence 작업이력 표에서 복사한 여러 행을 받아, 각 행을 작업이력 1건으로 정리한다.
각 행은 '열이름: 값' 형식이며 열 구성은 표마다 다를 수 있다.
규칙:
- 사실만 정리하고 없는 내용을 지어내지 않는다. 수치·호기명·부품명·알람코드·벤더명은 원문 그대로 유지. 없으면 빈 문자열.
- work_date: 날짜 (YYYY-MM-DD). 연도가 없으면 기준 연도 {year} 사용. 날짜를 알 수 없으면 null.
- shift: 근무 DAY / SW / GY 중 하나 (표에 있거나 시간으로 판단 가능할 때만, 아니면 null).
- status: 완료여부 "closed" 또는 "ongoing". 표에 값이 있으면 그대로, 없으면 결론 기준으로 판단.
- equipment: 설비호기 목록 (예: ["PAA7302"]). 특정 호기가 없으면 ["공통"].
- title: 작업명 30자 이내 명사형. 표에 작업명이 있으면 그대로 사용.
- symptom / action / result: 작업내용을 1. 현상 / 2. 조치사항 / 3. 결론 으로 나눈 것. 여러 개면 "- " 개조식 줄.
- link: EDM / CTTTM 번호나 URL. category: 다음 코드 중 하나
{categories}
반드시 JSON 배열 하나만 출력한다. 입력 행과 같은 순서·같은 개수이며 각 원소의 키:
index, work_date, shift, status, equipment, title, symptom, action, result, link, category"""


def llm_organize_rows(rows, context):
    categories = '\n'.join(f"  {c} ({l}): {CATEGORY_HINTS.get(c, '')}" for c, l in context['categories'])
    body = '\n\n'.join(f"### 행 {i}\n{text}" for i, text in enumerate(rows))
    user = (f"등록된 설비호기: {', '.join(context.get('known_equipment') or [])}\n"
            f"기준 연도: {context.get('year')}\n--- 표 행 ({len(rows)}개) ---\n{body}")
    raw = chat([{'role': 'system', 'content': ROWS_PROMPT.format(categories=categories, year=context.get('year'))},
                {'role': 'user', 'content': user}], max_tokens=min(8000, 600 * len(rows) + 400))
    text = re.sub(r'^```(?:json)?|```$', '', (raw or '').strip(), flags=re.M).strip()
    start, end = text.find('['), text.rfind(']')
    if start < 0 or end < start:
        raise ValueError('LLM 응답에서 JSON 배열을 찾지 못했습니다')
    items = json.loads(text[start:end + 1])
    if not isinstance(items, list):
        raise ValueError('LLM 응답이 배열이 아닙니다')
    by_index = {}
    for pos, it in enumerate(items):
        if isinstance(it, dict):
            idx = it.get('index') if isinstance(it.get('index'), int) else pos
            by_index[idx] = it
    return by_index


def _row_extras(result):
    """행 정리 결과에서 날짜/근무만 검증해서 꺼냄."""
    d = result.get('work_date') if isinstance(result.get('work_date'), str) else None
    sh = (result.get('shift') or '').upper() if isinstance(result.get('shift'), str) else ''
    return {'work_date': d if d and re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) else None,
            'shift': sh if sh in ('DAY', 'SW', 'GY') else None}


def organize_rows(rows, rule_texts, context, chunk=10):
    """표 여러 행 → 행별 정리 결과 목록 (입력과 같은 순서).
    rows: LLM 용 '열이름: 값' 텍스트, rule_texts: 규칙 기반용 본문 텍스트.
    LLM 은 chunk 행씩 묶어서 호출, 실패한 묶음만 규칙 기반으로 폴백. 반환: (results, engine, warning)."""
    codes = {c for c, _ in context['categories']}
    common = context.get('common', '공통')
    fallbacks = [rule_organize(t, context.get('known_equipment', ()), context.get('category')) for t in rule_texts]
    rule_result = lambda fb: {**_clean(fb, fb, codes, common), 'work_date': None, 'shift': None, 'engine': 'rule'}
    if not is_enabled():
        return [rule_result(fb) for fb in fallbacks], 'rule', None
    out, failed = [], 0
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        try:
            got = llm_organize_rows(part, context)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
            print(f'[llm] organize_rows failed, fallback to rule: {type(e).__name__}')
            got, failed = {}, failed + len(part)
        for j in range(len(part)):
            fb = fallbacks[i + j]
            r = got.get(j)
            out.append({**_clean(r, fb, codes, common), **_row_extras(r), 'engine': 'llm'} if r else rule_result(fb))
    warning = f'LLM 정리 실패 {failed}행 → 규칙 기반으로 정리' if failed else None
    return out, ('llm' if failed < len(rows) else 'rule'), warning
