/** Dev-only proof for the played matchday (v2 game): kickoff → half time → second half → inbox.
 * Setup: bash tools/setup_browser_tools.sh
 * NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/wave17.mjs [--url https://90plus-cyan.vercel.app]
 */
import {writeFileSync} from 'node:fs';
const mods=process.env.NT90_PLAYWRIGHT_MODULES||'/tmp/a11y/node_modules';
const {chromium}=await import(`${mods}/playwright/index.mjs`);
const args=process.argv.slice(2),arg=(key,def)=>{const i=args.indexOf(key);return i<0?def:args[i+1]};
const base=arg('--url','http://127.0.0.1:8000').replace(/\/$/,''),out=arg('--out','/tmp/wave17.json');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const report={url:base,errors:[],outside:[],widths:[],audits:[],checks:{}};
const check=(ok,message)=>{if(!ok)throw new Error(message)};
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});
 const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 page.on('request',r=>{if(!r.url().startsWith(base+'/')&&!r.url().startsWith('data:')&&!r.url().startsWith('blob:'))report.outside.push(r.url())});
 await page.goto(base+'/play.html?seed=42&club=ARS',{waitUntil:'networkidle'});
 await page.locator('#startCareer').click();
 // A real ticking first half: the clock must advance before half time appears.
 await page.locator('#kickOff').click();
 await page.waitForFunction(()=>{const s=NT90_PLAY.getSession();return s&&s.minute>3},null,{timeout:20000});
 report.checks.ticking=true;
 await page.waitForSelector('#halfTimePanel:not([hidden])',{timeout:20000});
 report.checks.firstHalfClock=await page.locator('#liveClock').innerText();
 const halfScore=await page.locator('#liveScore').innerText();
 report.checks.halfTimeScore=halfScore;
 check(/half time/i.test(await page.locator('#stageTag').innerText()),'Half time did not stop the match');
 // The session must lock the season controls while it is live.
 check(await page.locator('#playRound').isDisabled(),'Skip was available during a live match');
 check(await page.locator('#fastForward').isDisabled(),'Fast-forward was available during a live match');
 const lockedBefore=await page.evaluate(()=>document.querySelector('#tactics button').disabled===false);
 check(!lockedBefore,'Tactics could be changed mid-match');
 await page.locator('[data-instruction="push"]').click();
 await page.locator('[data-sub="saka"]').check();
 report.checks.subs=await page.locator('#subsCount').innerText();
 check(report.checks.subs.startsWith('1 / 2'),'Substitution counter is wrong');
 await page.locator('#secondHalf').click();
 await page.waitForFunction(()=>NT90_PLAY.getSession().stage==='full',null,{timeout:20000});
 const summary=await page.locator('#fullTimeSummary').innerText();
 report.checks.fullTimeReport=summary.replace(/\s+/g,' ').slice(0,220);
 check(/FULL TIME/.test(summary)&&/what it did/i.test(summary),'No decision report at full time');
 check(/Without any half-time change/.test(summary),'No honest comparison with the no-decision path');
 check(!/\[object Object\]/.test(summary),'Raw object leaked into the full-time report');
 await page.locator('#continueAfterMatch').click();
 await page.waitForFunction(()=>!NT90_PLAY.isBusy());
 report.checks.inbox=await page.evaluate(()=>NT90_PLAY.getInbox());
 check(report.checks.inbox.length>0,'No inbox decisions after a match');
 const effect=await page.evaluate(()=>{const item=NT90_PLAY.getInbox()[0];return NT90_PLAY.chooseInbox(item,document.querySelector('[data-inbox="'+item+'"]').dataset.choice)});
 report.checks.effect=effect;
 report.checks.afterReply=await page.evaluate(()=>NT90_PLAY.getInbox());
 check(report.checks.afterReply.length===report.checks.inbox.length-1,'The reply did not clear its item');
 const replayA=await page.evaluate(()=>JSON.stringify(NT90_PLAY.getCareer()));
 await page.reload({waitUntil:'networkidle'});await page.locator('[data-resume]').first().click();
 report.checks.frozenResume=await page.evaluate(()=>JSON.stringify(NT90_PLAY.getCareer()))===replayA;
 check(report.checks.frozenResume,'Reload changed a decided match');
 // Second matchday, skipped at both breaks, with reduced motion: same decision points, no ticking.
 const reducedPage=await context.newPage();await reducedPage.emulateMedia({reducedMotion:'reduce'});
 reducedPage.on('pageerror',e=>report.errors.push(e.message));
 await reducedPage.goto(base+'/play.html?seed=7&club=LIV',{waitUntil:'networkidle'});
 await reducedPage.locator('#startCareer').click();await reducedPage.locator('#kickOff').click();
 await reducedPage.waitForSelector('#halfTimePanel:not([hidden])',{timeout:15000});
 report.checks.reducedMotionHalfTime=true;
 await reducedPage.locator('[data-instruction="hold"]').click();
 await reducedPage.locator('#secondHalf').click();
 await reducedPage.waitForFunction(()=>NT90_PLAY.getSession().stage==='full',null,{timeout:15000});
 await reducedPage.locator('#continueAfterMatch').click();
 // Skip-match path still works for people who want the fast route.
 await reducedPage.locator('#playRound').click();
 check((await reducedPage.evaluate(()=>NT90_PLAY.summary().played))===2,'Skip-match path did not advance the season');
 check((await reducedPage.evaluate(()=>NT90_PLAY.getInbox())).length>0,'No inbox after the skip path');
 await reducedPage.close();
 for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
  await page.setViewportSize(viewport);
  const width=await page.evaluate(()=>({document:document.documentElement.scrollWidth,screen:innerWidth}));
  report.widths.push({viewport:viewport.width,...width});
  check(width.document<=width.screen+1,'Horizontal overflow at '+viewport.width);
 }
 // Mid-match capture, then axe on the live stage panel.
 await page.locator('#kickOff').click();await page.waitForSelector('#halfTimePanel:not([hidden])',{timeout:20000});
 await page.addScriptTag({path:`${mods}/axe-core/axe.min.js`});
 for(const target of ['matchStage','inboxList']){
  const result=await page.evaluate(id=>axe.run(document.getElementById(id),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}),target);
  report.audits.push({target,violations:result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.html)})),incomplete:result.incomplete.map(v=>v.id)});
 }
 check(!report.errors.length,'Runtime JS errors');check(!report.outside.length,'Unexpected external request');
 report.ok=report.audits.every(a=>!a.violations.length);
 writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));process.exitCode=report.ok?0:1;
}finally{await browser.close()}
