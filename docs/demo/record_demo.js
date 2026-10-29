// K2 PHOTO History 데모 영상 녹화 (Playwright recordVideo)
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://localhost:5070';
const OUT_DIR = path.join(__dirname, 'video');  // 녹화 결과(.webm) 위치
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
    step += 1;
    await p.evaluate(([t, s, n]) => {
      const c = document.getElementById('demo-caption');
      c.innerHTML = `<span class="step">${n}</span>${t}${s ? `<small>${s}</small>` : ''}`;
      c.style.opacity = 1;
    }, [title, sub, step]);
    await wait(ms);
  };
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
    document.querySelector('#entryContent').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  }, b64);

  // 1. Work History
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await wait(800);
  await caption('K2 PHOTO History — 라인 셋업 일일 작업이력', 'Confluence 표(날짜 · 작업시간 · 설비호기 · 작업내용 · 요약)를 대체', 2600);
  await click('#globalAuthor', { after: 300 });
  await type('홍길동', 90);
  await caption('작성자 이름은 한 번만 입력하면 브라우저에 기억', '', 1400);
  await p.mouse.move(700, 420, { steps: 15 });
  await caption('Work History: 날짜별로 묶인 작업 이력 표', '분류별 색 배지 · 호기 배지 · 캡처 썸네일', 2400);

  // 2. 작업 입력 팝업 + 메모 + 캡처 + AI 정리
  await caption('작업 입력 → 팝업에서 바로 입력', '단축키 N 또는 우하단 + 버튼도 동일', 1200);
  await click('#view-history [data-new-log]', { after: 900 });
  await caption('메모는 대충 적어도 OK', '호기 · 시간 · 내용을 한 줄로', 900);
  await type('pth7301 10:00-13:30 COT spin motor alarm 발생 설비 down. motor driver 교체 후 복구 dummy 5매 OK. 내일 vendor 원인 분석 회신 예정', 28);
  await wait(500);
  await caption('캡처는 Ctrl+V 로 바로 붙여넣기', '붙이는 즉시 서버에 업로드 → 썸네일에 "저장" 표시', 900);
  await paste(capA);
  await wait(1800);
  await caption('✨ AI 정리 클릭', '개조식 내용 · 요약 · 분류 · 호기 · 작업시간을 자동 기입', 900);
  await click('[data-ai]', { after: 2400 });
  await caption('설비 Down / PTH7301 / 10:00~13:30 / 요약이 채워짐', '이슈 · 후속 조치 목록, 되돌리기 지원 → 확인 후 저장', 3000);
  await click('#entrySubmit', { after: 1400 });
  await caption('저장 → DB 자동 저장, 표에 바로 반영', '', 2200);

  // 3. 기존 기록 수정 → 캡처 바로 저장
  await caption('✏️ 수정도 같은 팝업', '기존 기록에 붙인 캡처는 그 자리에서 바로 저장', 1200);
  const row = p.locator('#historyBody tr', { hasText: 'COT spin motor' }).first();
  await row.hover(); await wait(300);
  await click('#historyBody tr:has-text("COT spin motor") [data-edit]', { after: 900 });
  await click('#entryContent', { dx: 300, dy: 120, after: 300 });
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
  await caption('Daily Log: 화면에서 바로 연속 입력', '시간 프리셋 · 호기 칩 · 분류 · 넓은 작업내용 칸', 1000);
  await click('[data-view="daily"]', { after: 800 });
  await click('[data-time-preset="day"]', { after: 500 });
  await click('[data-equip="PTA7302"]', { after: 300 });
  await click('#categoryGrid [data-category="PM"]', { after: 300 });
  await click('#entryContent', { after: 200 });
  await type('주간 PM: DEV cup 세정, filter 교체, 배기압 확인 OK', 30);
  await wait(400);
  await p.keyboard.press('Control+Enter');
  await wait(1200);
  await caption('Ctrl+Enter 저장 → 오늘 작업 내역 타임라인에 추가', '다음 작업 시작시간 = 직전 종료시간', 2000);
  await p.mouse.wheel(0, 500); await wait(1400); await p.mouse.wheel(0, -500); await wait(500);

  // 7. Setup Dashboard
  await click('[data-view="stats"]', { after: 900 });
  await caption('Setup Dashboard: 누적 · 주간 · 14일 추이 · 분류 · 호기별', '', 2800);

  // 8. Confluence 가져오기
  await click('[data-view="io"]', { after: 700 });
  await caption('기존 Confluence 표 → 복사해서 붙여넣기로 일괄 이관', '병합된 날짜 칸은 윗 행 날짜를 이어받음', 1000);
  await click('#importText', { after: 200 });
  await p.fill('#importText', '날짜\t작업시간\t설비호기\t작업내용\t요약\n10/14\t09:00~12:00\tPAH7304\tReticle stage 초기 Cal\tReticle Cal\n\t13:00~16:00\t공통\t셋업 일정 협의 회의\t\n10/15\t08:30~11:00\tPSH7306\tDrain 배관 누수 수리\t누수 수리');
  await wait(900);
  await click('#importPreview', { after: 1800 });
  await click('#importRun', { after: 1600 });
  await caption('CSV · JSONL(AI용) · Confluence 마크업으로 내보내기도 가능', '', 1800);

  // 9. Theme
  await caption('Theme: 디자인 컬러를 원클릭으로 변경', 'Accent 9색 + 직접 지정 · 사이드바 4종 · Light/Dark', 1000);
  await click('[data-view="history"]', { after: 600 });
  await click('button[title="디자인 컬러 변경"]', { after: 600 });
  for (const hex of ['#0d9488', '#7c3aed', '#1428a0']) await click(`[data-accent="${hex}"]`, { after: 700 });
  await click('[data-sidebar-style="accent"]', { after: 900 });
  await click('[data-sidebar-style="light"]', { after: 900 });
  await click('[data-mode="dark"]', { after: 1200 });
  await click('[data-accent="#e11d48"]', { after: 900 });
  await click('[data-sidebar-style="black"]', { after: 1400 });
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
