import {esc} from '../../utils/html.js';
export function table(headers,rows){return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.map(row=>`<tr>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${headers.length}">尚无记录。请先保存日志集与故障场景，再提交恢复任务。</td></tr>`}</tbody></table></div>`;}
