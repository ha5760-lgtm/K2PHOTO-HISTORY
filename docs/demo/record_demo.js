// K2 PHOTO History 데모 영상 녹화 (Playwright recordVideo)
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://localhost:5070';
const OUT_DIR = path.join(__dirname, 'video');  // 녹화 결과(.webm) 위치
const PNG_DIR = path.join(__dirname, 'png');     // 단계별 스크린샷 (자막 포함)
const W = 1280, H = 800;

const overlay = () => {
  const css = `
    #demo-cursor { position: fixed; z-index: 99999; width: 22px; height: 22px; margin: -4px 0 0 -4px; pointer-events: none;
      background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M3 2l7 19 2.5-7.5L20 11z' fill='black' stroke='white' stroke-width='1.5'/></svg>") no-repeat; transition: transform .08s; }
    #demo-cursor.down { transform: scale(.8); }
    .demo-ripple { position: fixed; z-index: 99998; width: 34px; height: 34px; margin: -17px 0 0 -17px; border-radius: 50%;
      border: 3px solid rgba(239,71,111,.85); pointer-events: none; animation: demoRipple .6s ease-out forwards; }
    @keyframes demoRipple { from { transform: scale(.3); opacity: 1; } to { transform: scale(1.6); opacity: 0; } }
    #demo-caption { position: fixed; z-index: 99997; left: 50%; bottom: 26px; transform: translateX(-50%); max-width: 80%;
      background: rgba(15,23,42,.88); color: #fff; padding: 10px 22px; border-radius: 12px; font: 600 17px/1.45 -apple-system, 'Segoe UI', sans-serif;
      box-shadow: 0 8px 30px rgba(0,0,0,.3); text-align: center; pointer-events: none; transition: opacity .25s; }
    #demo-caption small { display: block; font-weight: 400; font-size: 13px; opacity: .8; }
    #demo-caption .step { display: inline-block; background: #4361ee; border-radius: 6px; padding: 0 8px; margin-right: 8px; font-size: 13px; vertical-align: 2px; }`;
  const install = () => {
    if (document.getElementById('demo-cursor')) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const c = document.createElement('div'); c.id = 'demo-cursor'; document.body.appendChild(c);
    const cap = document.createElement('div'); cap.id = 'demo-caption'; cap.style.opacity = 0; document.body.appendChild(cap);
    const pos = JSON.parse(sessionStorage.getItem('demoPos') || '[640,400]');
    c.style.left = pos[0] + 'px'; c.style.top = pos[1] + 'px';
    document.addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
      sessionStorage.setItem('demoPos', JSON.stringify([e.clientX, e.clientY])); }, true);
    document.addEventListener('mousedown', (e) => { c.classList.add('down');
      const r = document.createElement('div'); r.className = 'demo-ripple'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
    document.addEventListener('mouseup', () => c.classList.remove('down'), true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
};

(async () => {
  fs.rmSync(OUT_DIR, { recursive: true, force: true });
  fs.rmSync(PNG_DIR, { recursive: true, force: true });
  fs.mkdirSync(PNG_DIR, { recursive: true });
  const browser = await chromium.launch();

  // 붙여넣기용 "캡처" 이미지 준비 (녹화 밖에서)
  const prep = await browser.newPage({ viewport: { width: W, height: H } });
  await prep.goto(`${BASE}/#stats`, { waitUntil: 'networkidle' });
  await prep.waitForTimeout(800);
  const capA = (await prep.locator('#chartDaily').screenshot()).toString('base64');
  const capB = (await prep.locator('#categoryBars').screenshot()).toString('base64');
  await prep.close();

  const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: OUT_DIR, size: { width: W, height: H } } });
  await ctx.addInitScript(overlay);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message));

  const wait = (ms) => p.waitForTimeout(ms);
  let step = 0;
  const caption = async (title, sub = '', ms = 1600) => {
    step += 1; extra = 0;
    await p.evaluate(([t, s, n]) => {
      const c = document.getElementById('demo-caption');
      c.innerHTML = `<span class="step">${n}</span>${t}${s ? `<small>${s}</small>` : ''}`;
      c.style.opacity = 1;
    }, [title, sub, step]);
    await wait(Math.min(ms, 700));
    await p.screenshot({ path: path.join(PNG_DIR, `${String(step).padStart(2, '0')}.png`) });
    await wait(Math.max(0, ms - 700));
  };
  // 동작 후 상태를 추가로 남김 (예: 21b.png)
  let extra = 0;
  const snap = async () => { extra += 1; await p.screenshot({ path: path.join(PNG_DIR, `${String(step).padStart(2, '0')}${'bcdefg'[extra - 1]}.png`) }); };
  const hideCaption = () => p.evaluate(() => { document.getElementById('demo-caption').style.opacity = 0; });
  const moveTo = async (sel, opts = {}) => {
    const el = p.locator(sel).first();
    await el.scrollIntoViewIfNeeded();
    const b = await el.boundingBox();
    const x = b.x + (opts.dx ?? b.width / 2), y = b.y + (opts.dy ?? b.height / 2);
    await p.mouse.move(x, y, { steps: 18 });
    await wait(250);
    return { x, y };
  };
  const click = async (sel, opts = {}) => {
    const { x, y } = await moveTo(sel, opts);
    await p.mouse.down(); await wait(80); await p.mouse.up();
    await wait(opts.after ?? 600);
  };
  const type = (text, delay = 38) => p.keyboard.type(text, { delay });
  const paste = (b64) => p.evaluate((b64) => {
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const dt = new DataTransfer(); dt.items.add(new File([bin], 'image.png', { type: 'image/png' }));
    document.querySelector('#entrySymptom').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  }, b64);

  // 1. Work History
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await wait(800);
  await caption('K2 PHOTO History — 작업이력 Confluence 표 대체', '완료여부 · 날짜/근무 · 호기명 · 작업명 · EDM/CTTTM · 작업내용(1.현상 2.조치사항 3.결론)', 2800);
  await click('#globalAuthor', { after: 300 });
  await type('홍길동', 90);
  await caption('작성자 이름은 한 번만 입력하면 브라우저에 기억', '', 1400);
  await p.mouse.move(700, 420, { steps: 15 });
  await caption('Work History: Confluence 와 같은 열 구성', '넓은 작업내용 칸에 현상 / 조치사항 / 결론을 나눠 표시', 2600);

  // 2. 작업 입력 팝업 + 메모 + 캡처 + AI 정리
  await caption('작업 입력 → 팝업에서 바로 입력', '단축키 N 또는 우하단 + 버튼도 동일', 1200);
  await click('#view-history [data-new-log]', { after: 900 });
  await caption('1. 현상 칸에 메모를 대충 몰아서 적기', '호기 · 시간 · 증상 · 한 일 · 결과를 한 줄로', 900);
  await click('#entrySymptom', { after: 200 });
  await type('pth7301 22:30-02:00 COT spin motor alarm E-3021 발생 설비 down. motor driver 교체 후 복구 dummy 5매 OK. vendor 원인 분석 회신 대기 CTTTM-240117', 26);
  await wait(500);
  await caption('캡처는 Ctrl+V 로 바로 붙여넣기', '붙이는 즉시 서버에 업로드 → 썸네일에 "저장" 표시', 900);
  await paste(capA);
  await wait(1800);
  await caption('✨ AI 정리 클릭', '작업명 · 현상 / 조치사항 / 결론 · 완료여부 · 근무 · 호기 · 분류 · CTTTM 을 자동 기입', 900);
  await click('[data-ai]', { after: 2600 });
  await caption('On-going · GY · PTH7301 · 설비 Down · CTTTM-240117 자동 입력', '현상 / 조치사항 / 결론이 칸별로 나뉨 → 확인 후 저장', 3200);
  await click('#entrySubmit', { after: 1400 });
  await caption('저장 → DB 자동 저장, 표 맨 위에 On-going 으로 표시', '', 2200);
  await caption('완료여부 배지를 클릭하면 On-going ↔ Closed 전환', '', 900);
  await click('#historyBody tr:has-text("Motor driver") .status-pill', { after: 1400 });

  // 3. 기존 기록 수정 → 캡처 바로 저장
  await caption('✏️ 수정도 같은 팝업', '기존 기록에 붙인 캡처는 그 자리에서 바로 저장', 1200);
  const row = p.locator('#historyBody tr', { hasText: 'COT spin motor' }).first();
  await row.hover(); await wait(300);
  await click('#historyBody tr:has-text("COT spin motor") [data-edit]', { after: 900 });
  await click('#entryResult', { after: 300 });
  await paste(capB);
  await wait(1800);
  await p.keyboard.press('Escape');
  await wait(900);
  await moveTo('#historyBody tr:has-text("COT spin motor") .thumbs-sm');
  await caption('썸네일 2장 — 클릭하면 크게 보기', '', 900);
  await click('#historyBody tr:has-text("COT spin motor") .thumbs-sm .thumb', { after: 1600 });
  await p.keyboard.press('Escape'); await wait(600);

  // 4. 필터 / 검색
  await caption('분류 · 호기 · 기간 · 검색어 필터', '', 900);
  await click('#filterCategory', { after: 200 });
  await p.selectOption('#filterCategory', 'DOWN'); await wait(400);
  await click('#filterForm button[type=submit]', { after: 1600 });
  await click('#filterReset', { after: 300 });
  await click('#globalSearch', { after: 200 });
  await type('leveling', 70); await p.keyboard.press('Enter');
  await wait(1200);
  await caption('상단 검색 → 하이라이트 표시', 'Ctrl+K 로 어디서든 검색', 1800);
  await click('#filterReset', { after: 600 });

  // 5. 실시간 반영
  await caption('실시간: 다른 PC에서 입력한 기록이 자동으로 나타남', '5초마다 변경 확인', 1000);
  const d = new Date(); const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  await p.request.post(`${BASE}/api/logs`, { data: { work_date: today, start_time: '15:10', end_time: '15:25', equipment: ['PAA7302'], category: 'MINOR_STOP',
    content: 'Wafer handler 순간정지 (robot timeout) → 리셋 후 정상 진행', summary: 'PAA7302 handler 순간정지', author: '이지훈' } });
  await p.waitForFunction(() => document.querySelector('#historyBody').textContent.includes('handler 순간정지'), null, { timeout: 9000 });
  await moveTo('#historyBody tr:has-text("handler 순간정지")', { dx: 520 });
  await wait(2200);

  // 6. Daily Log
  await caption('Daily Log: 화면에서 바로 연속 입력', '빠른 문구 버튼으로 현상 / 조치사항 / 결론을 클릭만으로 채우기', 1000);
  await click('[data-view="daily"]', { after: 800 });
  await click('#shiftSeg [data-shift="DAY"]', { after: 300 });
  await click('[data-equip="PTA7302"]', { after: 300 });
  await click('#categoryGrid [data-category="PM"]', { after: 300 });
  await click('#entryTitle', { after: 200 });
  await type('PTA7302 주간 PM', 45);
  await click('#entrySymptom', { after: 200 });
  await type('주간 PM 일정', 45);
  await click('.sec-action [data-quick="세정"]', { after: 500 });
  await p.keyboard.type(' (DEV cup), filter 교체', { delay: 35 });
  await click('.sec-result [data-quick="정상 복구"]', { after: 700 });
  await snap();
  await p.keyboard.press('Control+Enter');
  await wait(1200);
  await caption('Ctrl+Enter 저장 → 오늘 작업 내역에 추가', '결론에 "정상 복구" 를 고르면 완료여부가 자동으로 Closed', 2200);
  await p.mouse.wheel(0, 650); await wait(1600); await p.mouse.wheel(0, -650); await wait(500);

  // 7. Setup Dashboard
  await click('[data-view="stats"]', { after: 900 });
  await caption('Setup Dashboard: 누적 · 주간 · 14일 추이 · 분류 · 호기별', '', 2800);

  // 8. Confluence 가져오기
  await click('[data-view="io"]', { after: 700 });
  await caption('기존 Confluence 표 → 그대로 복사해서 붙여넣기', '머리글 자동 인식 · 셀 안 줄바꿈 · 병합된 날짜/근무 칸까지 유지', 1000);
  await click('#importText', { after: 200 });
  await p.evaluate(() => {
    const html = `<table><tr><th>완료여부</th><th>날짜/근무</th><th>호기명</th><th>작업명</th><th>EDM CTTTM LINK</th><th>작업내용</th></tr>
      <tr><td>Closed</td><td rowspan="2">10/14<br>DAY</td><td>PAH7304</td><td>Reticle stage 초기 Cal</td><td>EDM-50777</td><td><p>1. 현상</p><p>Reticle stage 초기 상태</p><p>2. 조치사항</p><p>Calibration, mark 인식 확인</p><p>3. 결론</p><p>인식률 99.2% 정상</p></td></tr>
      <tr><td>On-going</td><td>PSH7306</td><td>Drain 배관 누수</td><td></td><td>1. 현상<br>Drain 배관 누수<br>2. 조치사항<br>배관 재체결<br>3. 결론<br>재발 모니터링 필요</td></tr></table>`;
    const dt = new DataTransfer(); dt.setData('text/html', html); dt.setData('text/plain', 'table');
    document.querySelector('#importText').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  await wait(2200);
  await snap();
  await click('#importRun', { after: 1600 });
  await caption('CSV · JSONL(AI용) · Confluence 마크업으로 내보내기도 가능', '', 1800);

  // 9. Theme
  await caption('Theme: 디자인 컬러를 원클릭으로 변경', 'Accent 9색 + 직접 지정 · 사이드바 4종 · Light/Dark', 1000);
  await click('[data-view="history"]', { after: 600 });
  await click('button[title="디자인 컬러 변경"]', { after: 600 });
  for (const hex of ['#0d9488', '#7c3aed', '#1428a0']) await click(`[data-accent="${hex}"]`, { after: 700 });
  await click('[data-sidebar-style="accent"]', { after: 900 });
  await snap();
  await click('[data-sidebar-style="light"]', { after: 900 });
  await click('[data-mode="dark"]', { after: 1200 });
  await click('[data-accent="#e11d48"]', { after: 900 });
  await click('[data-sidebar-style="black"]', { after: 1400 });
  await snap();
  await click('#themeReset', { after: 900 });
  await p.mouse.move(700, 450, { steps: 10 });
  await p.keyboard.press('Escape');

  // 10. AI Assistant
  await click('[data-view="ai"]', { after: 900 });
  await caption('AI Assistant: 저장된 이력을 AI 입력용 JSONL 로', 'RAG 인덱싱 · 주간 리포트 · photo-ai-bot 연동 준비', 3000);
  await hideCaption();
  await click('[data-view="history"]', { after: 600 });
  await caption('K2 PHOTO History', '입력은 간단하게 · 저장은 자동으로 · 활용은 AI로', 2600);

  console.log('page errors:', JSON.stringify(errs));
  const video = p.video();
  await ctx.close();
  console.log('video:', await video.path());
  await browser.close();
})();
