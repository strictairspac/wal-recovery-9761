"""服务层编排测试：受理预留、短单插队/屏障、检查点回收、崩溃恢复与排队续办。"""
import unittest
from types import SimpleNamespace

from tests import _stubs  # noqa: F401  注册 sqlalchemy / fastapi 替身
from tests._stubs import FakeSession, HTTPException

from src.services import capacity_service as svc
from src.services import capacity_engine as engine


def input_(**kwargs):
    return SimpleNamespace(model_dump=lambda: dict(kwargs), **kwargs)


class ServiceFlowTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSession()
        self.drill = svc.create_drill(self.db, input_(
            name='日志盘容量演练-1', initial={'A': 100, 'B': 50},
            capacity_bytes=1000, short_threshold_bytes=None, description=''))

    def test_full_disk_queues_with_visible_reason_then_resumes(self):
        svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=300))
        svc.enqueue(self.db, self.drill.id, input_(code='TX2', declared_bytes=300))
        detail = svc.detail(self.db, self.drill.id)
        self.assertEqual([r['code'] for r in detail['requests']], ['TX1', 'TX2'])
        self.assertEqual(detail['queue_remaining'], 0)
        # 第三单整体放不下：排队并给出字节级原因
        svc.enqueue(self.db, self.drill.id, input_(code='TX3', declared_bytes=100))
        detail = svc.detail(self.db, self.drill.id)
        self.assertEqual(detail['queue_remaining'], 1)
        self.assertIn('容量不足排队', detail['head_reason'])
        tx3 = next(r for r in detail['requests'] if r['code'] == 'TX3')
        self.assertEqual(tx3['status'], 'queued')
        # TX1 收尾释放预留，泵自动受理 TX3
        svc.finish(self.db, self.drill.id, 'TX1', 'commit')
        detail = svc.detail(self.db, self.drill.id)
        self.assertEqual(detail['queue_remaining'], 0)
        tx3 = next(r for r in detail['requests'] if r['code'] == 'TX3')
        self.assertEqual(tx3['status'], 'active')

    def test_commit_always_fits_even_when_declared_quota_fills_disk(self):
        svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=200))
        svc.write_sample(self.db, self.drill.id, 'TX1',
                         input_(key='A', value=90, payload_bytes=100))
        svc.write_sample(self.db, self.drill.id, 'TX1',
                         input_(key='A', value=80, payload_bytes=100))
        detail = svc.detail(self.db, self.drill.id)
        # begin(64)+write(164)*2=392；负载200已落盘，预留只剩结束帧64
        self.assertEqual(detail['drill']['used_bytes'], 392)
        self.assertEqual(detail['drill']['reserved_bytes'], 64)
        self.assertEqual(detail['available_bytes'], 1000 - 392 - 64)
        # 超申报额度被拒
        with self.assertRaises(HTTPException) as blocked:
            svc.write_sample(self.db, self.drill.id, 'TX1',
                             input_(key='A', value=70, payload_bytes=1))
        self.assertEqual(blocked.exception.status_code, 422)
        self.assertIn('申报上限', blocked.exception.detail)
        # 即使申报额度已用满，commit 仍由预留的结束帧保证落盘
        req = svc.finish(self.db, self.drill.id, 'TX1', 'commit')
        self.assertEqual(req.status, 'committed')
        self.assertEqual(svc.detail(self.db, self.drill.id)['drill']['ledger']['A'], 80)

    def test_short_jump_barrier_and_checkpoint_reclaim(self):
        drill = svc.create_drill(self.db, input_(
            name='插队与屏障', initial={'A': 0}, capacity_bytes=1500,
            short_threshold_bytes=150, description=''))
        # HOLD 受理后占用 used64 + 预留864 = 928，可用 572
        svc.enqueue(self.db, drill.id, input_(code='HOLD', declared_bytes=800))
        # 队首大单 need(900)=1028 > 572，先排队
        svc.enqueue(self.db, drill.id, input_(code='BIG', declared_bytes=900))
        codes = ['S1', 'S2', 'S3', 'S4']
        for code in codes:
            svc.enqueue(self.db, drill.id, input_(code=code, declared_bytes=50))
        detail = svc.detail(self.db, drill.id)
        statuses = {r['code']: r['status'] for r in detail['requests']}
        self.assertEqual(statuses['BIG'], 'queued')
        # 短单 need=178，可连续插队 3 次，第 4 次被屏障挡住
        self.assertEqual([c for c in codes if statuses[c] == 'active'], ['S1', 'S2', 'S3'])
        self.assertEqual([c for c in codes if statuses[c] == 'queued'], ['S4'])
        big = next(r for r in detail['requests'] if r['code'] == 'BIG')
        self.assertEqual(big['skip_count'], engine.MAX_SKIPS)
        self.assertIn('屏障', big['queue_reason'])
        # 已受理事务全部收尾，释放预留后泵继续受理 BIG 与 S4（大单优先、不饿死）
        svc.finish(self.db, drill.id, 'HOLD', 'commit')
        for code in ('S1', 'S2', 'S3'):
            svc.finish(self.db, drill.id, code, 'commit')
        # 已受理事务全部结束，无活动事务；BIG/S4 仍排队（容量未释放够）
        detail = svc.detail(self.db, drill.id)
        self.assertEqual(next(r for r in detail['requests'] if r['code'] == 'BIG')['status'], 'queued')
        self.assertEqual(next(r for r in detail['requests'] if r['code'] == 'S4')['status'], 'queued')
        # 静止检查点回收历史日志腾出空间，受理泵随即继续办理 BIG（不饿死）与 S4
        svc.checkpoint(self.db, drill.id)
        detail = svc.detail(self.db, drill.id)
        self.assertGreater(detail['drill']['reclaimed_bytes'], 0)
        self.assertEqual(next(r for r in detail['requests'] if r['code'] == 'BIG')['status'], 'active')
        self.assertEqual(next(r for r in detail['requests'] if r['code'] == 'S4')['status'], 'active')
        svc.finish(self.db, drill.id, 'BIG', 'commit')
        svc.finish(self.db, drill.id, 'S4', 'commit')
        self.assertEqual(svc.detail(self.db, drill.id)['queue_remaining'], 0)

    def test_checkpoint_requires_no_active_request(self):
        svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=100))
        with self.assertRaises(HTTPException) as blocked:
            svc.checkpoint(self.db, self.drill.id)
        self.assertEqual(blocked.exception.status_code, 409)

    def test_crash_keeps_committed_undoes_losers_and_queued_requests_continue(self):
        drill = svc.create_drill(self.db, input_(
            name='崩溃恢复', initial={'A': 100, 'B': 50}, capacity_bytes=4000,
            short_threshold_bytes=200, description=''))
        svc.enqueue(self.db, drill.id, input_(code='T1', declared_bytes=200))
        svc.write_sample(self.db, drill.id, 'T1',
                         input_(key='A', value=60, payload_bytes=80))
        svc.finish(self.db, drill.id, 'T1', 'commit')           # 已提交：A=60
        svc.enqueue(self.db, drill.id, input_(code='T2', declared_bytes=200))
        svc.write_sample(self.db, drill.id, 'T2',
                         input_(key='B', value=9, payload_bytes=80))  # 未提交
        svc.enqueue(self.db, drill.id, input_(code='Q1', declared_bytes=100))  # 排队中
        entries = svc.detail(self.db, drill.id)['journal']
        crash_after = len(entries)
        svc.crash(self.db, drill.id, crash_after)
        bundle = svc.detail(self.db, drill.id)
        recovery = bundle['drill']['recovery']
        self.assertTrue(recovery['invariant_passed'])
        self.assertEqual(recovery['recovered'], {'A': 60, 'B': 50})   # 提交保住、未提交撤净
        self.assertEqual(bundle['drill']['ledger'], {'A': 60, 'B': 50})
        statuses = {r['code']: r['status'] for r in bundle['requests']}
        self.assertEqual(statuses['T1'], 'committed')
        # 容量充足：崩溃后受理泵立即把 T2、Q1 重新受理，演练不中断
        self.assertEqual(statuses['T2'], 'active')
        self.assertEqual(statuses['Q1'], 'active')
        t2 = next(r for r in bundle['requests'] if r['code'] == 'T2')
        self.assertEqual(t2['used_payload_bytes'], 0)                 # 未落盘写入已撤净

    def test_crash_preserves_queued_requests_until_space_allows(self):
        # 小容量演练：崩溃后空间仍不足时，原排队申请保持排队并携带原因，检查点腾空间后续办
        drill = svc.create_drill(self.db, input_(
            name='崩溃排队保留', initial={'A': 0}, capacity_bytes=600,
            short_threshold_bytes=100, description=''))
        svc.enqueue(self.db, drill.id, input_(code='HOLD', declared_bytes=300))
        svc.enqueue(self.db, drill.id, input_(code='WAIT', declared_bytes=300))  # 放不下，排队
        before = svc.detail(self.db, drill.id)
        self.assertEqual(before['queue_remaining'], 1)
        svc.crash(self.db, drill.id, len(before['journal']))
        after = svc.detail(self.db, drill.id)
        wait = next(r for r in after['requests'] if r['code'] == 'WAIT')
        hold = next(r for r in after['requests'] if r['code'] == 'HOLD')
        # 原排队申请跨崩溃保留：仍排队且原因可核对；HOLD 容量够则被泵重新受理
        self.assertEqual(wait['status'], 'queued')
        self.assertTrue(wait['queue_reason'])
        self.assertIn('容量不足', wait['queue_reason'])
        self.assertEqual(hold['status'], 'active')
        # HOLD 收尾后静止检查点腾出空间，WAIT 接着受理，演练不中断
        svc.finish(self.db, drill.id, 'HOLD', 'commit')
        svc.checkpoint(self.db, drill.id)
        detail = svc.detail(self.db, drill.id)
        wait = next(r for r in detail['requests'] if r['code'] == 'WAIT')
        self.assertEqual(wait['status'], 'active')
        self.assertEqual(detail['queue_remaining'], 0)

    def test_abort_rolls_back_after_using_full_declared_quota(self):
        drill = svc.create_drill(self.db, input_(
            name='写满撤销演练', initial={'A': 100, 'B': 50}, capacity_bytes=500,
            short_threshold_bytes=None, description=''))
        svc.enqueue(self.db, drill.id, input_(code='F1', declared_bytes=236))
        # 用满申报负载额度：172+64=236；受理预留保证这些写入与结束帧一定落盘
        svc.write_sample(self.db, drill.id, 'F1',
                         input_(key='A', value=30, payload_bytes=172))
        svc.write_sample(self.db, drill.id, 'F1',
                         input_(key='B', value=20, payload_bytes=64))
        detail = svc.detail(self.db, drill.id)
        self.assertEqual(detail['drill']['used_bytes'], 64 + 236 + 128)  # begin+两帧
        self.assertEqual(detail['drill']['reserved_bytes'], 64)         # 仅剩结束帧
        # 即使把申报额度写满，撤销依旧可以：倒序回滚 A、B，账本恢复
        req = svc.finish(self.db, drill.id, 'F1', 'abort')
        self.assertEqual(req.status, 'aborted')
        detail = svc.detail(self.db, drill.id)
        self.assertEqual(detail['drill']['ledger'], {'A': 100, 'B': 50})
        # 撤销释放预留与帧后，空间回来，排队申请可被受理
        self.assertEqual(detail['drill']['reserved_bytes'], 0)

    def test_committed_value_survives_crash_across_checkpoint(self):
        drill = svc.create_drill(self.db, input_(
            name='跨检查点崩溃', initial={'A': 100}, capacity_bytes=3000,
            short_threshold_bytes=200, description=''))
        svc.enqueue(self.db, drill.id, input_(code='T1', declared_bytes=200))
        svc.write_sample(self.db, drill.id, 'T1',
                         input_(key='A', value=60, payload_bytes=80))
        svc.finish(self.db, drill.id, 'T1', 'commit')      # A=60 已提交
        svc.checkpoint(self.db, drill.id)                  # 静止检查点冻结
        svc.enqueue(self.db, drill.id, input_(code='T2', declared_bytes=200))
        svc.write_sample(self.db, drill.id, 'T2',
                         input_(key='A', value=9, payload_bytes=80))  # 未提交
        n = len(svc.detail(self.db, drill.id)['journal'])
        svc.crash(self.db, drill.id, n)
        rec = svc.detail(self.db, drill.id)['drill']['recovery']
        self.assertGreater(rec['checkpoint_lsn'], 0)
        self.assertEqual(rec['recovered'], {'A': 60})      # 已提交保住、T2 撤净
        self.assertTrue(rec['invariant_passed'])

    def test_reservation_is_isolated_per_request_and_released_on_finish(self):
        svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=200))
        svc.enqueue(self.db, self.drill.id, input_(code='TX2', declared_bytes=100))
        detail = svc.detail(self.db, self.drill.id)
        # 两个活动申请各自预留：(200+64)+(100+64)=428，begin 两帧 128 进 used
        self.assertEqual(detail['drill']['reserved_bytes'], 428)
        self.assertEqual(detail['drill']['used_bytes'], 128)
        svc.write_sample(self.db, self.drill.id, 'TX1',
                         input_(key='A', value=1, payload_bytes=80))
        detail = svc.detail(self.db, self.drill.id)
        # TX1 的负载只扣它自己的预留，TX2 的 164 不受影响
        self.assertEqual(detail['drill']['reserved_bytes'], 428 - 80)
        # TX1 收尾只释放它剩余预留（200-80+64=184），TX2 预留原样保留
        svc.finish(self.db, self.drill.id, 'TX1', 'commit')
        detail = svc.detail(self.db, self.drill.id)
        self.assertEqual(detail['drill']['reserved_bytes'], 164)
        tx2 = next(r for r in detail['requests'] if r['code'] == 'TX2')
        self.assertEqual(tx2['reserved_bytes'], 164)
        svc.finish(self.db, self.drill.id, 'TX2', 'abort')
        self.assertEqual(svc.detail(self.db, self.drill.id)['drill']['reserved_bytes'], 0)

    def test_code_cannot_be_reused(self):
        svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=100))
        svc.finish(self.db, self.drill.id, 'TX1', 'commit')
        with self.assertRaises(HTTPException) as blocked:
            svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=100))
        self.assertEqual(blocked.exception.status_code, 409)

    def test_write_lock_conflict_rejected(self):
        svc.enqueue(self.db, self.drill.id, input_(code='TX1', declared_bytes=200))
        svc.enqueue(self.db, self.drill.id, input_(code='TX2', declared_bytes=200))
        svc.write_sample(self.db, self.drill.id, 'TX1',
                         input_(key='A', value=1, payload_bytes=50))
        with self.assertRaises(HTTPException) as blocked:
            svc.write_sample(self.db, self.drill.id, 'TX2',
                             input_(key='A', value=2, payload_bytes=50))
        self.assertEqual(blocked.exception.status_code, 409)
        # 不同键不受锁影响
        svc.write_sample(self.db, self.drill.id, 'TX2',
                         input_(key='B', value=2, payload_bytes=50))
        # TX1 撤销释放 A 键并回滚账本，随后 TX2 可写同键
        svc.finish(self.db, self.drill.id, 'TX1', 'abort')
        svc.write_sample(self.db, self.drill.id, 'TX2',
                         input_(key='A', value=2, payload_bytes=50))
        detail = svc.detail(self.db, self.drill.id)
        self.assertEqual(detail['drill']['ledger']['A'], 2)
        self.assertEqual(detail['drill']['ledger']['B'], 2)


if __name__ == '__main__':
    unittest.main()
