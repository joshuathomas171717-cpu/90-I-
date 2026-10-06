/** Phase 15 browser regression: named profiles, mobile layout, squad sources and XSS.
 * Dev-only: bash tools/setup_browser_tools.sh, then NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/wave15.mjs
 * --url https://90plus-cyan.vercel.app --out /tmp/wave15.json
 */
import {writeFileSync,readFileSync} from 'node:fs';
const modules=process.env.NT90_PLAYWRIGHT_MODULES||'/tmp/a11y/node_modules';
const {chromium}=await import(`${modules}/playwright/index.mjs`);
const args=process.argv.slice(2),arg=(n,d)=>{const i=args.indexOf(n);return i<0?d:args[i+1]};
const base=arg('--url','http://127.0.0.1:8000').replace(/\/$/,''),out=arg('--out','/tmp/wave15.json');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const report={url:base,errors:[],outside:[],widths:[],audits:[]};
function check(ok,message){if(!ok)throw new Error(message)}
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 const page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(e.message));
 page.on('request',r=>{if(!r.url().startsWith(base+'/')&&!r.url().startsWith('data:'))report.outside.push(r.url())});
 await page.goto(base+'/',{waitUntil:'networkidle'});await page.locator('#tabbtn-table').click();
 report.squadCards=await page.locator('#squadPlayers .squad-card').count();
 check(report.squadCards>=4,'Arsenal squad panel missing');check(await page.locator('#squadPlayers').innerText().then(t=>t.includes('Trend unavailable')),'Season totals fabricated a trend');
 await page.addScriptTag({path:`${modules}/axe-core/axe.min.js`});
 for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
  await page.setViewportSize(viewport);
  for(const tab of ['matchweek','table','awards','duel','whatif','model']){
   await page.locator('#tabbtn-'+tab).click();const width=await page.evaluate(()=>({document:document.documentElement.scrollWidth,screen:innerWidth}));
   report.widths.push({viewport:viewport.width,tab,...width});check(width.document<=width.screen+1,'Horizontal document overflow: '+tab);
  }
  await page.locator('#tabbtn-table').click();
  let audit=await page.evaluate(()=>axe.run(document.getElementById('squadPanel'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
  report.audits.push({viewport:viewport.width,scope:'squad',violations:audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.html)})),incomplete:audit.incomplete.map(v=>v.id)});
  await page.locator('#tabbtn-whatif').click();
  audit=await page.evaluate(()=>axe.run(document.getElementById('scenarioForm'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
  report.audits.push({viewport:viewport.width,scope:'named scenarios',violations:audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.html)})),incomplete:audit.incomplete.map(v=>v.id)});
 }
 await page.locator('#scenPlayerSearch').fill('haaland');
 await page.locator('input.inj[data-pid="haaland"]').evaluate(el=>{el.value=4;el.dispatchEvent(new Event('input',{bubbles:true}))});
 const frozen=await page.evaluate(()=>JSON.parse(JSON.stringify(SCENARIO.player_effects)));
 check(frozen.haaland.model==='replacement-share/1','No frozen effect');
 check((await page.locator('input.inj[data-pid="haaland"]').getAttribute('aria-valuetext')).includes('4'),'Slider accessible value did not update');
 await page.locator('#scenName').fill('Haaland four matches — frozen range');await page.locator('#saveScen').click();
 check(await page.evaluate(()=>NT90_STORE.scenarios()[0].scenario.player_effects.haaland.attack===SCENARIO.player_effects.haaland.attack),'Save dropped profile');
 const token=await page.evaluate(()=>window.NT90_SHARE.encode(SCENARIO));check(token.startsWith('v2-'),'New profile link is not v2');
 const second=await context.newPage();second.on('pageerror',e=>report.errors.push(e.message));
 await second.goto(base+'/whatif#s='+token,{waitUntil:'networkidle'});
 report.frozenRoundTrip=await second.evaluate(()=>JSON.stringify(SCENARIO.player_effects))===JSON.stringify(frozen);check(report.frozenRoundTrip,'Link re-priced assumptions');
 await page.locator('[data-player-in="haaland"]').click();check(await page.evaluate(()=>!SCENARIO.player_injuries.haaland&&!SCENARIO.player_effects.haaland),'Restore did not clear absence');
 for(const route of ['club/arsenal.html','gameweek/mw6.html','receipts.html']){
  await second.goto(base+'/'+route,{waitUntil:'networkidle'});await second.addScriptTag({path:`${modules}/axe-core/axe.min.js`});
  const audit=await second.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
  report.audits.push({viewport:1440,scope:route,violations:audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.html)})),incomplete:audit.incomplete.map(v=>v.id)});
 }
 const hostile=arg('--hostile',null);
 if(hostile){
  await second.route('**/hostile-fixture.html',route=>route.fulfill({contentType:'text/html',body:readFileSync(hostile,'utf8')}));
  await second.goto(base+'/hostile-fixture.html',{waitUntil:'networkidle'});await second.locator('#tabbtn-table').click();await second.locator('#squadClub').selectOption('MCI');
  report.xss=await second.evaluate(()=>({executed:!!window.__pwned,injected:document.querySelectorAll('img[src="x"]').length,polluted:Object.prototype.polluted!==undefined}));
  check(!report.xss.executed&&!report.xss.injected&&!report.xss.polluted,'Player/source markup executed');
 }
 check(!report.errors.length,'Runtime JS errors');check(!report.outside.length,'Unexpected external request');
 const failures=report.audits.flatMap(a=>a.violations);report.ok=!failures.length;
 writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));process.exitCode=report.ok?0:1;
}finally{await browser.close()}
