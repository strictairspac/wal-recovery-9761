# 初始化结构
SQLAlchemy metadata.create_all首次建users、log_sets、crash_cases、recoveries、audits。log_sets.name、crash_cases.name唯一，关联使用外键，入队冻结日志和崩溃点快照。暂无在线schema升级器。
