// Real Chromium regression checks using mock HTTP responses; no AI calls.
// Run: node tests/browser_smoke.cjs (requires playwright + Chromium).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    let revision = 60, detailRequests = 0, fullRequests = 0;
    const jobs = Array.from({length: 60}, (_, i) => ({
      id: `job-${60-i}`, title: `工作 ${60-i}`, provider: 'mock', status: 'succeeded',
      priority: 5, created_at: i+1, updated_at: i+1, revision: 60-i, next_run_at: 0,
      step_index: 1, steps_count: 1, next_step: '', attempts: 1, last_error: '',
      session_id: null, output_count: 1, has_partial: false, retry_source: null
    }));
    const html = fs.readFileSync(path.join(__dirname, '../relay/static/index.html'), 'utf8');
    await page.route('http://relay.test/**', async route => {
      const url = new URL(route.request().url());
      let data;
      if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (url.pathname === '/api/state') {
        const p = Number(url.searchParams.get('page') || 0);
        const since = url.searchParams.has('since') ? Number(url.searchParams.get('since')) : -1;
        if (since === -1) fullRequests++;
        const rows = jobs.slice(p*50, (p+1)*50);
        data = {jobs: rows.filter(j => j.revision > since), job_order: rows.map(j => j.id),
          revision, page: p, pages: Math.ceil(jobs.length/50), page_size: 50,
          total_jobs: jobs.length, counts: {succeeded: jobs.length}, events: [], now: Date.now()/1000,
          paused: true, providers: {mock: true, codex: false}, quota: {}, workspace: '/work', csrf_token: 'test'};
      } else if (url.pathname.startsWith('/api/jobs/')) {
        detailRequests++;
        const j = jobs.find(j => j.id === url.pathname.split('/').pop());
        data = {...j, steps: ['分析'], cwd: '/work', outputs: [Array.from({length: 300}, (_,i)=>`RESULT LINE ${i}`).join('\n')], partial_output: ''};
      } else return route.fulfill({status: 404, body: '{}'});
      await route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
    });
    await page.goto('http://relay.test/');
    await page.waitForFunction(() => document.querySelectorAll('.job').length === 50);
    assert.equal(detailRequests, 0, 'summary render must not fetch outputs');
    await page.locator('.job details summary').first().click();
    await page.waitForFunction(() => document.querySelector('.job pre')?.textContent.includes('RESULT LINE'));
    await page.evaluate(() => {
      const pre = document.querySelector('.job pre');
      window.savedPre = pre;
      pre.scrollTop = 150;
      window.savedScroll = pre.scrollTop;
      const range = document.createRange();
      range.setStart(pre.firstChild, 0); range.setEnd(pre.firstChild, 12);
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      window.savedSelection = selection.toString();
    });
    // Change a different job and poll several times. The reader's DOM must survive.
    jobs[1].revision = ++revision; jobs[1].last_error = 'Changed metadata';
    await page.evaluate(async () => { for (let i=0;i<3;i++) await refresh(); });
    const preserved = await page.evaluate(() => ({
      node: savedPre === document.querySelector('.job pre'),
      scroll: savedPre.scrollTop === savedScroll,
      selection: window.getSelection().toString() === savedSelection,
      open: document.querySelector('.job details').open
    }));
    assert.deepEqual(preserved, {node:true, scroll:true, selection:true, open:true});
    assert.equal(detailRequests, 1, 'unchanged output must not reload');
    await page.locator('#nextPage').click();
    await page.waitForFunction(() => document.querySelectorAll('.job').length === 10);
    const before = fullRequests;
    jobs.unshift({...jobs[0], id: 'new-job', title: '<script>not executable</script>', revision: ++revision});
    await page.evaluate(() => refresh());
    await page.waitForFunction(() => document.querySelectorAll('.job').length === 11);
    assert.equal(fullRequests, before + 1, 'new page member needs exactly one full summary fetch');
    const ids = await page.locator('.job').evaluateAll(nodes => nodes.map(n=>n.dataset.job));
    assert.deepEqual(ids, jobs.slice(50).map(j=>j.id));
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('PASS: lazy outputs; stable DOM/selection/scroll; delta page membership; mobile width');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
