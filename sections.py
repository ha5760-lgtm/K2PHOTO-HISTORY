"""작업내용 3단 구성 (1. 현상 / 2. 조치사항 / 3. 결론) — app.py 와 llm.py 공용."""
import re

SECTIONS = [('symptom', '1. 현상'), ('action', '2. 조치사항'), ('result', '3. 결론')]
SECTION_KEYS = [k for k, _ in SECTIONS]
SECTION_HEAD_RE = re.compile(
    r'^\s*(?:\d\s*[.)]\s*)?[\[(]?\s*(현상|문제|증상|조치\s*사항|조치내용|조치|결론|결과|작업명)\s*[\])]?\s*[:：]?\s*', re.M)
SECTION_ALIASES = {'현상': 'symptom', '문제': 'symptom', '증상': 'symptom', '조치사항': 'action', '조치': 'action',
                   '조치내용': 'action', '결론': 'result', '결과': 'result', '작업명': 'title'}


def parse_sections(text):
    """'1. 현상 … 2. 조치사항 … 3. 결론 …' (또는 [현상] …) → dict. 머리말이 하나도 없으면 None.
    '[작업명] …' 머리말이 있으면 'title' 키로 함께 반환."""
    text = text or ''
    heads = list(SECTION_HEAD_RE.finditer(text))
    if not heads:
        return None
    out = {k: '' for k in SECTION_KEYS}
    lead = text[:heads[0].start()].strip()
    for i, m in enumerate(heads):
        key = SECTION_ALIASES[re.sub(r'\s+', '', m[1])]
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        out[key] = (out.get(key, '') + '\n' + body).strip() if out.get(key) else body
    if lead:
        out['symptom'] = (lead + '\n' + out['symptom']).strip()
    return out


def compose_content(parts):
    """현상/조치/결론 → Confluence 작업내용 칸 형식 텍스트 (검색·내보내기용)."""
    return '\n\n'.join(f'{label}\n{parts[k].strip()}' for k, label in SECTIONS if (parts.get(k) or '').strip())
