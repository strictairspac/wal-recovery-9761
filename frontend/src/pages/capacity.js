import {capacityAPI} from '../api/entities.js';
import {session} from '../stores/session.js';
import {table} from '../components/common/table.js';
import {esc,formObject} from '../utils/html.js';
import {action,message} from '../hooks/action.js';
import {downloadCapacity} from '../api/client.js';
import {REQUEST_STATUSES,DRILL_RUN_STATUSES} from '../constants/enums.js';

const writable=()=>session.role!=='viewer';
const pct=(used,reserved,cap)=>Math.min(100,Math.round(((used+reserved)/cap)*100));

export function capacityPage(list,detail){
 const d=detail?.drill;
 return `<div class="section-title"><h2>日志盘容量演练</h2><span>申报预留 · 有界插队 · 静止检查点 · 崩溃续办</span></div>
 ${table(['演练','容量(字节)','短单阈值(字节)','已用/预留','状态','核对'],(list||[]).map(x=>[
   esc(x.name),x.capacity_bytes,x.short_threshold_bytes,
   `${x.used_bytes} / ${x.reserved_bytes}`,
   `<span class="badge ${esc(x.status)}">${esc(DRILL_RUN_STATUSES[x.status]||x.status)}</span>`,
   `<a href="#capacity/${x.id}">进入演练 →</a>`]))}
 ${writable()?`<section class="split"><div><h2>设置一块可写满的日志盘</h2>
 <p>受理申请时按“申报写入上限 + 开工/结束两条记录帧”预留空间，保证开工后即使写满申报额度，也一定能提交或撤销。放不下的并发申请进入持久队列。</p>
 <p class="big-note">写满不拦收尾，只拦新申请。</p></div>
 <form id="drill-form">
 <label>演练名称<input name="name" value="日志盘容量-演练1" required></label>
 <label>初始账本 JSON<textarea name="initial" rows="2" required>{"sample_A":100,"sample_B":50}</textarea></label>
 <label>日志容量（字节）<input name="capacity_bytes" type="number" min="129" value="2000" required></label>
 <label>短单阈值（字节，留空取容量1/10）<input name="short_threshold_bytes" type="number" min="1" placeholder="200"></label>
 <label>说明<input name="description" value="容量受理与崩溃续办演练"></label>
 <button type="submit">建立容量演练</button></form></section>`
 :'<p class="readonly">观察员仅查看容量与排队，新增与操作需要操作员或管理员。</p>'}
 ${d?drillPanel(detail):'<section class="empty"><h2>选择一个演练进入</h2><p>或新建一块日志盘开始容量受理演练。</p></section>'}`;
}

function drillPanel(detail){
 const d=detail.drill;const ratio=pct(d.used_bytes,d.reserved_bytes,d.capacity_bytes);
 const active=detail.requests.filter(r=>r.status==='active');
 const queued=detail.requests.filter(r=>r.status==='queued');
 return `<section class="capacity-board">
 <div class="cap-head"><h2>${esc(d.name)}</h2><span class="badge ${esc(d.status)}">${esc(DRILL_RUN_STATUSES[d.status]||d.status)}</span></div>
 <div class="cap-meter"><div class="cap-fill" style="width:${ratio}%"></div></div>
 <p class="cap-nums">容量 ${d.capacity_bytes} 字节 · 已用 ${d.used_bytes} · 预留 ${d.reserved_bytes} ·
 可用 <b>${detail.available_bytes}</b> · 已回收 ${d.reclaimed_bytes} · 检查点LSN ${d.checkpoint_lsn||0}</p>
 <div class="cap-grid">
 <div class="cap-card"><h3>当前账本</h3><pre>${esc(JSON.stringify(d.ledger,null,2))}</pre></div>
 <div class="cap-card"><h3>排队核对（剩余 ${detail.queue_remaining} 条）</h3>
 ${queued.length?table(['序号','申请','申报(字节)','被插队次数','排队原因'],queued.map(r=>[r.seq,esc(r.code),r.declared_bytes,r.skip_count,esc(r.queue_reason||'—')]))
   :'<p class="readonly">队列已清空，新申请可直接受理。</p>'}</div>
 </div>
 ${writable()?`<form id="req-form" class="inline-form">
 <label>申请标识<input name="code" placeholder="TX4" required></label>
 <label>申报写入上限（字节）<input name="declared_bytes" type="number" min="1" value="120" required></label>
 <button type="submit">提交并发申请</button></form>`:''}
 <h3>申请全量台账</h3>
 ${table(['序号','申请','申报(字节)','已写负载','状态','插队','排队原因','操作'],detail.requests.map(r=>[
   r.seq,esc(r.code),r.declared_bytes,r.used_payload_bytes,
   `<span class="badge ${esc(r.status)}">${esc(REQUEST_STATUSES[r.status]||r.status)}</span>`,
   r.skip_count,esc(r.queue_reason||'—'),r.status==='active'&&writable()?operationButtons(d.id,r.code):'—']))}
 ${active.length&&writable()?`<h3>采样写入（仅已开工申请）</h3><form id="write-form" class="inline-form">
 <label>申请<select name="code">${active.map(r=>`<option value="${esc(r.code)}">${esc(r.code)}</option>`).join('')}</select></label>
 <label>账本键<select name="key">${Object.keys(d.ledger).map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('')}</select></label>
 <label>新整数值<input name="value" type="number" required></label>
 <label>本笔负载（字节）<input name="payload_bytes" type="number" min="1" value="80" required></label>
 <button type="submit">写入采样</button></form>`:''}
 <div class="toolbar">
 ${writable()?`<button class="secondary" id="checkpoint">静止检查点（回收空间）</button>
 <button class="secondary" id="crash">注入崩溃并恢复</button>`:''}
 <button class="secondary" id="refresh">刷新</button>
 <button class="secondary" id="export-drill">导出恢复账本 JSON</button></div>
 <h3>持久日志（未回收 ${detail.journal.length} 条）</h3>
 ${table(['LSN','操作','事务','键','值','帧字节'],detail.journal.map(j=>[j.lsn,esc(j.op),esc(j.tx||'—'),esc(j.key||'—'),j.value??'—',j.record_bytes]))}
 ${d.recovery?recoveryBlock(d.recovery):''}
 </section>`;
}

function operationButtons(drillId,code){
 return `<button class="mini" data-act="commit" data-code="${esc(code)}">提交</button>
 <button class="mini secondary" data-act="abort" data-code="${esc(code)}">撤销</button>`;
}

function recoveryBlock(r){
 return `<details open class="recovery-box"><summary>崩溃恢复账本（崩溃点 ${r.crash_after} / 检查点LSN ${r.checkpoint_lsn}）</summary>
 <div class="verdict"><div><p>恢复核对</p><h2>${r.invariant_passed?'已提交值保住、未提交撤净':'核对失败'}</h2></div>
 <p>重做 ${r.redo_count} 次 / 撤销 ${r.undo_count} 次<br>已提交 ${esc((r.committed||[]).join(', ')||'无')} ·
 未提交 ${esc((r.losers||[]).join(', ')||'无')}<br>已撤销事务 ${esc((r.aborted||[]).join(', ')||'无')}</p></div>
 ${table(['账本键','检查点值','重做后','恢复后','独立核对'],Object.keys(r.recovered||{}).map(k=>[esc(k),r.durable_checkpoint[k],r.after_redo[k],r.recovered[k],r.oracle[k]]))}
 <p class="checksum">输入摘要 ${esc(r.input_sha256)}<br>结果摘要 ${esc(r.result_sha256)}</p></details>`;
}

export function bindCapacity(render,id,list,detail){
 action(document.querySelector('#drill-form'),async f=>{
  const d=formObject(f);d.initial=JSON.parse(d.initial);
  d.capacity_bytes=Number(d.capacity_bytes);
  if(d.short_threshold_bytes)d.short_threshold_bytes=Number(d.short_threshold_bytes);else delete d.short_threshold_bytes;
  const created=await capacityAPI.create(d);location.hash='#capacity/'+created.id;
 });
 action(document.querySelector('#req-form'),async f=>{
  const d=formObject(f);d.declared_bytes=Number(d.declared_bytes);
  await capacityAPI.enqueue(Number(id),d);await render();
 });
 action(document.querySelector('#write-form'),async f=>{
  const d=formObject(f);d.value=Number(d.value);d.payload_bytes=Number(d.payload_bytes);
  await capacityAPI.write(Number(id),d.code,d);await render();
 });
 document.querySelector('#refresh')?.addEventListener('click',render);
 document.querySelector('#export-drill')?.addEventListener('click',()=>downloadCapacity(Number(id)).catch(e=>message(e.message,true)));
 document.querySelector('#checkpoint')?.addEventListener('click',async()=>{
  try{await capacityAPI.checkpoint(Number(id));message('静止检查点完成，历史日志已回收');await render();}
  catch(e){message(e.message,true);}});
 document.querySelector('#crash')?.addEventListener('click',async()=>{
  try{const out=await capacityAPI.crash(Number(id),null);
   message(`崩溃恢复完成：${out.drill.recovery.invariant_passed?'账本核对一致':'请检查'}`);await render();}
  catch(e){message(e.message,true);}});
 document.querySelectorAll('button.mini').forEach(btn=>btn.addEventListener('click',async()=>{
  try{const code=btn.dataset.code;
   if(btn.dataset.act==='commit')await capacityAPI.commit(Number(id),code);
   else await capacityAPI.abort(Number(id),code);
   await render();}catch(e){message(e.message,true);}}));
}
