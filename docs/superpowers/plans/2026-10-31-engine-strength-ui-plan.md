# Pikafish 棋力档位完善实施计划

**目标：** 实现一套行为一致、可恢复、对不同 CPU 设备兼容的 Pikafish 对弈档位；档位选择不得绕过项目象棋规则。

**范围：** 只完善 Pikafish。固定五档的搜索参数由服务端预设；高级面板可查看固定档位参数，但只能在自定义档位编辑。云端棋局保存对手档位和自定义搜索参数。提示速度继续作为本地偏好。档位属于启发式体验设置，不宣传 Elo。

**规格：** `docs/superpowers/specs/2026-10-31-engine-strength-design.md`

## 设计决策

- 服务端对固定档位按可用 CPU 数降级线程数；自定义档位按主机 CPU 数拒绝越界配置并返回具体错误。
- 有评估值时只在最大 rank 和 cp/mate 损失预算内确定性抽选。任何可比较评估值缺失时不允许抽选该候选；若 rank 1 缺少分值或没有可用候选，回退到引擎返回的最佳合法候选。
- Pydantic 存档设置结构限制难度、深度、时间、线程和 Hash 范围。`games.engine_settings` 使用 nullable JSON 迁移；旧记录与无设置旧客户端兼容为“进阶对手”。
- 新建云端棋局时保存设置；每次追加走法时原子更新走法和当前引擎设置。读取云端存档恢复设置。既有棋谱和走法版本机制不变。
- `EngineMoveResponse.bestmove/score/pv` 描述实际选中的应手，`lines` 仍列出经规则过滤的候选及原引擎 rank，`selected_rank` 明确标识执行的候选。自动应手不写入分析视图，避免把选择档位结果误显示为完整分析结果。

## 实施任务

### 1. 档位策略边界（TDD）

涉及：`apps/api/app/engine_strength.py`、`apps/api/tests/test_engine_strength.py`

- [x] 现有五档、固定 seed、分值损失过滤和全力档测试。
- [x] 增加候选无分值不可抽中、最佳/全部候选无分值回退 rank 1、mate 正负分值方向测试；策略实现通过。
- [x] 固定档位按 `available_threads` 适配线程，覆盖 1/2/4 核。

### 2. 应手接口与 API 合同（TDD）

涉及：`apps/api/app/models.py`、`apps/api/app/main.py`、`apps/api/tests/test_engine_strength.py`

- [x] 现有接口基本档位及非法棋谱历史测试。
- [x] 覆盖自定义深度/时间/线程/Hash 透传、固定档位线程降级、自定义线程超限错误和 rank 1 无分值回退。
- [x] 服务端 CPU 数作为最终线程上限；固定档位自动降级，自定义越界返回参数错误。
- [x] 对弈候选仍经共享规则层校验；分析、提示、复盘调用合同保持不变。
- [x] 同一棋局 ID 和 ply 得到可复现候选；响应的 `bestmove/score/pv` 描述实际应手，`selected_rank` 表示其原候选序号。

### 3. 云端棋局设置存储及兼容（TDD）

涉及：`apps/api/app/persistence.py`、新增 Alembic migration、`apps/api/app/models.py`、`apps/api/app/main.py`、`apps/api/tests/test_persistence_api.py`、`apps/web/src/lib/api.ts`、`apps/web/src/App.vue`

- [x] 覆盖创建、走子更新、读取设置，旧请求默认进阶档、旧空字段读取默认值、固定档位规范化及非法设置 422。
- [x] 增加 nullable `engine_settings` JSON 列和 Alembic 迁移；既有行不回填虚构设置。
- [x] 创建和走子请求/响应使用有范围限制的设置模型；省略设置的旧请求兼容。
- [x] 前端本地/云端存档保存档位和自定义参数；旧云端记录默认进阶档。
- [x] 现有棋谱重建、合法着法校验和乐观版本冲突测试通过。

### 4. 界面一致性及旧设置迁移（TDD）

涉及：`apps/web/src/App.vue`、`apps/web/src/components/EngineSettings.vue`、`apps/web/src/lib/api.ts`、新增 `apps/web/src/lib/engineStrength.test.ts` 和 API 测试

- [x] 新增设置迁移与 API 传输测试；固定档位控件禁用、自定义可编辑由组件属性控制，并通过生产 TypeScript 构建验证。
- [x] 固定档位显示只读预设，自定义参数可编辑；线程输入读取 `hardwareConcurrency`。
- [x] 旧本地 `regular`/`elite` 映射至新档位；缺档位使用进阶对手默认值，兼容旧数值字段。
- [x] 对弈应手不覆盖完整分析结果；提示、分析和复盘继续使用既有分析路径。

### 5. 文档与交付验证

涉及：`README.md`、运行手册及本计划

- [x] README 说明启发式档位、固定/自定义参数行为及云端设置保留规则。
- [x] 后端全量测试：`D:\Python\Python312\python.exe -m pytest -q`，128 passed。
- [x] 前端全量测试：`npm test`，14 个测试文件、52 passed；生产构建：`npm run build` 成功。
- [x] 一次性 SQLite 数据库执行 `alembic upgrade head`，到达 `0004_game_engine_settings`，并确认新列可空；API 测试覆盖 null 旧值序列化。
- [x] 重启 API；`/api/health` 返回就绪，Web 返回 HTTP 200，OpenAPI 包含 `/api/engine/move`；使用初始局面完成一次进阶档应手请求，返回合法候选 `b2e2`。
- [x] 棋规回归与错误输入测试包含在 127 项后端测试及 51 项前端测试中；本次未连接真实 PostgreSQL。

## 验证记录

- 后端：128 passed，26 warnings（第三方依赖弃用提示）。
- 前端：14 test files / 52 tests passed。
- 前端生产构建：`vue-tsc --noEmit && vite build` 成功。
- Alembic：临时 SQLite 从空库升级到 `0004_game_engine_settings`，`games.engine_settings` 为 nullable JSON。
- 服务：重启后 API 健康、引擎就绪；Web HTTP 200；应手路由已注册，并从初始局面实际返回一次合法进阶档应手。

## 项目约束

- 不创建第二套象棋合法性判断；着法安全依赖现有 `validate_history` / `validate_candidate` 路径。
- 未验证的数据或无分值候选不能被当作可靠评估结果。
- 不改动用户现有 `.env`、数据库密钥或历史棋谱。
- 不提交本地 SQLite 测试数据库、构建缓存或运行日志。
