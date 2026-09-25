// Local review session. Only a successful durable response changes position/state.
let data, reviewer = '', index = 0, busy = false, editing = false, baseline = '', draft = '', complete = false;
const el = id => document.getElementById(id);
const text = (tag, value, parent) => {const x = document.createElement(tag); x.textContent = value; parent.append(x); return x;};
async function api(path, body) {
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json','X-CRABS-Review':'1'}, body:JSON.stringify(body)} : {});
  const x = await r.json(); if (!r.ok) throw Error(x.error || 'Could not save decision'); return x;
}
function message(value, error = false) {el('message').textContent = value; el('message').className = error ? 'error' : '';}
function dirty() {return editing && el('edit').value !== baseline;}
function canLeave() {return !busy && (!dirty() || window.confirm('Discard unsaved edits?'));}
function label(f) {return f.review.status === 'approved' ? (f.review.final !== f.replacement ? 'Edited + approved' : 'Approved') : ({rejected:'Rejected', deferred:'Deferred', awaiting_review:'Awaiting review'}[f.review.status]);}
function button(label, action, parent, disabled = false) {const b = text('button', label, parent); b.disabled = disabled; b.onclick = action; return b;}
function diff(parent, parts, side) {const p = text('pre', '', parent); for (const part of parts) {if (part[side]) text(part[0] === 'equal' ? 'span' : side === 1 ? 'del' : 'ins', part[side], p);}}
function navigate(next) {if (!canLeave()) return; editing = false; complete = false; index = next; render();}
function render() {
  if (editing && el('edit')) draft=el('edit').value;
  el('queue').replaceChildren(); el('session').hidden = !reviewer; el('start').hidden = !!reviewer;
  if (!data) return;
  const reviewed = data.findings.filter(f => f.review.id).length;
  el('progress').textContent = `${reviewed} / ${data.findings.length} reviewed · ${reviewer}`;
  if (!reviewer) return;
  if (complete || !data.findings.length) {
    text('h2', 'Review complete', el('queue'));
    for (const name of ['Approved','Edited + approved','Rejected','Deferred']) text('p', `${name}: ${data.findings.filter(f => label(f) === name).length}`, el('queue'));
    text('p', `Total decisions successfully saved: ${reviewed} (latest saved decision per proposal)`, el('queue'));
    if (data.findings.length) button('Revisit proposals', () => navigate(0), el('queue'));
    return;
  }
  const f = data.findings[index], a = text('article', '', el('queue'));
  text('h2', `Proposal ${index + 1} / ${data.findings.length} · ${f.severity} · ${f.category}`, a);
  text('p', f.review.id ? `${label(f)} · ${f.review.reviewer} · saved · ${f.review.created}` : 'Awaiting review', a);
  text('p', `GUID ${f.guid} | ${f.field} | ${f.specialty} / ${f.subspecialty} | Confidence: ${f.confidence}`, a);
  text('p', f.rationale, a); text('p', `Evidence: ${f.evidence_status} | ${f.audit_version} | ${f.audit_date}`, a);
  for (const e of f.evidence) {const p = text('p', `${e.title} — ${e.organization_authors}, ${e.publication}, ${e.year}. ${e.locator || ''} `, a); const link = text('a','Source',p); link.href=e.url; link.target='_blank'; link.rel='noreferrer noopener';}
  text('p', 'Changes: deletions are red and struck through; additions are green and underlined. HTML is shown as text.', a);
  text('h3','Original field (exact)',a); diff(a, f.diff, 1);
  text('h3', f.review.status === 'approved' ? 'Proposed · saved approved version' : 'Proposed · automated proposal',a);
  if (editing) {const edit = text('textarea','',a); edit.id='edit'; edit.value=draft; edit.setAttribute('aria-label', 'Proposed replacement'); edit.disabled=busy;}
  else diff(a, f.diff, 2);
  const source = text('details','',a); text('summary','Original automated proposal and full source note',source); text('pre',f.replacement ?? '(No replacement; research required)',source); text('pre',JSON.stringify(f.note,null,2),source);
  const locked = busy || !reviewer.trim(), research = f.evidence_status === 'needs_research';
  if (editing) {button('Save & Approve',()=>decide('approved',true),a,locked); button('Cancel',()=>{if(canLeave()){editing=false;render();}},a,busy);}
  else {button('Approve (A)',()=>decide('approved'),a,locked || research);button('Reject (R)',()=>decide('rejected'),a,locked);button('Defer (D)',()=>decide('deferred'),a,locked);button('Edit + Approve (E)',editProposal,a,locked || research);}
  if (research) text('p','Research required: this proposal can be rejected or deferred.',a);
  const nav=text('nav','',a); button('Previous',()=>navigate(index-1),nav,busy || index===0); button('Next',()=>navigate(index+1),nav,busy || index===data.findings.length-1);
  if (reviewed === data.findings.length) button('Completion summary',()=>{if(canLeave()){editing=false;complete=true;render();}},nav,busy);
  const history=text('details','',a);text('summary','Review history',history);text('pre',JSON.stringify(f.history,null,2),history);
}
function editProposal() {if (!reviewer.trim() || busy || editing || data.findings[index].evidence_status === 'needs_research') return; baseline=data.findings[index].review.final ?? data.findings[index].replacement ?? ''; draft=baseline;editing=true;render();el('edit').focus();}
async function decide(status, edited = false) {
  if (!reviewer.trim() || busy || (editing && !edited)) return;
  const f=data.findings[index]; if (status==='approved' && f.evidence_status==='needs_research') return;
  const final=status==='approved' ? (edited ? el('edit').value : f.replacement) : null;
  // Preserve the draft while disabling controls, including on a failed request.
  busy=true; render(); message('Saving…');
  try {
    const result=await api('/api/review',{id:f.id,status,reviewer,final,expected_review_id:f.review.id});
    if (!result.saved || !result.finding) throw Error('Save was not confirmed. Refresh to check the saved state before retrying.');
    data.findings[index]=result.finding;
    el('patch').hidden=true;
    message(`${label(result.finding)} · ${result.finding.review.reviewer} · saved`);
    editing=false;
    const next=data.findings.findIndex((item,i)=>i>index && !item.review.id);
    const first=data.findings.findIndex(item=>!item.review.id);
    if (next>=0) index=next; else if(first>=0) index=first; else complete=true;
  } catch(e) {message(e.message,true);} finally {busy=false;render();}
}
async function load() {
  if (!canLeave()) return;
  try {const fresh=await api('/api/state'); data=fresh; editing=false;complete=false;index=Math.min(index,Math.max(0,data.findings.length-1));
    el('context').textContent=`Batch: ${data.batch.version} · ${data.batch.id.slice(0,12)} · ${data.findings.length} proposals · Audits: ${[...new Set(data.findings.map(f=>f.audit_version))].join(', ')}`;
    el('coverage').textContent=JSON.stringify({...data.coverage,notes:undefined},null,2);el('audits').textContent=JSON.stringify(data.audits,null,2);el('start-review').disabled=!el('reviewer').value.trim();render();
  } catch(e) {message(e.message,true);}
}
function startReview() {if (!data || !el('reviewer').value.trim()) return;reviewer=el('reviewer').value.trim();try{localStorage.setItem('crabs-reviewer',reviewer);}catch(e){} index=Math.max(0,data.findings.findIndex(f=>!f.review.id));render();}
window.addEventListener('beforeunload',e=>{if(busy || dirty()){e.preventDefault();e.returnValue='';}});
document.addEventListener('keydown',e=>{if(e.repeat || e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT|BUTTON/.test(e.target.tagName) || e.target.isContentEditable || editing || !reviewer || busy || complete) return;const action={a:()=>decide('approved'),r:()=>decide('rejected'),d:()=>decide('deferred'),e:editProposal}[e.key.toLowerCase()];if(action){e.preventDefault();action();}});
try {el('reviewer').value=localStorage.getItem('crabs-reviewer') || '';} catch(e) {}
el('reviewer').oninput=()=>{el('start-review').disabled=!data || !el('reviewer').value.trim();};
el('start-review').onclick=startReview;el('refresh').onclick=load;
load();

el('preview').onclick=async()=>{try{const result=await api('/api/preview');el('patch').textContent=result.preview;el('patch').hidden=false;}catch(e){message(e.message,true);}};
