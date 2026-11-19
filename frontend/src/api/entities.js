import {api} from './client.js';
export const logSetsAPI={list:()=>api('/log-sets'),create:data=>api('/log-sets',{method:'POST',body:JSON.stringify(data)})};
export const crashCasesAPI={list:()=>api('/crash-cases'),create:data=>api('/crash-cases',{method:'POST',body:JSON.stringify(data)})};
export const recoveriesAPI={list:()=>api('/recoveries'),get:id=>api('/recoveries/'+id),create:data=>api('/recoveries',{method:'POST',body:JSON.stringify(data)})};
export const capacityAPI={
 list:()=>api('/capacity-drills'),
 get:id=>api('/capacity-drills/'+id),
 create:data=>api('/capacity-drills',{method:'POST',body:JSON.stringify(data)}),
 enqueue:(id,data)=>api(`/capacity-drills/${id}/requests`,{method:'POST',body:JSON.stringify(data)}),
 write:(id,code,data)=>api(`/capacity-drills/${id}/requests/${encodeURIComponent(code)}/writes`,{method:'POST',body:JSON.stringify(data)}),
 commit:(id,code)=>api(`/capacity-drills/${id}/requests/${encodeURIComponent(code)}/commit`,{method:'POST'}),
 abort:(id,code)=>api(`/capacity-drills/${id}/requests/${encodeURIComponent(code)}/abort`,{method:'POST'}),
 checkpoint:id=>api(`/capacity-drills/${id}/checkpoint`,{method:'POST'}),
 crash:(id,crash_after)=>api(`/capacity-drills/${id}/crash`,{method:'POST',body:JSON.stringify({crash_after})}),
};
