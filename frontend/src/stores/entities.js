import {logSetsAPI,crashCasesAPI,recoveriesAPI} from '../api/entities.js';
export const store={logs:[],cases:[],runs:[],async refresh(){[this.logs,this.cases,this.runs]=await Promise.all([logSetsAPI.list(),crashCasesAPI.list(),recoveriesAPI.list()]);}};
