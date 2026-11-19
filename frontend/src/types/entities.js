/** @typedef {{id:number,name:string,initial:object,records:object[],description:string}} LogSet */
/** @typedef {{id:number,name:string,log_set_id:number,crash_after:number}} CrashCase */
/** @typedef {{id:number,crash_case_id:number,label:string,status:string,snapshot:object,result:object|null}} Recovery */
/** @typedef {{id:number,name:string,capacity_bytes:number,short_threshold_bytes:number,used_bytes:number,reserved_bytes:number,reclaimed_bytes:number,checkpoint_lsn:number,status:string,ledger:object,recovery:object|null}} CapacityDrill */
/** @typedef {{id:number,drill_id:number,seq:number,code:string,declared_bytes:number,used_payload_bytes:number,status:string,queue_reason:string,skip_count:number}} CapacityRequest */
export {};
