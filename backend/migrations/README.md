# 初始化结构
SQLAlchemy metadata.create_all首次建users、log_sets、crash_cases、recoveries、audits，以及容量演练三表capacity_drills（容量/账本/检查点账本/恢复结果）、capacity_requests（申报/状态/排队原因/插队计数）、capacity_journal（持久日志帧与回收标记）。log_sets.name、crash_cases.name、capacity_drills.name唯一，关联使用外键，入队冻结日志和崩溃点快照。暂无在线schema升级器；新增表只影响首次建库，已有卷需 down -v 后重建。
