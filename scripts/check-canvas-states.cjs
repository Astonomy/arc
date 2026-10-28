// Browser contract for scope grouping, filled statuses and their connections.
const { chromium } = require(process.argv[2]);
const { pathToFileURL } = require('node:url');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
    page.on('pageerror', e=>errors.push(e.message));
    await page.goto(pathToFileURL(path.resolve(process.argv[3])).href);
    await page.evaluate(()=>{
      data.requirements={id:'ROOT',name:'Scope / status fixture',children:[
        {id:'REQ-UI',name:'Page',scope:'UI'}, {id:'REQ-API',name:'Endpoint',scope:'API'},
        {id:'REQ-FUNC',name:'Service',scope:'FUNC'}, {id:'REQ-DB',name:'Storage'},
        {id:'SCOPE-CUSTOM',name:'Feature',scope:'Feature A',children:[{id:'REQ-CUSTOM',name:'Custom scope'}]},
        {id:'REQ-OTHER',name:'Unscoped'}]};
      data.traceability={
        'REQ-UI':{status:'accepted',code:['src/page.tsx'],interface_scopes:{'src/page.tsx':'UI'}},
        'REQ-API':{status:'running',code:['src/api.py'],interface_scopes:{'src/api.py':'API'},test_runs:[{command:['pytest'],started_at:'now'}]},
        'REQ-FUNC':{status:'failed',code:['src/service.py'],interface_scopes:{'src/service.py':'FUNC'}},
        'REQ-CUSTOM':{status:'pending',code:['src/feature.py']},
        'REQ-OTHER':{status:'unknown',code:['src/other.py']}};
      data.tdd={'REQ-DB':{code:['src/storage.py'],tests:['tests/storage.py'],interface_scopes:{'src/storage.py':'DB'}}};
      renderCanvas();
    });
    const backgrounds=new Set();
    for(const [scope,status] of [['UI','accepted'],['API','running'],['FUNC','failed'],['DB','pending'],['Feature A','pending'],['未指定 scope','unknown']]){
      const node=page.locator(`#interface-nodes [data-scope="${scope}"] .node`);
      if(await node.count()!==1||await node.getAttribute('data-status')!==status)throw Error('Incorrect scope/status: '+scope);
      const fill=await node.evaluate(n=>getComputedStyle(n).backgroundColor);
      if(['rgb(255, 255, 255)','rgba(0, 0, 0, 0)'].includes(fill))throw Error('Missing status fill: '+status);
      backgrounds.add(fill);
    }
    if(backgrounds.size!==5)throw Error('Status fills are not distinct');
    await page.locator('#test-nodes .node.running').waitFor();
    await page.locator('.connection.artifact').first().waitFor({state:'attached'});
    await page.screenshot({path:path.join(path.dirname(path.resolve(process.argv[3])),'scope-states.png'),fullPage:true});
    await page.evaluate(()=>{data.traceability['REQ-API'].status='failed';renderCanvas()});
    await page.locator('#interface-nodes [data-scope="API"] .node.failed').waitFor();
    await page.evaluate(()=>{
      data.requirements={id:'ROOT',name:'Industrial workflow',children:[
        {id:'SCOPE-ROBOT',name:'Robot',scope:'机械控制',children:[{id:'REQ-MOTION',name:'Motion'}]},
        {id:'REQ-SENSOR',name:'Sensor'},
        {id:'REQ-PLANNED',name:'Pending equipment',scope:'设备标定'}]};
      data.traceability={'REQ-MOTION':{status:'running',code:['motion.py'],interface_scopes:{'motion.py':'Evidence-only'}},
        'REQ-SENSOR':{status:'accepted',code:['sensor.py']}};
      data.tdd={'REQ-SENSOR':{code:['sensor.py'],interface_scopes:{'sensor.py':'传感器采集'}},
        'REQ-ORPHAN':{code:['old.py'],interface_scopes:{'old.py':'Orphan'}}};
      renderCanvas();
    });
    const scopes=await page.locator('#interface-nodes [data-scope]').evaluateAll(nodes=>nodes.map(n=>n.dataset.scope));
    if(JSON.stringify(scopes)!==JSON.stringify(['机械控制','设备标定','传感器采集']))throw Error('Scopes must come only from current REQs: '+scopes);
    if(await page.locator('#interface-nodes [data-scope="设备标定"] .node').count()!==0)throw Error('Declared scope without artifacts should remain empty');
    await page.evaluate(()=>{data.requirements=null;data.tdd={};data.traceability={};renderCanvas()});
    if(await page.locator('#interface-nodes [data-scope]').count())throw Error('Empty REQ must not display preset scopes');
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
    if(errors.length)throw Error(errors.join('\n'));
    console.log(JSON.stringify({scope_grouping:'passed',dynamic_req_scopes:'passed',filled_statuses:'passed',runtime_transition:'passed',page_errors:errors}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
