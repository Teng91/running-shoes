// SPEC-026: real DOM interleavings with synthetic HTTP data in both engines.
const assert = require('node:assert/strict');
const { closeBrowser, saveFailure, startArtifacts, withDeadline } = require('../scripts/browser_artifacts.cjs');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

async function inspect(browser,baseUrl,scenario){
 const context=await browser.newContext({serviceWorkers:'block'}); await startArtifacts(context);
 await context.addInitScript(()=>{localStorage.setItem('token','synthetic-audit');localStorage.setItem('username','synthetic-audit');});
 const gate=deferred(),started=deferred();let holdGoal=false,removeShoe=false,holdAnnual=false,annualCalls=0;
 const writes=[],errors=[];
 const shoe={id:1,version:0,brand:'Test',model:'Pair A',nickname:'',date:'2026-01-01',size:'',price:1000,orig_price:2000,mileage:50,expected_mileage:800,monthly_km:60,is_retired:false,categories:['Daily'],discount_percent:50,cost_per_km:20,expected_cost_per_km:1.25,usage_percent:6.25,remaining_mileage_km:750};
 const other={...shoe,id:2,model:'Pair B',date:'2026-02-01'};
 await context.route('**/api/**',async route=>{
  const request=route.request(),name=new URL(request.url()).pathname;let body=[];
  if(request.method()==='DELETE'&&name==='/api/shoes/1'){removeShoe=true;body={ok:true};}
  else if(request.method()==='PUT'){writes.push({name,payload:request.postDataJSON()});body={...shoe,...request.postDataJSON(),version:1};}
  else if(name==='/api/runs'&&request.method()==='POST'){writes.push({name,payload:request.postDataJSON()});body={id:1,version:0,...request.postDataJSON()};}
  else if(name==='/api/runs/import/strava/preview'){body={run_count:1,importable_count:1,importable_km:5,duplicate_count:0,gear_groups:[{gear:'Synthetic Shoe',suggested_shoe_id:1,count:1,km:5}]};}
  else if(name==='/api/runs/import/strava'&&request.method()==='POST'){writes.push({name,raw:request.postDataBuffer().toString()});started.resolve();await gate.promise;if(scenario==='mapping-error') return route.fulfill({status:500,json:{detail:'Synthetic import failure'}});body={imported:1,skipped_unmapped:0,synced_mileage:5};}
  else if(request.method()!=='GET')throw Error('Unexpected mutation '+name);
  else if(name==='/api/auth/me')body={username:'synthetic-audit'};
  else if(name==='/api/shoes/active')body=removeShoe?[other]:[shoe,other];
  else if(name==='/api/monthly-mileage')body=[{id:1,year:2026,month:10,km:100,adjustment_km:100,version:0}];
  else if(name==='/api/running-goal'){if(holdGoal){started.resolve();await gate.promise;}body={version:0,start_year:2026,monthly_km:125,yearly_km:1500};}
  else if(name==='/api/running-goal/year')body={year:Number(new URL(request.url()).searchParams.get('year')),active:false,start_year:2026,months:[]};
  else if(name==='/api/runs/summary')body={total_km:0,run_count:0,run_days:0,calendar:[],shoe_usage:[]};
  else if(name==='/api/runs/year-summary'){annualCalls++;if(holdAnnual){started.resolve();await gate.promise;}body={year:2026,total_km:0,monthly_km:Array(12).fill(0),shoes:[]};}
  else if(name==='/api/analytics/dashboard')body={};
  await route.fulfill({json:body});
 });
 const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept());
 try{
  await page.clock.setFixedTime(new Date('2026-10-23T12:00:00Z'));
  await page.goto(baseUrl,{waitUntil:'networkidle'});await page.locator('#app-boot').waitFor({state:'hidden'});
  if(scenario.startsWith('inline-')){
   await page.evaluate(()=>switchTab('shoes'));
   holdGoal=true;await page.evaluate(()=>{window.__auditLoad=loadData();});await started.promise;
   await page.waitForFunction(()=>activeHttpRequests.size===1);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      // Match the mileage cell by its inline edit target, independent of numeric sibling cells.
   const target=page.locator('#shoe-table td[data-dblclick="inline-edit"][data-field="mileage"]').first();
   await target.dblclick();await page.locator('.inline-input').fill('1');
   assert.equal(await page.locator('.inline-input').inputValue(),'1');
   assert.equal(await page.locator('.inline-input').evaluate(node=>document.activeElement===node),true);
   holdGoal=false;gate.resolve();await page.evaluate(()=>window.__auditLoad);await page.waitForFunction(()=>activeHttpRequests.size===0);
   const count=await page.locator('.inline-input').count();
   assert.equal(count,1); assert.deepEqual(writes,[]);
   await page.evaluate(()=>toggleTheme());
   assert.equal(await page.locator('.inline-input').inputValue(),'1');
   // Also refresh the edited resource itself: the table must keep its live input.
   await page.evaluate(()=>loadData());
   assert.equal(await page.locator('.inline-input').inputValue(),'1'); assert.deepEqual(writes,[]);
   await page.locator('.inline-input').fill('180'); await page.locator('.inline-input').press('Enter');
   await page.waitForFunction(()=>!document.querySelector('.inline-input'));
   assert.equal(writes.length,1); assert.equal(writes[0].payload.expected_version,0);
   assert.equal(writes[0].payload.mileage,180);
   console.log('PASS',browser.browserType().name(),'SPEC-026',scenario,'retains DOM until explicit commit');
  }else if(scenario==='new-run-shoe'){
   await page.locator('#run-date').fill('2026-10-01');await page.locator('#run-km').fill('5');await page.locator('#run-shoe').selectOption('1');
   await page.evaluate(()=>switchTab('shoes'));
   await page.locator('#shoe-table tr:first-child .btn-edit').click();
   await page.locator('#btn-delete').click();await page.locator('#modal').waitFor({state:'hidden'});
   await page.waitForFunction(()=>shoes.length===1);await page.evaluate(()=>switchTab('runs'));
   // Panel rendering runs in the next frame. Wait for its DOM transition,
   // then assert that a removed option did not silently choose its successor.
   await page.waitForFunction(()=>!document.querySelector('#run-shoe option[value="1"]'));
   assert.equal(await page.locator('#run-shoe').inputValue(),'');
   await page.evaluate(()=>render());
   assert.equal(await page.locator('#run-shoe').inputValue(),'');
   await page.locator('#add-run-btn').click(); assert.deepEqual(writes,[]);
   await page.locator('#run-shoe').selectOption('2');
   await page.locator('#add-run-btn').click();await page.waitForFunction(()=>!runController.saving);
   assert.equal(writes[0].payload.shoe_id,2);
   console.log('PASS',browser.browserType().name(),'SPEC-026 removed shoe requires explicit replacement');
  }else if(scenario.startsWith('mapping')){
   await page.getByRole('button',{name:/匯入 Strava/}).click();
   await page.locator('#strava-file').setInputFiles({name:'audit.csv',mimeType:'text/csv',buffer:Buffer.from('synthetic')});
   await page.waitForFunction(()=>stravaController.state.preview&&!document.getElementById('strava-import-btn').disabled);
   await page.locator('#strava-import-btn').click();await started.promise;
   assert.equal(await page.locator('#strava-map-0').isDisabled(),true);
   gate.resolve();
   if(scenario==='mapping-error') {
    await page.waitForFunction(()=>!stravaController.importing());
    assert.equal(await page.locator('#strava-map-0').isEnabled(),true);
    assert.equal(await page.locator('#strava-map-0').inputValue(),'1');
   } else await page.locator('#strava-modal').waitFor({state:'hidden'});
   assert.ok(writes[0].raw.includes('{"Synthetic Shoe":1}'));
   console.log('PASS',browser.browserType().name(),'SPEC-026',scenario,'locks submitted mapping');
  }else if(scenario==='annual-requests'){
   holdAnnual=true;await page.evaluate(()=>switchTab('monthly'));await started.promise;
   await page.evaluate(()=>loadData());
   assert.equal(annualCalls,2,'one new read after run-resource invalidation');
   await page.evaluate(()=>{for(let i=0;i<5;i++)render();});
   assert.equal(annualCalls,2,'redraws share the pending annual read');
   gate.resolve(); await page.waitForFunction(()=>activeHttpRequests.size===0);
   console.log('PASS',browser.browserType().name(),'SPEC-026 annual reads coalesced across redraws');
  }
  assert.deepEqual(errors,[]);
 }catch(error){await saveFailure(context,page,'resource-editing-'+scenario+'-'+browser.browserType().name(),error);throw error;}
 finally{gate.resolve();await closeBrowser(context);}
}
module.exports = async function checkResourceEditing(browser, baseUrl) {
  for (const scenario of ['inline-shoe', 'new-run-shoe', 'mapping', 'mapping-error', 'annual-requests']) {
    await withDeadline(() => inspect(browser, baseUrl, scenario), 25000, 'SPEC-026 ' + scenario);
  }
};
