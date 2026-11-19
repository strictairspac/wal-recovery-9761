"""Log-disk capacity admission, bounded queueing and quiescent-checkpoint crash recovery.

教学模型，不模拟真实磁盘故障：
- 申请受理时按“申报写入上限 + 结束记录开销”预留空间，保证开工后即使写满申报额度也一定能提交或撤销；
- 放不下的申请进入持久队列，短单可有限插队，被插队次数达到上限的大单成为屏障，不会饿死；
- 静止检查点回收检查点之前的日志字节，腾出空间后继续受理队列；
- 崩溃后从最近静止检查点重放持久日志前缀，保住已提交值、撤净未提交值，排队申请继续受理。
"""
import copy
import hashlib
import json
import re

OVERHEAD = 64              # 每条日志记录（begin/write/commit/abort/checkpoint）的固定帧开销（字节）
END_RECORDS = 2            # 开工后至少还要写 commit/abort 与可能的结束记录，受理时预留两条记录开销
MAX_SKIPS = 3              # 队首大单最多被短单插队的次数，达到后成为屏障
MAX_JOURNAL = 500          # 单个演练日志条数上限，避免页面与账本无限增长
CAPACITY_MAX = 10_000_000_000
VALUE_LIMIT = 1_000_000_000
KEY_RE = re.compile(r'[A-Za-z0-9_-]{1,50}')
CODE_RE = re.compile(r'[A-Za-z0-9_-]{1,30}')
MODEL_VERSION = 'capacity-wal-quiescent-v1'
BOUNDARY = ('Python 日志盘容量教学模型；申报预留、有界短单插队、静止检查点回收、'
            '整数键值、日志前缀持久。没有注入真实磁盘故障，未执行数据库物理恢复。')


def need_bytes(declared):
    """受理一个申请需要预留的总字节：申报写入上限 + begin/commit(abort) 两条记录帧。"""
    return declared + END_RECORDS * OVERHEAD


def validate_initial(initial):
    if not initial or len(initial) > 30:
        raise ValueError('需1—30个初始账本键')
    for key, value in initial.items():
        if not KEY_RE.fullmatch(key) or isinstance(value, bool) or not isinstance(value, int) or abs(value) > VALUE_LIMIT:
            raise ValueError('初始键为字母数字下划线短横线，值为绝对值不超过10亿的整数')
    return True


def validate_capacity(capacity_bytes, short_threshold_bytes=None):
    if not isinstance(capacity_bytes, int) or isinstance(capacity_bytes, bool) or not 1 <= capacity_bytes <= CAPACITY_MAX:
        raise ValueError(f'日志容量为1—{CAPACITY_MAX}字节之间的整数')
    if capacity_bytes < need_bytes(1):
        raise ValueError('日志容量过小，至少要能容纳一条申报写入与开工/结束记录')
    if short_threshold_bytes is None:
        short_threshold_bytes = max(1, capacity_bytes // 10)
    if not isinstance(short_threshold_bytes, int) or isinstance(short_threshold_bytes, bool) or not 1 <= short_threshold_bytes <= capacity_bytes:
        raise ValueError('短单阈值须为不超过日志容量的正整数')
    return short_threshold_bytes


def validate_code(code):
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise ValueError('申请标识为1—30位字母数字下划线短横线')
    return True


def plan_admissions(used_bytes, reserved_bytes, capacity_bytes, short_threshold_bytes, queued):
    """纯函数：给定当前占用与排队申请，返回本轮可受理序列、排队原因与最新插队计数。

    queued: [{'seq','code','declared_bytes','skip_count'}]，按到达顺序给出。
    规则：
    - 队首放得下就受理；放不下时，仅允许其后的“短单”（申报额<=阈值）绕过队首；
    - 队首每被绕过一次 skip_count+1，达到 MAX_SKIPS 后成为屏障，本轮不再放行任何申请；
    - 非短单严格按到达顺序，不能绕过前序申请。
    """
    available = capacity_bytes - used_bytes - reserved_bytes
    if available < 0:
        raise ValueError('预留核算异常：已占用字节超过日志容量')
    pending = sorted(queued, key=lambda item: item['seq'])
    skips = {item['seq']: item.get('skip_count', 0) for item in pending}
    admitted = []
    i = 0
    while i < len(pending):
        head = pending[i]
        if need_bytes(head['declared_bytes']) <= available:
            admitted.append(head['seq'])
            available -= need_bytes(head['declared_bytes'])
            i += 1
            continue
        if skips[head['seq']] >= MAX_SKIPS:
            break  # 队首已是屏障，短单也不再放行，直到检查点/事务结束腾出空间
        moved = False
        j = i + 1
        while j < len(pending):
            candidate = pending[j]
            is_short = candidate['declared_bytes'] <= short_threshold_bytes
            if is_short and need_bytes(candidate['declared_bytes']) <= available:
                admitted.append(candidate['seq'])
                available -= need_bytes(candidate['declared_bytes'])
                skips[head['seq']] += 1
                pending.pop(j)
                moved = True
                if skips[head['seq']] >= MAX_SKIPS:
                    break
            else:
                j += 1
        if not moved:
            break
    admitted_set = set(admitted)
    reasons = {}
    remaining = [item for item in pending if item['seq'] not in admitted_set]
    for index, item in enumerate(remaining):
        need = need_bytes(item['declared_bytes'])
        if index == 0:
            if skips[item['seq']] >= MAX_SKIPS:
                reasons[item['seq']] = (f'容量不足且已被短单插队{MAX_SKIPS}次，成为屏障：'
                                        f'可用{available}字节，本单含记录开销需{need}字节，须等检查点腾空间')
            else:
                reasons[item['seq']] = (f'容量不足排队：当前可用{available}字节，'
                                        f'申报{item["declared_bytes"]}字节加{END_RECORDS}条记录开销共需{need}字节')
        else:
            reasons[item['seq']] = '前序申请尚未受理，按到达顺序排队（短单在容量允许时可有限插队）'
    return {'admit': admitted, 'skip_counts': skips, 'reasons': reasons, 'available_after': available}


def recover(initial, checkpoint_ledger, checkpoint_lsn, reclaimed_bytes, entries, crash_after):
    """从最近静止检查点与持久日志前缀重建账本。

    entries: [{'lsn','op','tx','key','value','record_bytes'}]，按 lsn 升序。
    崩溃点 crash_after 表示前 crash_after 条日志已持久化，其后的记录视为未落盘并丢弃。
    已提交事务的值保留，未结束事务的写入按 LSN 倒序撤销，独立 oracle 仅应用已提交写入做核对。
    """
    validate_initial(initial)
    if not isinstance(crash_after, int) or isinstance(crash_after, bool) or not 0 <= crash_after <= len(entries):
        raise ValueError('崩溃点超出日志范围')
    durable = copy.deepcopy(checkpoint_ledger or initial)
    latest_checkpoint = checkpoint_lsn or 0
    prefix = entries[:crash_after]
    state = copy.deepcopy(durable)
    active = {}
    winners = []
    aborted = []
    all_committed = []
    all_aborted = []
    winner_writes = []
    trace = []
    for entry in prefix:
        lsn = entry['lsn']
        if lsn <= latest_checkpoint:
            continue
        op = entry['op']
        tx = entry.get('tx')
        if op == 'checkpoint':
            latest_checkpoint = lsn
            durable = copy.deepcopy(state)
            active = {}
            winners = []
            aborted = []
            winner_writes = []
            trace = []
            continue
        if op == 'begin':
            active[tx] = []
        elif op == 'write':
            if tx not in active:
                raise ValueError(f'LSN {lsn}: 写入事务尚未begin')
            if entry['key'] not in state:
                raise ValueError(f'LSN {lsn}: 写入键必须存在于初始账本')
            row = {'lsn': lsn, 'tx': tx, 'key': entry['key'],
                   'before': state[entry['key']], 'after': entry['value']}
            active[tx].append(row)
            state[entry['key']] = entry['value']
            trace.append(dict(row, phase='redo'))
        elif op == 'abort':
            if tx not in active:
                raise ValueError(f'LSN {lsn}: 事务未开启或已结束')
            for row in reversed(active[tx]):
                state[row['key']] = row['before']
                trace.append(dict(row, phase='redo_abort_undo'))
            del active[tx]
            aborted.append(tx)
            all_aborted.append(tx)
        elif op == 'commit':
            if tx not in active:
                raise ValueError(f'LSN {lsn}: 事务未开启或已结束')
            winner_writes.extend(active[tx])
            winners.append(tx)
            all_committed.append(tx)
            del active[tx]
        else:
            raise ValueError(f'LSN {lsn}: 未知操作')
    before_undo = copy.deepcopy(state)
    losers = sorted(active)
    undo = sorted((row for tx in active for row in active[tx]),
                  key=lambda row: row['lsn'], reverse=True)
    for row in undo:
        state[row['key']] = row['before']
        trace.append(dict(row, phase='undo_loser'))
    oracle = copy.deepcopy(durable)
    for row in winner_writes:
        oracle[row['key']] = row['after']
    used_bytes = sum(entry['record_bytes'] for entry in prefix if entry['lsn'] > latest_checkpoint)
    source = json.dumps({'initial': initial, 'checkpoint_lsn': checkpoint_lsn,
                         'entries': entries, 'crash_after': crash_after}, sort_keys=True)
    return {
        'simulation': True,
        'model_version': MODEL_VERSION,
        'boundary': BOUNDARY,
        'crash_after': crash_after,
        'checkpoint_lsn': latest_checkpoint,
        'durable_checkpoint': durable,
        'after_redo': before_undo,
        'recovered': state,
        'oracle': oracle,
        'invariant_passed': state == oracle,
        'committed': all_committed,
        'aborted': all_aborted,
        'losers': losers,
        'redo_count': len([row for row in trace if row['phase'] == 'redo']),
        'undo_count': len(undo),
        'trace': trace,
        'used_bytes': used_bytes,
        'reserved_bytes': 0,
        'reclaimed_bytes': reclaimed_bytes,
        'kept_journal_count': len(prefix),
        'result_sha256': hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest(),
        'input_sha256': hashlib.sha256(source.encode()).hexdigest(),
    }
