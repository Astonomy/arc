// Optional visual QA using an existing Playwright installation, not a runtime dependency.
const { chromium } = require(process.argv[2]);
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const report = path.resolve(process.argv[3]);
  await page.goto(pathToFileURL(report).href);
  await page.locator('#canvas-tree .node').last().click();
  await page.locator('#node-details').getByText(/accepted/).waitFor();
  await page.locator('#zoom-in').click();
  await page.locator('#fit').click();
  await page.locator('.connection.artifact').first().waitFor({state:'attached'});
  const centered = await page.evaluate(() => {
    const groups = ['canvas-tree', 'interface-nodes', 'test-nodes'].map(id => {
      const group = document.getElementById(id), box = group.getBoundingClientRect();
      const items = [...group.children].map(n => n.getBoundingClientRect());
      return Math.abs((items[0].top + items.at(-1).bottom)/2 - (box.top + box.bottom)/2) < 2;
    });
    return groups.every(Boolean);
  });
  if (!centered) throw Error('Lane content is not vertically centered');
  await page.locator('#toggle-if').click();
  await page.locator('#interfaces').waitFor({state:'hidden'});
  await page.locator('#toggle-if').click();
  await page.screenshot({ path: path.join(path.dirname(report), 'canvas.png'), fullPage: true });
  await page.locator('#records').click();
  await page.getByRole('button', { name: 'REQ-ADD · 两数相加', exact: true }).click();
  await page.locator('#detail').getByText(/accepted/).waitFor();
  await page.getByLabel('筛选需求').fill('REQ-ADD');
  await page.getByRole('button', { name: 'REQ-ADD · 两数相加', exact: true }).waitFor();
  await page.screenshot({ path: path.join(path.dirname(report), 'desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await page.screenshot({ path: path.join(path.dirname(report), 'mobile.png'), fullPage: true });
  await page.locator('#back').click();
  await page.screenshot({path:path.join(path.dirname(report),'canvas-mobile.png'),fullPage:true});
  const canvasOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  const result = { page_errors: errors, mobile_overflow: overflow||canvasOverflow, requirement_selection: 'passed', filter: 'passed', artifact_connections:'passed', vertical_centering:'passed' };
  fs.writeFileSync(path.join(path.dirname(report), 'browser-check.json'), JSON.stringify(result, null, 2));
  await browser.close();
  console.log(JSON.stringify(result));
  if (errors.length || overflow) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
