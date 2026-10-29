# K2 PHOTO History

K2 라인 셋업 기간의 **일일 작업내용을 간단히 입력 → DB 자동 저장 → AI 활용**하기 위한 대시보드입니다.
Confluence 페이지 표(날짜 / 작업시간 / 설비호기·공통 / 작업내용 / 요약)로 관리하던 방식을 대체합니다.

디자인은 `equip-history`(EquipBoard) 의 사이드바·KPI 카드·작업유형 버튼 스타일을, 구조와 설비 호기 명명 규칙은 `fdc-dashboard`(Flask + sqlite3) 를 따릅니다.

## 화면

| Work History (Confluence 표 대체) | New Work Log 팝업 (캡처 + AI 정리) |
|---|---|
| ![history](docs/screenshots/history.png) | ![popup](docs/screenshots/1_entry_popup.png) |
| **Daily Log (컴팩트 입력)** | **Theme 패널 (Accent / Sidebar / Mode)** |
| ![daily](docs/screenshots/2_daily.png) | ![theme](docs/screenshots/theme_teal.png) |
| **Setup Dashboard** | **Dark + Rose 테마** |
| ![stats](docs/screenshots/stats.png) | ![dark](docs/screenshots/theme_dark_rose.png) |

## 기능

메뉴: **Work History**(기본 화면) · **Daily Log** · **Setup Dashboard** · **Import / Export** · **AI Assistant**

- **작업 입력 팝업**: Work History 의 `작업 입력` 버튼, 우하단 `+` 버튼, 또는 `N` 키 → 팝업에서 입력. 이력의 ✏️ 수정도 같은 팝업
  - 왼쪽에 날짜·시간·호기·분류·요약, 오른쪽에 넓은 작업내용 칸(팝업 440px+, 크기 조절 가능)
  - `저장`(닫기) / `저장 후 계속`(연속 입력), 수정 시 `삭제`. Daily Log 화면과 같은 폼이라 임시보관·단축키 동일
- **테마**: 상단 `Theme` → Accent 9색 + 직접 선택(#RRGGBB), Sidebar(Navy/Black/Accent/Light), Light/Dark, 기본값 복원.
  브라우저에 저장되며, 모든 색은 CSS 변수(`--primary*`, `--sidebar-*`)로 연결 → 새 프리셋은 `static/js/theme.js` 의 `ACCENTS` 에 한 줄 추가
- **입력 항목**: 날짜(◀ ▶ / 오늘), 작업시간(지금·+30분·+1h·+2h·+4h·주간 프리셋, 소요시간 자동 계산·야간 자정 넘김 지원),
  설비호기 칩 다중 선택 또는 `공통`, 셋업 분류(반입/설치, Hook-up/유틸, Power-on, S/W, Calibration, 공정 Qual, 회의, 기타), 작업내용, 요약
  - `Ctrl+Enter` 저장, 저장 후 다음 작업 시작시간 = 직전 종료시간
  - 요약을 비우면 작업내용 첫 줄로 자동 요약 (`자동` 태그) → 추후 LLM 요약으로 교체 예정
  - 입력 중 내용은 브라우저에 임시 보관 (새로고침해도 유지)
- **캡처 붙여넣기**: 작업내용 칸에서 `Ctrl+V` (또는 드래그&드롭) → 즉시 서버 업로드, 썸네일 바로 표시
  - 새 작업 입력 중: 서버에 먼저 저장되고, 작업 저장 시 그 기록에 연결
  - 기존 기록 수정 중(폼/수정 모달): 해당 기록에 바로 저장 → 목록에 즉시 반영
  - 썸네일 클릭 시 크게 보기, `×` 로 삭제. 파일은 `uploads/YYYYMM/` 에 저장
  - 엑셀처럼 텍스트+이미지가 함께 복사된 경우는 텍스트 붙여넣기 우선
- **AI 정리** (`✨ AI 정리` 버튼 또는 `Alt+A`): 대충 적은 메모 → 개조식 작업내용(후속 조치는 `▶ 후속:`), 40자 요약,
  분류, 설비호기, 작업시간을 자동 기입. 이슈/후속 조치 목록 표시, `되돌리기` 지원. 저장 전 확인용
- **실시간 반영**: 5초마다 변경 여부를 확인해 다른 사람이 입력/수정한 기록을 자동으로 보여줌 (새 항목 하이라이트)
- **작업 이력**: 날짜별 묶음 표, 기간/호기/분류/검색어 필터, 검색어 하이라이트, 수정·삭제
- **셋업 현황**: 누적/이번 주 건수·시간, 최근 14일 추이, 분류별 비중, 호기별 작업량 (클릭 시 이력 필터)
- **가져오기**: Confluence 표를 복사(탭 구분)해서 붙여넣으면 미리보기 후 일괄 등록 (병합된 날짜 셀은 윗 행 날짜 상속)
- **내보내기**: CSV(Excel, BOM 포함) / JSONL(AI·RAG용) / Confluence wiki markup 표 복사
- 다크 모드, 사이드바 접기, `Ctrl+K` 검색

## 실행

```bash
pip install -r requirements.txt
python seed_data.py   # (선택) 최근 14일 데모 데이터 — work_logs 를 비우고 다시 채움
python app.py         # http://localhost:5070
```

- DB: `k2photo_history.db` (SQLite, 환경변수 `K2PH_DB` 로 경로 변경)
- 포트: 환경변수 `PORT` (기본 5070)
- 캡처 저장 경로: 환경변수 `K2PH_UPLOADS` (기본 `./uploads`)

### AI 정리 (LLM) 설정

photo-ai-bot / equip-history 와 같은 OpenAI 호환 설정을 사용합니다. 설정이 없으면 **규칙 기반**(호기명·시간·분류 키워드 인식)으로 동작하고,
LLM 호출이 실패해도 규칙 기반으로 자동 폴백합니다.

```bash
export LLM_API_URL=https://api.x.ai/v1      # 사내 게이트웨이 주소로 교체 가능 (/chat/completions 는 자동 부착)
export LLM_API_KEY=<key>                    # 키가 필요 없는 사내 서버면 생략
export LLM_MODEL=grok-4-fast-non-reasoning  # 선택
```
- Bootstrap / Bootstrap Icons / Chart.js 는 `static/vendor/` 에 포함 → 사내망(CDN 차단)에서도 동작

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/meta` | 설비호기·분류·작성자 목록 |
| POST | `/api/equipment` | 호기 추가 `{"name": "PAA7308"}` |
| GET | `/api/logs` | 조회 (`date_from`, `date_to`, `equipment`, `category`, `author`, `q`, `limit`) |
| POST | `/api/logs` | 등록 |
| PUT / DELETE | `/api/logs/<id>` | 수정 / 삭제 |
| GET | `/api/stats` | 현황 집계 |
| POST | `/api/attachments` | 캡처 업로드 (multipart `file`, 선택 `log_id`) |
| DELETE | `/api/attachments/<id>` | 캡처 삭제 |
| POST | `/api/ai/organize` | AI 정리 (`content`, `equipment`, `category`, `work_date`) |
| GET | `/api/version` | 실시간 갱신용 변경 감지 |
| POST | `/api/import` | Confluence 표 붙여넣기 가져오기 (`dry_run` 지원) |
| GET | `/api/export.csv`, `/api/export.jsonl`, `/api/export/confluence` | 내보내기 (조회와 같은 필터) |

## AI 활용 계획

1. ~~AI 정리 버튼~~ (완료, `llm.py`) → 캡처 이미지까지 읽는 비전 모델 연동
2. 기간·호기별 주간 셋업 리포트 자동 생성
3. `/api/export.jsonl` 의 `text` 필드를 photo-ai-bot RAG 인덱스 소스로 연결

## 테스트

```bash
pip install -r requirements-dev.txt
pytest -q
```
