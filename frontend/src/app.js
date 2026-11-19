import {session} from './stores/session.js';
import {store} from './stores/entities.js';
import {recoveriesAPI} from './api/entities.js';
import {layout} from './components/common/layout.js';
import {loginPage,bindLogin} from './pages/login.js';
import {logsPage,bindLogs} from './pages/logs.js';
import {casesPage,bindCases} from './pages/cases.js';
import {runsPage,bindRuns} from './pages/runs.js';
import {detailPage,bindDetail} from './pages/detail.js';
import {routes} from './router/routes.js';
import {esc} from './utils/html.js';
const app=document.querySelector('#app');
async function render(){
 const [key,id]=location.hash.slice(1).split('/');
 if(!session.token||key==='login'){app.innerHTML=loginPage();bindLogin();return;}
 try{await store.refresh();let body,job;const route=routes[key]?key:'logs';
 if(route==='logs')body=logsPage();if(route==='cases')body=casesPage();if(route==='runs')body=runsPage();if(route==='detail'){job=id?await recoveriesAPI.get(Number(id)):store.runs[0];body=detailPage(job);}
 app.innerHTML=layout(...routes[route],body);document.querySelector('#logout').onclick=()=>{session.clear();location.hash='#login';};
 if(route==='logs')bindLogs(render);if(route==='cases')bindCases(render);if(route==='runs')bindRuns(render);if(route==='detail')bindDetail(job,render);
 }catch(e){app.innerHTML=layout('暂时无法载入','请检查服务状态后重试。',`<p class="notice error">${esc(e.message)}</p><button id="retry">重新加载</button>`);document.querySelector('#retry').onclick=render;document.querySelector('#logout').onclick=()=>{session.clear();location.hash='#login';};}
}
window.addEventListener('hashchange',render);render();
