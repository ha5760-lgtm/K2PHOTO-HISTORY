"""데모 데이터 생성 (최근 14일 K2 라인 셋업 작업). 기존 DB 는 유지하고 work_logs 만 비운 뒤 채움."""
import random
from datetime import date, timedelta
import app as k2

AUTHORS = ['김민수', '이지훈', '박서연', '최현우']
TEMPLATES = [
    ('MOVE_IN', ['PAA7302'], '08:30', '11:30', 'Scanner 본체 반입 및 위치 Marking 확인\n- 반입 경로 floor load 확인 완료\n- 벤더(ASML) FSE 3명 지원', 'PAA7302 본체 반입 완료'),
    ('HOOKUP', ['PAA7302', 'PAH7304'], '13:00', '17:00', 'PCW / CDA / Exhaust Hook-up 점검\n- PAH7304 CDA 압력 낮음 → 설비팀 요청', ''),
    ('POWER_ON', ['PTA7302'], '09:00', '10:30', 'Track Power-on 및 Interlock 점검\n- EMO 동작 확인 OK', 'PTA7302 Power-on OK'),
    ('SW', ['PTH7304'], '10:30', '12:00', 'Track S/W 설치, Host 연동 테스트 (EAP 통신 확인)', ''),
    ('CAL', ['PAA7302'], '13:30', '18:00', 'Wafer stage leveling 확인, Z offset 재조정\n- 1차 결과 spec-in, 내일 재측정 예정', 'Stage leveling 1차 spec-in'),
    ('QUAL', ['PTA7302', 'PAA7302'], '09:00', '15:00', 'Inline 연결 후 Dummy wafer 25매 Run\n- CD uniformity 확인 필요', 'Inline Dummy Run 25매'),
    ('MEETING', [k2.COMMON], '16:00', '17:00', '주간 셋업 일정 점검 회의 (설비/공정/벤더)\n- PCH7306 반입 일정 1주 지연 공유', '주간 셋업 회의'),
    ('ETC', [k2.COMMON], None, None, '클린룸 출입 교육 이수 (신규 벤더 인원 5명)', ''),
    ('HOOKUP', ['PSH7306'], '08:00', '12:00', 'SEMES Track Drain / Solvent 배관 연결, 누수 점검', ''),
    ('CAL', ['PCH7306'], '13:00', '16:30', 'Reticle stage 초기 Calibration, Alignment mark 인식 확인', ''),
    ('SW', ['PAH7304'], '14:00', '16:00', 'Recipe download 및 Host 등록\n- Job 이름 규칙 협의 필요', 'Recipe download 완료'),
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
        for cat, eq, s, e, content, summary in random.sample(TEMPLATES, random.randint(2, 4)):
            client.post('/api/logs', json={
                'work_date': d.isoformat(), 'start_time': s, 'end_time': e, 'equipment': eq,
                'category': cat, 'content': content, 'summary': summary,
                'author': random.choice(AUTHORS),
            })
    print('seeded', client.get('/api/stats').get_json()['total_count'], 'logs')


if __name__ == '__main__':
    run()
