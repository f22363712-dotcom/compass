const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:id==='project-path-input'?'C:/demo': '',hidden:true,
 classList:{toggle(){},add(){},remove(){}},addEventListener(){},setAttribute(){},append(){},prepend(){},
 querySelector(){return element(id+'-child');},querySelectorAll(){return [];}});return elements.get(id);}
const state={state_version:1,project:{project_id:'demo',name:'Demo',evidence_count:0,fact_count:0},personal:{},team:{facts:[],evidence_ids:[]},evidence:[],candidate_relations:[],confirmed_relations:[],review_history:[],fact_reviews:[],intake:{enabled:false}};
let statusCalls=0;
const context=vm.createContext({console,AbortController,setTimeout(callback){callback();return 1;},clearTimeout,setInterval(){},document:{hidden:false,getElementById:element,querySelectorAll:()=>[],createElement:()=>element('created')},fetch:async(path,options)=>{
  if(path==='/api/state') return {ok:true,json:async()=>state};
  if(path==='/api/projects/scan') return {ok:true,json:async()=>({state:'running'})};
  if(path==='/api/projects/scan-status'){statusCalls+=1;return {ok:true,json:async()=>({state:'pending'})};}
  throw new Error(`unexpected fetch ${path}`);
}});
async function main(){vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);await new Promise(r=>setImmediate(r));
  await vm.runInContext('(async()=>{await scanNewProject({preventDefault(){}})})()',context);
  assert.equal(element('project-scan-result').textContent,'扫描仍在进行，可稍后刷新页面查看状态。');
  assert.equal(statusCalls,100);
  console.log('Project scan timeout keeps an explicit pending status after the polling window.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
