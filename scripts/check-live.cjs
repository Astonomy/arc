// Run against a disposable workflow served with reqflow serve --no-open.
const { chromium } = require(process.argv[2]);
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(process.argv[3]);
    await page.locator('#stages').getByText('等待目标', { exact: true }).waitFor();
    fs.writeFileSync(path.join(process.argv[4], 'analysis.yaml'), 'status: pending\nquestions:\n  - id: Q-1\n    question: Clarify expected result\n');
    await page.locator('#stages').getByText('1 项待开发者回答', { exact: true }).waitFor();
    if (errors.length) throw Error(errors.join('\n'));
    console.log(JSON.stringify({ live_refresh: 'passed', page_errors: errors }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
