/** Dev-only career/challenge proof. Setup: bash tools/setup_browser_tools.sh.
 * NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/wave16.mjs [--url https://90plus-cyan.vercel.app]
 */
import {writeFileSync} from 'node:fs';
const mods=process.env.NT90_PLAYWRIGHT_MODULES||'/tmp/a11y/node_modules';
const {chromium}=await import(`${mods}/playwright/index.mjs`);
const args=process.argv.slice(2),arg=(key,def)=>{const i=args.indexOf(key);return i<0?def:args[i+1]};
const base=arg('--url','http://127.0.0.1:8000').replace(/\/$/,''),out=arg('--out','/tmp/wave16.json');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const report={url:base,errors:[],outside:[],widths:[],audits:[],checks:{}};
function check(ok,message){if(!ok)throw new Error(message)}
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(base+'/')&&!r.url().startsWith('data:')&&!r.url().startsWith('blob:'))report.outside.push(r.url())});
 await page.goto(base+'/',{waitUntil:'networkidle'});check(await page.locator('#hubCareer').isVisible(),'No obvious homepage game entry');
 await page.locator('#hubClub').selectOption('ARS');await page.locator('#hubCareer').click();await page.waitForLoadState('networkidle');
 check(await page.locator('[data-club]').count()===20,'Not all clubs selectable');
 await page.locator('#worldSeed').fill('42');
 async function audit(scope){await page.addScriptTag({path:`${mods}/axe-core/axe.min.js`});const result=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));report.audits.push({scope,violations:result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.html)})),incomplete:result.incomplete.map(v=>v.id)});}
 for(const v of [{width:1440,height:1000},{width:390,height:844}]){await page.setViewportSize(v);const width=await page.evaluate(()=>({document:document.documentElement.scrollWidth,screen:innerWidth}));report.widths.push({scope:'setup',...width});check(width.document<=width.screen,'Setup overflow');await audit('setup '+v.width);}
 await page.locator('#startCareer').click();check((await page.evaluate(()=>NT90_PLAY.summary())).played===0,'Career did not start');
 await page.locator('[data-tactic="pressing"]').click();await page.locator('[data-training="attack"]').click();await page.locator('[data-rest="raya"]').check();
 await page.locator('#marketSearch').fill('haaland');await page.locator('[data-transfer="haaland"]').click();
 check(await page.evaluate(()=>NT90_GAME.clubOf(NT90_PLAY.getCareer(),NT90_PLAY.getCareer().base.players.find(p=>p.id==='haaland')))==='ARS','Signing did not move the game player');
 await page.locator('#playRound').click();await page.waitForFunction(()=>!NT90_PLAY.isBusy());
 const saved=await page.evaluate(()=>JSON.stringify(NT90_PLAY.getCareer()));report.checks.playedRound=true;
 await page.reload({waitUntil:'networkidle'});await page.locator('[data-resume]').first().click();
 report.checks.frozenResume=await page.evaluate(()=>JSON.stringify(NT90_PLAY.getCareer()))===saved;check(report.checks.frozenResume,'Reload rerolled or lost career');
 for(const v of [{width:1440,height:1000},{width:390,height:844}]){await page.setViewportSize(v);const width=await page.evaluate(()=>({document:document.documentElement.scrollWidth,screen:innerWidth}));report.widths.push({scope:'career',...width});check(width.document<=width.screen,'Career overflow');await audit('career '+v.width);}
 const backup=await page.evaluate(()=>({kind:'ninety-plus-career',version:1,state:NT90_GAME.clone(NT90_PLAY.getCareer())}));
 backup.state.credits=999999;backup.state.table[0].pts=99999;
 await page.locator('#careerHome').click();await page.locator('#importCareer').setInputFiles({name:'career.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(backup))});
 await page.waitForFunction(()=>document.getElementById('careerActive').hidden===false);
 report.checks.recomputedImport=await page.evaluate(()=>NT90_PLAY.getCareer().credits<200&&NT90_PLAY.getCareer().table.every(t=>t.pts<120));check(report.checks.recomputedImport,'Imported invented totals trusted');
 // Full season is reachable through the actual fast-forward control.
 while(!(await page.evaluate(()=>NT90_PLAY.summary().done))){await page.locator('#fastForward').click();}
 report.checks.finished=await page.locator('#seasonReport').isVisible();check(report.checks.finished,'No full-season report');
 await page.locator('#challengeTab').click();for(const button of await page.locator('[data-outcome="H"]').all())await button.click();
 await page.locator('#practiceRound').click();check((await page.locator('#challengeFeedback').innerText()).includes('PRACTICE ONLY'),'Practice not labelled');
 const before=await page.evaluate(()=>NT90_STORE.get('predictionChallenges',[]).length);check(before===0,'Practice wrote real score records');
 await page.locator('#lockPicks').click();check(await page.locator('#lockPicks').isDisabled(),'Locked picks can be overwritten');
 check((await page.locator('#challengeHistory').innerText()).includes('0 actually played, 10 pending'),'Missing results awarded real points');report.checks.practiceSeparate=true;
 const immutable=await page.evaluate(()=>JSON.stringify(NT90_STORE.get('predictionChallenges',[])));
 await page.locator('#challengeNew').click();await page.locator('[data-outcome="A"]').first().click();
 report.checks.lockPreserved=await page.evaluate(()=>JSON.stringify(NT90_STORE.get('predictionChallenges',[])))===immutable;check(report.checks.lockPreserved,'Practice reset changed real locked picks');
 for(const v of [{width:1440,height:1000},{width:390,height:844}]){await page.setViewportSize(v);const width=await page.evaluate(()=>({document:document.documentElement.scrollWidth,screen:innerWidth}));report.widths.push({scope:'challenge',...width});check(width.document<=width.screen,'Challenge overflow');await audit('challenge '+v.width);}
 // A poisoned backup goes through validation and escaped rendering, never script execution.
 await page.locator('#careerTab').click();await page.locator('#careerHome').click();const poisoned=structuredClone(backup);poisoned.state.base.players.find(p=>p.id==='haaland').name='<img src=x onerror="window.__pwned=1">';
 await page.locator('#importCareer').setInputFiles({name:'poison.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(poisoned))});await page.waitForFunction(()=>!document.getElementById('careerActive').hidden);
 report.checks.xss=await page.evaluate(()=>({executed:!!window.__pwned,nodes:document.querySelectorAll('img[src="x"]').length,polluted:Object.prototype.polluted!==undefined}));check(!report.checks.xss.executed&&!report.checks.xss.nodes&&!report.checks.xss.polluted,'Imported name injected markup');
 await page.locator('#careerHome').click();const broken=structuredClone(backup);broken.state.journal[0].transfers.push({pid:'palmer',release:false});
 await page.locator('#importCareer').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(broken))});check(await page.locator('#gameError').isVisible(),'Invalid journal accepted');report.checks.invalidSaveHeld=true;
 check(!report.errors.length,'Runtime errors');check(!report.outside.length,'External requests');
 report.ok=report.audits.every(a=>!a.violations.length);writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));process.exitCode=report.ok?0:1;
}finally{await browser.close()}
