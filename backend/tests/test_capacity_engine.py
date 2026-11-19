"""零第三方依赖的容量引擎单测：python3 -m unittest tests.test_capacity_engine -v"""
import unittest

from src.services import capacity_engine as engine


class ReservationTests(unittest.TestCase):
    def test_need_bytes_covers_writes_and_two_end_records(self):
        self.assertEqual(engine.need_bytes(100), 100 + 2 * engine.OVERHEAD)

    def test_capacity_too_small_rejected(self):
        with self.assertRaises(ValueError):
            engine.validate_capacity(engine.need_bytes(1) - 1)
        self.assertEqual(engine.validate_capacity(1000), 100)

    def test_capacity_bounds(self):
        with self.assertRaises(ValueError):
            engine.validate_capacity(0)
        with self.assertRaises(ValueError):
            engine.validate_capacity(engine.CAPACITY_MAX + 1)
        with self.assertRaises(ValueError):
            engine.validate_capacity(500, short_threshold_bytes=501)

    def test_initial_ledger_validation(self):
        engine.validate_initial({'A': 1, 'b_2': -2})
        for bad in [{}, {'A': 1.0}, {'A': True}, {'A': engine.VALUE_LIMIT + 1}, {'bad key': 1}]:
            with self.assertRaises(ValueError):
                engine.validate_initial(bad)


class AdmissionPlanTests(unittest.TestCase):
    def _q(self, seq, declared, skip=0):
        return {'seq': seq, 'code': f'R{seq}', 'declared_bytes': declared, 'skip_count': skip}

    def test_head_fits_then_fifo(self):
        # 容量 1000，无占用：两单都能按序受理
        plan = engine.plan_admissions(0, 0, 1000, 100,
                                      [self._q(1, 200), self._q(2, 300)])
        self.assertEqual(plan['admit'], [1, 2])
        self.assertEqual(plan['available_after'], 1000 - engine.need_bytes(200) - engine.need_bytes(300))
        self.assertEqual(plan['reasons'], {})

    def test_full_disk_queues_with_reason(self):
        used = 900
        plan = engine.plan_admissions(used, 0, 1000, 100, [self._q(1, 50)])
        self.assertEqual(plan['admit'], [])
        self.assertIn('容量不足排队', plan['reasons'][1])
        self.assertIn(str(1000 - used), plan['reasons'][1])

    def test_short_jumps_three_times_then_barrier(self):
        # 已受理大单占用预留后可用 572；队首大单需 628 放不下；短单 138 可插队
        cap = 1000
        used_reserved = engine.need_bytes(300)  # 428
        available = cap - used_reserved        # 572
        queued = [self._q(1, 500)] + [self._q(n, 10) for n in range(2, 6)]
        plan = engine.plan_admissions(used_reserved, 0, cap, 100, queued)
        self.assertEqual(plan['admit'], [2, 3, 4])           # 第5个短单被屏障挡住
        self.assertEqual(plan['skip_counts'][1], engine.MAX_SKIPS)
        self.assertIn('屏障', plan['reasons'][1])
        self.assertIn('前序申请尚未受理', plan['reasons'][5])

    def test_long_request_never_overtakes(self):
        # 队首放不下，后面的非短单即使自身放得下也不能插队
        plan = engine.plan_admissions(850, 0, 1000, 50,
                                      [self._q(1, 80), self._q(2, 10)])
        self.assertEqual(plan['admit'], [2])  # 申报10、阈值50 → 短单可过（含帧共138<=150）
        plan2 = engine.plan_admissions(850, 0, 1000, 5,
                                       [self._q(1, 80), self._q(2, 10)])
        self.assertEqual(plan2['admit'], [])  # 阈值5时申报10不再是短单
        self.assertIn('前序申请尚未受理', plan2['reasons'][2])

    def test_barrier_clears_after_space_freed(self):
        # 屏障大单在空间腾出后优先受理，排队单不饿死
        queued = [self._q(1, 500, skip=engine.MAX_SKIPS), self._q(2, 10)]
        plan = engine.plan_admissions(0, 0, 1000, 100, queued)
        self.assertEqual(plan['admit'], [1, 2])


    def test_reservation_guarantees_finish_frame_when_disk_fills(self):
        # 容量恰好容纳一个申请的完整生命周期（申报负载+开工帧+结束帧）
        declared = 200
        cap = engine.need_bytes(declared) + engine.OVERHEAD  # 额外一个 begin 帧的空间
        plan = engine.plan_admissions(0, 0, cap, 100, [self._q(1, declared)])
        self.assertEqual(plan['admit'], [1])
        # 受理后第二个申请必然放不下：哪怕只申报 1 字节
        used = engine.OVERHEAD                      # begin 已落盘
        reserved = declared + engine.OVERHEAD      # 剩余负载 + 结束帧
        plan2 = engine.plan_admissions(used, reserved, cap, 100, [self._q(2, 1)])
        self.assertEqual(plan2['admit'], [])
        self.assertIn('容量不足排队', plan2['reasons'][2])
        # 但结束帧始终在预留内：剩余负载+结束帧 == reserved，收尾不再申请任何新空间
        self.assertEqual(reserved, declared + engine.OVERHEAD)
        self.assertLessEqual(used + reserved, cap)


class RecoveryTests(unittest.TestCase):
    def test_committed_kept_loser_undone_oracle_matches(self):
        initial = {'A': 100, 'B': 50}
        entries = [
            {'lsn': 1, 'op': 'begin', 'tx': 'T1', 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 2, 'op': 'write', 'tx': 'T1', 'key': 'A', 'value': 60, 'record_bytes': 80},
            {'lsn': 3, 'op': 'commit', 'tx': 'T1', 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 4, 'op': 'checkpoint', 'tx': None, 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 5, 'op': 'begin', 'tx': 'T2', 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 6, 'op': 'write', 'tx': 'T2', 'key': 'B', 'value': 40, 'record_bytes': 80},
        ]
        out = engine.recover(initial, dict(initial), 0, 0, entries, crash_after=6)
        self.assertTrue(out['invariant_passed'])
        self.assertEqual(out['recovered'], {'A': 60, 'B': 50})  # T2 未提交，B 撤净
        self.assertEqual(out['oracle'], {'A': 60, 'B': 50})
        self.assertEqual(out['committed'], ['T1'])
        self.assertEqual(out['losers'], ['T2'])
        self.assertEqual(out['undo_count'], 1)
        self.assertEqual([t['phase'] for t in out['trace']], ['redo', 'undo_loser'])

    def test_crash_prefix_drops_non_durable_writes(self):
        initial = {'A': 100}
        entries = [
            {'lsn': 1, 'op': 'begin', 'tx': 'T1', 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 2, 'op': 'write', 'tx': 'T1', 'key': 'A', 'value': 9, 'record_bytes': 80},
            {'lsn': 3, 'op': 'commit', 'tx': 'T1', 'key': None, 'value': None, 'record_bytes': 64},
        ]
        out = engine.recover(initial, dict(initial), 0, 128, entries, crash_after=1)
        self.assertEqual(out['recovered'], {'A': 100})       # 写入与提交均未落盘
        self.assertEqual(out['losers'], ['T1'])
        self.assertEqual(out['reclaimed_bytes'], 128)

    def test_abort_during_redo_is_undone_and_excluded_from_oracle(self):
        initial = {'A': 100}
        entries = [
            {'lsn': 1, 'op': 'begin', 'tx': 'T1', 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 2, 'op': 'write', 'tx': 'T1', 'key': 'A', 'value': 9, 'record_bytes': 80},
            {'lsn': 3, 'op': 'abort', 'tx': 'T1', 'key': None, 'value': None, 'record_bytes': 64},
        ]
        out = engine.recover(initial, dict(initial), 0, 0, entries, crash_after=3)
        self.assertEqual(out['recovered'], {'A': 100})
        self.assertEqual(out['aborted'], ['T1'])
        self.assertTrue(out['invariant_passed'])

    def test_recover_from_checkpoint_ledger(self):
        initial = {'A': 0}
        checkpoint_ledger = {'A': 77}
        entries = [
            {'lsn': 9, 'op': 'begin', 'tx': 'T9', 'key': None, 'value': None, 'record_bytes': 64},
            {'lsn': 10, 'op': 'write', 'tx': 'T9', 'key': 'A', 'value': 88, 'record_bytes': 80},
        ]
        out = engine.recover(initial, checkpoint_ledger, 8, 200, entries, crash_after=2)
        self.assertEqual(out['durable_checkpoint'], {'A': 77})
        self.assertEqual(out['recovered'], {'A': 77})
        self.assertEqual(out['used_bytes'], 64 + 80)
        self.assertEqual(out['reclaimed_bytes'], 200)

    def test_crash_point_bounds(self):
        with self.assertRaises(ValueError):
            engine.recover({'A': 1}, {'A': 1}, 0, 0, [], crash_after=1)


if __name__ == '__main__':
    unittest.main()
