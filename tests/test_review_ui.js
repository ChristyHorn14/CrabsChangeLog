// Execute the actual browser controller with a minimal DOM and controlled HTTP promises.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
function harness(){
 const nodes=new Map();
 class Element {constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.value='';}set id(v){this._id=v;nodes.set(v,this);}get id(){return this._id;}append(x){this.children.push(x);}replaceChildren(){nodes.delete('edit');this.children=[];}setAttribute(){}focus(){}}
 for(const id of ['queue','session','start','progress','message','context','coverage','audits','start-review','reviewer','refresh','preview','patch']){const e=new Element('div');e.id=id;}
 const findings=Array.from({length:3},(_,i)=>({id:String(i),review:{id:0,status:'awaiting_review',final:null},original:'old',replacement:'new',diff:[['replace','old','new']],evidence:[],history:[]}));
 let pending, calls=[];let confirm=true;
 const ctx=vm.createContext({document:{getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),addEventListener(){}},window:{addEventListener(){},confirm:()=>confirm},localStorage:{getItem:()=>'',setItem(){}},fetch:async(path,opts)=>{if(!opts.body)return {ok:true,json:async()=>({findings,batch:{id:'abcdef',version:'test'},coverage:{},audits:[]})};calls.push(JSON.parse(opts.body));return new Promise(resolve=>pending=resolve);}});
 vm.runInContext(source,ctx);return {nodes,calls,run:s=>vm.runInContext(s,ctx),settle:async()=>{await new Promise(r=>setImmediate(r));},reply(ok=true){const body=calls.at(-1);pending({ok,json:async()=>ok?{saved:true,finding:{...findings[Number(body.id)],review:{...body,id:42,created:'today'},history:[]}}:{error:'disk failure'}});},deny(){confirm=false;}};
}
(async()=>{
 for(const status of ['approved','rejected','deferred']){
  const h=harness();await h.settle();await h.run(`decide('${status}')`);assert.equal(h.calls.length,0);assert.equal(h.nodes.get('queue').children.length,0);
  h.nodes.get('reviewer').value='   ';h.run('startReview()');assert.equal(h.run('reviewer'),'');
  h.nodes.get('reviewer').value=' Chris Hornung ';h.run('startReview()');
  const saving=h.run(`decide('${status}')`);assert.equal(h.run('index'),0);assert.equal(h.run('busy'),true,h.nodes.get('message').textContent);assert.equal(h.calls[0].reviewer,'Chris Hornung');
  await h.run(`decide('${status}')`);assert.equal(h.calls.length,1);h.reply();await saving;
  assert.equal(h.run('index'),1);assert.match(h.nodes.get('message').textContent,/Chris Hornung · saved/);h.run('navigate(0)');assert.equal(h.run('data.findings[0].review.status'),status);
 }
 const h=harness();await h.settle();h.nodes.get('reviewer').value='Chris';h.run('startReview();editProposal()');h.nodes.get('edit').value='edited';h.deny();h.run('navigate(1)');assert.equal(h.run('index'),0);
 const saving=h.run("decide('approved',true)");h.reply(false);await saving;assert.equal(h.run('index'),0);assert.equal(h.nodes.get('edit').value,'edited');assert.equal(h.run('dirty()'),true);
 const retry=h.run("decide('approved',true)");assert.equal(h.calls.at(-1).final,'edited');h.reply();await retry;assert.equal(h.run('data.findings[0].replacement'),'new');assert.equal(h.run('data.findings[0].review.final'),'edited');
 h.run('navigate(2)');assert.equal(h.calls.length,2);assert.equal(h.run('data.findings[2].review.id'),0);
 for(const status of ['rejected','deferred']){const save=h.run(`decide('${status}')`);h.reply();await save;}
 assert.equal(h.run('complete'),true);assert.match(h.nodes.get('progress').textContent,/3 \/ 3 reviewed/);
 console.log('PASS: identity gate; A/R/D persist before advance; duplicate guard; failure/draft retention; edit provenance; navigation');
})().catch(e=>{console.error(e);process.exitCode=1;});
