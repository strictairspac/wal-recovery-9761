import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {crashCasesAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {esc,formObject} from '../utils/html.js';
import {action} from '../hooks/action.js';
export function casesPage(){return `<div class="section-title"><h2>故障注入点</h2><span>崩溃点为已持久化日志条数</span></div>${table(['场景','日志集','崩溃点'],store.cases.map(c=>[esc(c.name),esc(store.logs.find(l=>l.id===c.log_set_id)?.name),c.crash_after]))}<section class="split"><div><h2>选择故障发生时刻</h2><p>0表示没有任何日志持久化，N表示前N条日志已经落盘。检查点以后尚未写回的数据页，通过日志重建；未提交事务必须撤销。</p><p class="big-note">提交边界，决定恢复结果。</p></div>${session.role!=='viewer'?`<form id="case-form"><label>场景名称<input name="name" value="晚班断电点10" required></label><label>日志集<select name="log_set_id">${store.logs.map(l=>`<option value="${l.id}">${esc(l.name)} · ${l.records.length}条</option>`).join('')}</select></label><label>崩溃点<input name="crash_after" type="number" min="0" max="200" value="10" required></label><button type="submit">保存故障场景</button></form>`:'<p class="readonly">观察员可复核故障场景。</p>'}</section>`;}
export function bindCases(render){action(document.querySelector('#case-form'),async f=>{const d=formObject(f);d.log_set_id=Number(d.log_set_id);d.crash_after=Number(d.crash_after);await crashCasesAPI.create(d);await render();});}
