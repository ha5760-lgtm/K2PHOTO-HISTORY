"""데모 데이터 생성 (최근 14일 K2 라인 셋업 작업). 기존 DB 는 유지하고 work_logs 만 비운 뒤 채움."""
import random
from datetime import date, timedelta
import app as k2

AUTHORS = ['김민수', '이지훈', '박서연', '최현우']
# (분류, 호기, 시작, 종료, 완료여부, 작업명, 1.현상, 2.조치사항, 3.결론, EDM/CTTTM)
TEMPLATES = [
    ('SETUP', ['PAA7302'], '08:30', '11:30', 'closed', 'PAA7302 본체 반입', 'Scanner 본체 반입 일정 (ASML FSE 3명 지원)',
     '- 반입 경로 floor load 확인\n- 위치 Marking 확인 후 안착', '반입 완료, 내주 Hook-up 진행', ''),
    ('SETUP', ['PAA7302', 'PAH7304'], '13:00', '17:00', 'ongoing', 'PCW / CDA / Exhaust Hook-up 점검',
     'Hook-up 후 유틸 압력 점검 필요', '- PCW 유량, Exhaust 정압 측정\n- PAH7304 CDA 압력 0.42MPa (spec 0.5↑) 확인', 'PAH7304 CDA 압력 낮음 → 설비팀 조치 요청, 회신 대기', 'EDM-50213'),
    ('SETUP', ['PTA7302'], '09:00', '10:30', 'closed', 'PTA7302 Power-on', 'Track 최초 Power-on', 'Interlock / EMO 동작 점검', '정상, S/W 셋업 진행 가능', ''),
    ('SETUP', ['PTH7304'], '10:30', '12:00', 'closed', 'Track S/W 설치 · Host 연동', '신규 Track S/W 미설치 상태', 'S/W 설치 후 Host 연동 테스트 (EAP 통신)', '통신 정상', ''),
    ('SETUP', ['PAA7302'], '14:30', '18:00', 'ongoing', 'Wafer stage leveling 1차', 'Leveling 초기값 spec-out (Z 0.35um)',
     'Z offset 재조정', '1차 spec-in, 내일 재측정 예정', ''),
    ('PROCESS', ['PTA7302', 'PAA7302'], '09:00', '15:00', 'ongoing', 'Inline Dummy Run 25매', 'Inline 연결 후 첫 Run',
     'Dummy wafer 25매 Run, CD 측정', 'CD uniformity 3σ 2.4nm → 개선 필요', ''),
    ('COMMON', ['공통'], '16:00', '17:00', 'closed', '주간 셋업 일정 회의', '설비/공정/벤더 주간 점검', '호기별 일정 리뷰',
     'PCH7306 반입 1주 지연 공유', ''),
    ('SIMPLE', ['공통'], None, None, 'closed', '클린룸 출입 교육', '신규 벤더 인원 5명 출입 필요', '출입 교육 진행', '이수 완료', ''),
    ('SETUP', ['PSH7306'], '08:00', '12:00', 'closed', 'Drain / Solvent 배관 연결', 'SEMES Track 배관 미연결', 'Drain / Solvent 배관 연결 후 누수 점검', '누수 없음', ''),
    ('SETUP', ['PCH7306'], '13:00', '16:30', 'closed', 'Reticle stage 초기 Calibration', 'Reticle stage 초기 상태',
     'Calibration, Alignment mark 인식 확인', '인식률 99.2% 정상', ''),
    ('SETUP', ['PAH7304'], '14:00', '16:00', 'ongoing', 'Recipe download · Host 등록', 'Recipe 미등록', 'Recipe download 및 Host 등록',
     'Job 이름 규칙 협의 필요', ''),
    ('DOWN', ['PTH7301'], '22:30', '02:00', 'closed', 'COT spin motor 교체', 'COT unit spin motor alarm (E-3021) 발생 → 설비 Down',
     '- Motor driver 교체\n- Dummy 5매 확인', '정상 복구, 생산 재개. Vendor 원인 분석 회신 받음', 'CTTTM-240117'),
    ('MINOR_STOP', ['PAA7302'], '15:10', '15:25', 'closed', 'Handler robot timeout 순간정지', 'Wafer handler robot timeout 으로 순간정지',
     '리셋', '정상 진행, 재발 시 robot teaching 점검', ''),
    ('PM', ['PTA7302'], '07:00', '10:00', 'closed', 'PTA7302 주간 PM', '주간 PM 일정', '- DEV cup 세정\n- Filter 교체', 'PM 완료, 배기압 정상', ''),
    ('PROCESS', ['PAH7304'], '13:00', '15:00', 'closed', 'Focus 조정 CD 균일도 개선', 'CD uniformity 3σ 2.1nm',
     'Focus offset 미세 조정', '3σ 1.6nm 로 개선, 적용 완료', ''),
]


def run():
    k2.init_db()
    conn = k2.get_db()
    conn.execute('DELETE FROM work_logs')
    conn.commit()
    conn.close()
    random.seed(73)
    client = k2.app.test_client()
    for back in range(13, -1, -1):
        d = date.today() - timedelta(days=back)
        if d.weekday() == 6:
            continue
        for cat, eq, s, e, status, title, symptom, action, result, link in random.sample(TEMPLATES, random.randint(2, 4)):
            client.post('/api/logs', json={
                'work_date': d.isoformat(), 'start_time': s, 'end_time': e, 'equipment': eq, 'category': cat,
                'status': status if back < 4 else 'closed',  # 오래된 건 대부분 종료
                'title': title, 'symptom': symptom, 'action': action, 'result': result, 'link': link,
                'shift': None if s else random.choice(['DAY', 'SW']), 'author': random.choice(AUTHORS),
            })
    print('seeded', client.get('/api/stats').get_json()['total_count'], 'logs')


if __name__ == '__main__':
    run()
