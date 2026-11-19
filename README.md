# 海砾 · 采样账本 WAL 恢复演练
海砾计量数据保障组（8人）用可重放日志替代恢复演练时手工拼接的SQL片段和账本截图。

## 场景与模块
上游为事务日志样例，下游为值班复核人。原流程人工标记提交、表格算恢复余额、截图写结论；痛点是崩溃点不清、撤销顺序容易错、恢复证据缺失。模块为事务日志集 / 故障注入点 / 恢复队列 / 恢复证据，实体LogSet/CrashCase/Recovery贯穿全栈。新增**日志盘容量受理**模块（实体CapacityDrill/CapacityRequest/CapacityJournal）：页面可设日志容量，申请时申报写入上限，放不下的并发申请排队，短单有限插队、大单不饿死，静止检查点腾空间，崩溃后已提交值保住、未提交值撤净、排队申请继续办理。

**Python WAL教学模型，不注入真实PostgreSQL故障，不执行数据库物理恢复。** PostgreSQL真实保存业务输入、冻结快照、任务和结果，Redis实际用于worker互斥，后台Python实际演算恢复历史。

## 启动
```bash
cp .env.example .env
docker compose up -d --build
# http://localhost:18246
# http://localhost:19246/docs
docker compose exec -T backend python -m scripts.seed_demo
docker compose down --remove-orphans
```
SEED_DEMO=true时启动自动执行种子；自然键查重，不覆盖用户修改。初始化失败显式阻止启动，不隐藏结构错误。删除数据需显式down -v。

|账号|密码|权限|典型动作|
|---|---|---|---|
|admin@haili.local|Recovery2026!|读写/导出/审计|查询审计记录|
|operator@haili.local|Recovery2026!|新增日志/场景/运行/导出|设置断电点10|
|viewer@haili.local|Recovery2026!|只读/导出|核对恢复账本|

## 一天的复核剧本
09:00操作员登录；09:05查看海砾采样账本-晚班（A100、B50）；09:10复制日志集保存shift-20261117；09:15在第10条日志后注入断电点；09:20提交恢复；09:25核对检查点LSN4、已提交T3、未提交T2两条写入逆序撤销，最终A60/B50；09:30下载JSON；09:40观察员核对且写操作403；10:00管理员查看/api/audits。

## 算法、格式和失败态
日志为JSON数组，操作为begin/write/commit/abort/checkpoint；write包含tx/key/value，其他事务操作包含tx，checkpoint不带tx。键必须在初始整数账本存在。事务ID不可复用；严格写锁直到commit/abort释放，同键重叠活动事务拒绝；检查点仅在无活动事务时允许。最多200条日志/30键/整数绝对值不超过10亿。

crash_after=N表示前N条日志已持久化。最近静止检查点保存全部数据页，检查点后数据页假定均未写回（no-force）。恢复重放日志写入和已abort的撤销，再按LSN倒序撤销未结束事务。独立oracle从检查点账本仅应用已提交事务写入，结果须相同。输出重做/撤销轨迹、事务集合、各阶段账本、SHA256和模型版本。空输入、未知键、事务顺序非法、检查点有活动事务、写锁冲突、崩溃点超限均拒绝。模型不涉及页LSN、CLR、模糊检查点或真实磁盘故障；不是完整ARIES实现。

## 日志盘容量受理与排队（capacity-wal-quiescent-v1）
页面在“05 日志盘容量”设置容量（字节）与短单阈值（默认容量1/10）。每条日志帧固定开销64字节。申请提交时携带**申报写入上限**，受理按 `申报负载 + 开工帧 + 结束帧` 预留空间（`need_bytes`），因此开工后即使把申报额度写满，提交或撤销的结束记录也一定落盘——写满只拦新申请和新受理，不拦已开工事务收尾。超过申报额度的写入拒绝；申报上限超过盘容量的申请直接拒绝。

容量不足时申请进入持久队列表 `capacity_requests`，记录排队原因、剩余条数和被插队次数。受理泵规则：队首放得下按FIFO受理；放不下时仅其后的短单（申报≤阈值）可绕过队首，队首每被绕过一次计数+1，达到3次（MAX_SKIPS）成为**屏障**，本轮不再放行任何申请，直到事务结束或检查点腾出空间；非短单严格按到达顺序不得插队，故大单不会被无限插队饿死。

静止检查点仅在无活动（已开工未收尾）申请时允许：写一条checkpoint帧、冻结当前账本到 `checkpoint_ledger`，把检查点之前的日志帧标记回收并从used字节扣除，回收后受理泵立即继续办理队列。`used`（已落盘帧）与 `reserved`（各活动申请尚未落盘的剩余负载+结束帧）分离核算，同一字节不重复占用。

崩溃注入给定持久前缀 `crash_after`：其后日志视为未落盘并删除；从最近静止检查点账本重放持久前缀，已提交事务的值保留、未结束事务按LSN倒序撤净，独立oracle仅应用已提交写入做核对（invariant_passed）。崩溃时活动申请回到队列、未落盘写入清零，原排队申请保留；恢复完成后演练回到可受理状态，泵继续把排队申请办完。页面可核对排队原因、剩余条数、容量仪表与恢复账本（检查点值/重做后/恢复后/独立核对、SHA256），并导出整包JSON。容量1—100亿字节且至少容纳一条申报与两条记录帧（129字节），单演练日志上限500条，申请标识同演练内不可复用，写入遵守严格写锁。

## 工程与开发
前端原生HTML/CSS/JS+Nginx1.27；后端Python3.11+FastAPI+SQLAlchemy+PyJWT；PostgreSQL16和Redis7；5服务均healthcheck。持久任务队列在PG，单worker通过Redis锁互斥。20条待执行配额，审计记录写入操作，JWT8小时、PBKDF2随机盐密码。后端路由不含/api，Nginx/api/去前缀代理。

目录frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}与backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}。本地开发安装backend/requirements.txt并设DATABASE_URL/REDIS_URL/JWT_SECRET，再运行uvicorn src.main:app；前端需代理/api。migrations记录初始化结构，暂无在线升级器。容量模块的纯算法在src/services/capacity_engine.py（零第三方依赖），服务编排capacity_service.py；标准库单测 `python3 -m unittest discover -s backend/tests`，覆盖受理预留、短单插队与屏障、检查点回收、写满收尾、跨请求预留隔离、崩溃撤销与排队续办共26项。

环境COMPOSE_PROJECT_NAME控制命名，FRONTEND_PORT/BACKEND_PORT/DB_PORT为18246/19246/17746，DB_PASSWORD控制演示数据库密码，JWT_SECRET签名密钥，SEED_DEMO控制种子。命名卷db-data/redis-data/artifacts；共享artifacts预留，导出由冻结快照即时生成。Google Fonts需外网，业务离线可运行。默认凭据仅本地演示。

共享枚举roles与任务states定义于backend/src/constants/enums.py、frontend/src/constants/enums.js，状态使用models/entities.py/services/recovery_service.py/worker.py/components/common/status.js；日志操作类型在schemas/log_set.py和pages/logs.js中声明/说明。MIT许可。真实验证见批次test-artifacts/gb-4107/TESTING.md。
