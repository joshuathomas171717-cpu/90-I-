/** Phase 14 browser smoke + axe. Dev-only; Python/static shipping needs no Node runtime.
 * bash tools/setup_browser_tools.sh
 * NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/player-layer.mjs
 * Optional: --url https://90plus-cyan.vercel.app --out /tmp/player-layer-audit.json
 */
import {writeFileSync} from 'node:fs';
const MODULES = process.env.NT90_PLAYWRIGHT_MODULES || '/tmp/a11y/node_modules';
const {chromium} = await import(`${MODULES}/playwright/index.mjs`);
const args = process.argv.slice(2);
const arg = (name, fallback) => { const i=args.indexOf(name); return i<0 ? fallback : args[i+1]; };
const base = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/,'');
const out = arg('--out', '/tmp/player-layer-audit.json');
const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
const report = {url:base, errors:[], externalRequests:[], viewports:[]};
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  page.on('pageerror', e=>report.errors.push(e.message));
  page.on('request', r=>{
    if(!r.url().startsWith(base+'/') && !r.url().startsWith('data:')) report.externalRequests.push(r.url());
  });
  await page.goto(base+'/', {waitUntil:'networkidle'});
  await page.locator('#tabbtn-model').click();
  report.notice = await page.locator('#playerGateStatus').innerText();
  await page.locator('#playerGatePanel a').click();
  await page.waitForLoadState('networkidle');
  report.title = await page.title();
  await page.addScriptTag({path:`${MODULES}/axe-core/axe.min.js`});
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
    await page.setViewportSize(viewport);
    const result = await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    const width = await page.evaluate(()=>({document:document.documentElement.scrollWidth,screen:innerWidth}));
    report.viewports.push({viewport,width, violations:result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.html)})),
                           incomplete:result.incomplete.map(v=>v.id)});
  }
  const response = await page.request.get(base+'/player-model.json');
  const data = await response.json();
  report.download = {status:response.status(),mode:data.context.mode,players:data.context.coverage.players};
  const failed = report.errors.length || report.externalRequests.length || response.status() !== 200
    || report.viewports.some(v=>v.violations.length || v.width.document>v.width.screen);
  report.ok = !failed;
  writeFileSync(out,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
  process.exitCode = failed ? 1 : 0;
} finally {
  await browser.close();
}
