import {DRILL_STATUSES} from '../../constants/enums.js';
import {esc} from '../../utils/html.js';
export const badge=(status)=>`<span class="badge ${esc(status)}">${esc(DRILL_STATUSES[status]||status)}</span>`;
