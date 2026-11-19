"""容量受理服务：把纯算法落到持久表，并在每次变更后驱动受理泵。"""
import copy

from fastapi import HTTPException
from sqlalchemy import select

from src.models.entities import CapacityDrill, CapacityJournal, CapacityRequest
from src.services import capacity_engine as engine
from src.utils.serialize import record

QUEUED = 'queued'
ACTIVE = 'active'
COMMITTED = 'committed'
ABORTED = 'aborted'


# ---------- 基础读取 ----------
def list_drills(db):
    return [record(x) for x in db.scalars(select(CapacityDrill).order_by(CapacityDrill.id))]


def get_drill(db, ident):
    drill = db.get(CapacityDrill, ident)
    if drill is None:
        raise HTTPException(404, '容量演练不存在')
    return drill


def _journal(db, drill, include_reclaimed=False):
    stmt = select(CapacityJournal).where(CapacityJournal.drill_id == drill.id)
    if not include_reclaimed:
        stmt = stmt.where(CapacityJournal.reclaimed.is_(False))
    return list(db.scalars(stmt.order_by(CapacityJournal.lsn)))


def _requests(db, drill):
    return list(db.scalars(
        select(CapacityRequest).where(CapacityRequest.drill_id == drill.id).order_by(CapacityRequest.seq)))


def detail(db, ident):
    drill = get_drill(db, ident)
    reqs = _requests(db, drill)
    entries = _journal(db, drill)
    queued = [r for r in reqs if r.status == QUEUED]
    active = [r for r in reqs if r.status == ACTIVE]
    head = queued[0] if queued else None
    return {
        'drill': record(drill),
        'requests': [record(r) for r in reqs],
        'journal': [record(e) for e in entries],
        'queue_remaining': len(queued),
        'head_reason': head.queue_reason if head else '',
        'available_bytes': drill.capacity_bytes - drill.used_bytes - drill.reserved_bytes,
    }


# ---------- 演练创建 ----------
def create_drill(db, data):
    values = data.model_dump()
    try:
        engine.validate_initial(values['initial'])
        short = engine.validate_capacity(values['capacity_bytes'], values['short_threshold_bytes'])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    values['short_threshold_bytes'] = short
    values['ledger'] = copy.deepcopy(values['initial'])
    values['checkpoint_ledger'] = copy.deepcopy(values['initial'])
    drill = CapacityDrill(**values)
    db.add(drill)
    db.flush()
    return drill


# ---------- 受理泵 ----------
def _pump(db, drill):
    """按申报预留容量受理队列；短单有限插队，屏障大单不被饿死。"""
    queued = list(db.scalars(
        select(CapacityRequest).where(
            CapacityRequest.drill_id == drill.id, CapacityRequest.status == QUEUED)
        .order_by(CapacityRequest.seq)))
    plan = engine.plan_admissions(
        drill.used_bytes, drill.reserved_bytes, drill.capacity_bytes,
        drill.short_threshold_bytes,
        [{'seq': r.seq, 'code': r.code, 'declared_bytes': r.declared_bytes,
          'skip_count': r.skip_count} for r in queued])
    by_seq = {r.seq: r for r in queued}
    from src.models.entities import now
    for seq in plan['admit']:
        req = by_seq[seq]
        req.status = ACTIVE
        req.queue_reason = ''
        req.admitted_at = now()
        # 该申请独占的未来帧预留：申报负载 + 结束记录；begin 帧实际落盘后计入 used
        req.reserved_bytes = req.declared_bytes + engine.OVERHEAD
        drill.reserved_bytes += req.reserved_bytes
        _append(db, drill, 'begin', tx=req.code)
    for req in queued:
        if req.status == QUEUED:
            req.skip_count = plan['skip_counts'].get(req.seq, req.skip_count)
            req.queue_reason = plan['reasons'].get(req.seq, req.queue_reason)


def _append(db, drill, op, tx=None, key=None, value=None, payload_bytes=0):
    entry = CapacityJournal(
        drill_id=drill.id, lsn=drill.next_lsn, op=op, tx=tx, key=key, value=value,
        payload_bytes=payload_bytes, record_bytes=payload_bytes + engine.OVERHEAD)
    drill.next_lsn += 1
    drill.used_bytes += entry.record_bytes
    db.add(entry)
    return entry


def _require_running(drill):
    # running：正常受理；recovered：已完成崩溃重建，账本与队列一致后允许继续办理排队申请
    if drill.status not in ('running', 'recovered'):
        raise HTTPException(409, '演练当前状态不允许继续受理，请先完成崩溃恢复')


# ---------- 申请 ----------
def enqueue(db, ident, data):
    drill = get_drill(db, ident)
    _require_running(drill)
    try:
        engine.validate_code(data.code)
        engine.validate_capacity(drill.capacity_bytes, drill.short_threshold_bytes)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if data.declared_bytes > drill.capacity_bytes:
        raise HTTPException(422, '申报写入上限超过日志盘容量，任何时刻都无法受理')
    existing = db.scalar(select(CapacityRequest).where(
        CapacityRequest.drill_id == drill.id, CapacityRequest.code == data.code))
    if existing is not None:
        raise HTTPException(409, '申请标识在本演练内不得复用')
    if len(_journal(db, drill)) >= engine.MAX_JOURNAL:
        raise HTTPException(422, f'单个演练日志条数已达{engine.MAX_JOURNAL}上限，请先做静止检查点回收')
    req = CapacityRequest(
        drill_id=drill.id, seq=drill.next_seq, code=data.code,
        declared_bytes=data.declared_bytes, status=QUEUED)
    drill.next_seq += 1
    db.add(req)
    db.flush()
    _pump(db, drill)
    return req


# ---------- 开工后的写入与收尾 ----------
def _active_request(db, drill, code):
    req = db.scalar(select(CapacityRequest).where(
        CapacityRequest.drill_id == drill.id, CapacityRequest.code == code))
    if req is None:
        raise HTTPException(404, '申请不存在')
    if req.status != ACTIVE:
        raise HTTPException(409, f'申请当前为{req.status}状态，只有已受理（开工）申请可以写入')
    return req


def _write_locks(db, drill, exclude_tx=None):
    locks = {}
    for entry in _journal(db, drill):
        if entry.op == 'write' and entry.tx != exclude_tx:
            locks[entry.key] = entry.tx
        elif entry.op in ('commit', 'abort') and entry.tx:
            locks = {k: v for k, v in locks.items() if v != entry.tx}
    return locks


def write_sample(db, ident, code, data):
    drill = get_drill(db, ident)
    _require_running(drill)
    req = _active_request(db, drill, code)
    if data.key not in drill.ledger:
        raise HTTPException(422, '写入键必须存在于初始账本')
    locks = _write_locks(db, drill, exclude_tx=code)
    if data.key in locks:
        raise HTTPException(409, f'严格写锁：键{data.key}正被活动申请{locks[data.key]}持有')
    if req.used_payload_bytes + data.payload_bytes > req.declared_bytes:
        raise HTTPException(422, f'本次写入将超过申报上限{req.declared_bytes}字节'
                                 f'（已用{req.used_payload_bytes}）')
    # reserved 已含本事务“剩余负载 + 结束帧”；新帧负载会从 reserved 转入 used，
    # 因此新增占用只有本帧固定开销 OVERHEAD，负载部分不重复计算。
    if drill.used_bytes + drill.reserved_bytes + engine.OVERHEAD > drill.capacity_bytes:
        raise HTTPException(422, '日志盘已写满，本笔写入无法落盘；已开工申请仍可提交或撤销，'
                                '静止检查点可回收空间')
    drill.ledger[data.key] = data.value
    req.used_payload_bytes += data.payload_bytes
    # 该笔负载已实际落盘进 used，从该申请自己的未来帧预留中扣减，避免双重占用
    req.reserved_bytes -= data.payload_bytes
    drill.reserved_bytes -= data.payload_bytes
    if req.reserved_bytes < 0:
        req.reserved_bytes = 0
    if drill.reserved_bytes < 0:
        drill.reserved_bytes = 0
    _append(db, drill, 'write', tx=code, key=data.key, value=data.value,
            payload_bytes=data.payload_bytes)
    return req


def finish(db, ident, code, outcome):
    drill = get_drill(db, ident)
    _require_running(drill)
    req = _active_request(db, drill, code)
    op = 'commit' if outcome == 'commit' else 'abort'
    # reserved 已含本事务结束记录帧，若 used+reserved 仍超容量说明核算被外部破坏
    if drill.used_bytes + drill.reserved_bytes > drill.capacity_bytes:
        raise HTTPException(422, '日志盘写满且结束记录也无法落盘，请先执行静止检查点')
    if op == 'abort':
        for entry in reversed(_journal(db, drill)):
            if entry.tx == code and entry.op == 'write':
                drill.ledger[entry.key] = _before_value(db, drill, entry)
    _append(db, drill, op, tx=code)
    # 释放该申请自己剩余的预留（写入后通常只剩结束帧），不影响其它活动事务的预留
    drill.reserved_bytes -= req.reserved_bytes
    req.reserved_bytes = 0
    if drill.reserved_bytes < 0:
        drill.reserved_bytes = 0
    req.status = COMMITTED if op == 'commit' else ABORTED
    from src.models.entities import now
    req.finished_at = now()
    _pump(db, drill)
    return req


def _before_value(db, drill, target):
    before = drill.checkpoint_ledger.get(target.key)
    for entry in _journal(db, drill):
        if entry.lsn >= target.lsn:
            break
        if entry.op == 'write' and entry.key == target.key:
            before = entry.value
    return before


# ---------- 静止检查点 ----------
def checkpoint(db, ident):
    drill = get_drill(db, ident)
    _require_running(drill)
    active = db.scalars(select(CapacityRequest).where(
        CapacityRequest.drill_id == drill.id, CapacityRequest.status == ACTIVE)).all()
    if active:
        raise HTTPException(409, '存在已开工未收尾申请，仅支持无活动申请的静止检查点')
    if drill.used_bytes == 0:
        raise HTTPException(409, '当前没有可回收的日志记录')
    _append(db, drill, 'checkpoint')
    old = db.scalars(select(CapacityJournal).where(
        CapacityJournal.drill_id == drill.id,
        CapacityJournal.reclaimed.is_(False),
        CapacityJournal.lsn < drill.next_lsn - 1)).all()
    reclaimed = sum(e.record_bytes for e in old)
    for entry in old:
        entry.reclaimed = True
    drill.reclaimed_bytes += reclaimed
    drill.used_bytes -= reclaimed
    if drill.used_bytes < 0:
        drill.used_bytes = 0
    drill.checkpoint_lsn = drill.next_lsn - 1
    drill.checkpoint_ledger = copy.deepcopy(drill.ledger)
    _pump(db, drill)
    return drill


# ---------- 崩溃与恢复 ----------
def crash(db, ident, crash_after):
    drill = get_drill(db, ident)
    _require_running(drill)
    entries = list(db.scalars(select(CapacityJournal).where(
        CapacityJournal.drill_id == drill.id).order_by(CapacityJournal.lsn)))
    if crash_after is None:
        crash_after = len(entries)
    if crash_after > len(entries):
        raise HTTPException(422, '崩溃点超过当前日志条数')
    durable_lsns = {e.lsn for e in entries[:crash_after]}
    result = engine.recover(
        drill.initial, drill.checkpoint_ledger, drill.checkpoint_lsn,
        drill.reclaimed_bytes,
        [{'lsn': e.lsn, 'op': e.op, 'tx': e.tx, 'key': e.key, 'value': e.value,
          'record_bytes': e.record_bytes} for e in entries],
        crash_after)
    for entry in entries:
        if entry.lsn not in durable_lsns:
            drill.used_bytes -= entry.record_bytes
            db.delete(entry)
    drill.ledger = copy.deepcopy(result['recovered'])
    drill.reserved_bytes = 0
    drill.status = 'recovered'
    drill.recovery = result
    # 崩溃时未收尾的申请：未落盘写入全部撤销，申请回到队列，恢复后可继续受理。
    for req in _requests(db, drill):
        if req.status == ACTIVE:
            req.status = QUEUED
            req.used_payload_bytes = 0
            req.reserved_bytes = 0
            req.admitted_at = None
            req.skip_count = 0
            req.queue_reason = '崩溃恢复：未落盘写入已撤销，申请重新排队等待受理'
        elif req.status == QUEUED:
            req.queue_reason = '崩溃恢复：排队申请保留，待空间满足后继续受理'
    db.flush()
    _pump(db, drill)
    return drill


def export_bundle(db, ident):
    return detail(db, ident)
