import {api} from '../api/client.js';
import {session} from '../stores/session.js';
import {action} from '../hooks/action.js';
export function loginPage(){return `<div class="login"><section><p class="eyebrow">HAILI / RECOVERY LABORATORY</p><h1>断电之后，<br>哪些写入<br>应该留下？</h1><p>沿着日志前缀追踪已提交和未提交事务，复核每次重做与撤销。</p><div class="boundary">Python WAL教学模型 · 不模拟页面上的生产恢复成功率</div></section><form id="login"><h2>进入恢复演练册</h2><label>账号<input name="email" type="email" value="operator@haili.local" required></label><label>密码<input name="password" type="password" value="Recovery2026!" required></label><button type="submit">打开实验记录 →</button><p>admin / operator / viewer @haili.local<br>演示密码 Recovery2026!</p><div id="notice" hidden></div></form></div>`;}
export function bindLogin(){action(document.querySelector('#login'),async form=>{session.save(await api('/auth/login',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))}));location.hash='#logs';});}
