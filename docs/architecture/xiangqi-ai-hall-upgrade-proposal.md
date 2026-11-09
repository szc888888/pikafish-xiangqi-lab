# 象棋大厅 AI 棋友平台技术改造方案

> 阶段：现状审查与方案设计（只读审查；本文档为交付物）
> 范围：第一阶段 20 个 AI 棋友；沿用现有 Vue、FastAPI、SQLAlchemy、象棋规则层与 Pikafish。
> 数据库：本次未连接或修改数据库，未执行迁移。

## 1. 结论

当前项目不是一个只有临时状态的单页 Demo：已经具备用户账号、云端和本地棋局存储、逐着棋谱、走棋规则验证、五档引擎强度、候选过滤、提示/悔棋事件、复盘和棋局恢复。第一阶段应在这些能力上增加“AI 棋友目录 + 对手匹配 + 带对手身份和赛果的对局”，不要另建一套棋局系统。

建议先把 20 个棋友定义为应用内静态目录配置；每个棋友是稳定的展示身份和玩法预设，映射到现有五档之一及受控的候选选择参数。对局保存稳定的 `opponent_id` 和创建时的配置快照。仍由现有 Pikafish UCI 进程提供搜索，棋友配置不代表 20 个引擎实例，也不应把身份描述成经过校准的 Elo。

当前单个 API worker 内的搜索是串行的：`PikafishEngine.analyze()` 用一个 `asyncio.Lock` 保护引擎 stdin/stdout 和搜索状态，因此多局可以共用一个进程但不能并行搜索。多 worker / 多 API 副本会各自创建一个全局引擎进程。`/api/engine/reset` 没有经过同一把锁，存在与分析交错的竞态，应在接入大厅请求前修正并验证。

## 2. 审查范围与项目结构

| 范围 | 当前真实文件 | 现状 |
| --- | --- | --- |
| 仓库规范与说明 | `AGENTS.md`、`README.md` | 规则优先；README 说明当前产品、部署、账号和数据生命周期。 |
| 前端入口/主页面 | `apps/web/src/main.ts`、`apps/web/src/App.vue` | Vue 3 单一应用入口；主要状态、功能 Tab 和工作流集中在 `App.vue`。默认进入“对弈”。 |
| 前端棋盘/棋局历史 | `apps/web/src/components/BoardView.vue`、`apps/web/src/components/GamesView.vue` | 棋盘交互组件；历史列表支持继续、重开、删除，没有大厅或棋友目录页面。 |
| 其他前端业务 | `apps/web/src/components/AnalysisView.vue`、`ReviewView.vue`、`CoachView.vue`、`SetupControls.vue`、`EngineSettings.vue` | 分析、复盘、教练、摆棋、引擎参数组件。 |
| 前端规则/API | `apps/web/src/lib/xiangqi.ts`、`api.ts`、`engineStrength.ts`、`gameEvents.ts` | 前端规则镜像、HTTP API、五档设置规范化和对局事件。 |
| API 入口与业务路由 | `apps/api/app/main.py` | FastAPI 生命周期、引擎端点、账号、棋局创建/导入/读取/追加着法/删除、复盘和图片识别。 |
| 引擎 | `apps/api/app/engine.py`、`apps/api/app/engine_strength.py` | UCI 子进程生命周期、搜索、候选合法性过滤、五档配置和确定性选择。 |
| 规则层 | `apps/api/app/xiangqi.py` | 后端合法着法、历史、终局、长将/长捉及棋谱描述；应继续作为后端规则真源。 |
| API/持久化模型 | `apps/api/app/models.py`、`apps/api/app/persistence.py` | Pydantic 请求响应模型；SQLAlchemy 用户、游戏、走法、复盘、事件等表模型。 |
| 数据库与迁移 | `apps/api/app/database.py`、`apps/api/alembic/versions/0001_persistent_data.py` 至 `0006_game_events.py` | 开发可 SQLite，生产推荐 PostgreSQL；Alembic 当前最新为 `0006_game_events`。 |
| 引擎部署 | `engine/README.md`、`scripts/install-engine.ps1`、`start-docker.ps1`、`compose.yaml` | Pikafish/NNUE 按平台安装；Compose 中 Pikafish 由 API 容器启动，不是单独服务。 |
| 相关测试 | `apps/api/tests/test_engine.py`、`test_engine_strength.py`、`test_persistence_api.py`、`test_xiangqi.py`；`apps/web/src/lib/*.test.ts` | 已覆盖引擎参数/过滤/超时、强度选择、持久化接口、规则和前端行为；未发现大厅匹配、机器人对局元数据、reset 并发覆盖。 |

前端 `package.json` 没有 Vue Router 等路由依赖；目前是 `App.vue` 内部 Tab，不应在第一阶段仅为一个大厅页面引入新路由框架。是否未来需要可分享 URL 的大厅/对局路由，属于待确认的产品决定。

## 3. 现状审查

### 3.1 引擎调用与五档棋力

- `main.py` 创建模块级单例 `engine = PikafishEngine()`；应用 lifespan 启动时尝试启动，退出时停止。
- `engine.py` 用 `asyncio.create_subprocess_exec` 启动一个 Pikafish 子进程，通过 UCI stdin/stdout 通信。`analyze()` 在锁内设置 `Threads`、`Hash`、`MultiPV`、position、等待 `readyok` 并搜索。日志记录版本、NNUE 哈希、耗时和失败阶段。
- 搜索有超时：读取行使用 `PIKAFISH_TIMEOUT_SECONDS`，搜索时间上限会考虑 movetime；超时后发 `stop` 并等待 `bestmove`，恢复失败则停止进程。启动握手错误会记录并停止进程。
- 每个候选着法均由 `validate_candidate()` 进行本地规则校验；无合法候选会报错。Pikafish 是分析建议来源，不是规则裁判。
- `engine_strength.py` 目前提供 companion/beginner/progress/serious/full 五个预设，控制 depth、movetime、Threads、Hash、候选上限、cp 损失阈值和是否允许弱着。`select_candidate()` 对合法候选进行确定性随机选择，seed 为 `game_id:ply`。这是应用层棋力调节，不是 Pikafish 内置等级。
- 已审查代码只发送 `Threads`、`Hash`、`MultiPV`、`EvalFile` 等配置；本方案不使用 `Skill Level` 或 `UCI_Elo`。`Threads` 等 option 的目标版本兼容性仍应由引擎实测验证。
- timeout 对搜索有恢复处理；`start()` 与 `reset()` 没有与 `analyze()` 共用同一把生命周期锁。尤其 `/api/engine/reset` 在搜索中执行时可能杀掉正在使用的进程。当前支持几套进程取决于 API worker/副本数，而不是每个用户或每个棋友。

### 3.2 对局、规则、存储和恢复

- 创建：`POST /api/games` 创建 `Game`，保存起始 FEN、初始当前 FEN、红方行棋标志、状态、引擎设置和 hint/undo events。
- 走棋：`POST /api/games/{id}/moves` 校验 `expected_version`，从 `initial_fen + GameMove.uci[]` 重放规则历史、检查投影一致性和合法着法，再以版本条件更新 Game 并新增 GameMove。当前接口将棋局写入和客户端单独请求的引擎应手分开；不存在一个服务端原子操作涵盖“用户着法 + 机器人应手”的大厅流程。
- AI 应手：`POST /api/engine/move` 校验完整历史，调用共享 Pikafish，再用 profile 选择候选并返回着法；之后仍由前端发起棋局着法追加。建议大厅对局改为服务端编排，并把用户着法和 AI 应手按受控步骤分别验证、持久化，避免客户端中断导致半个回合；一个事务内完成数据提交，搜索期间不要长时间持有数据库事务/行锁。
- 状态：现有 `Game.status` 是 active/finished/deleted 投影；终局从规则层计算。没有保存 winner/result、结束原因、游戏模式或机器人身份。不要用引擎 cp/mate 推导胜负。
- 棋谱：`GameMove` 保存 ply、side、UCI、中文着法、前后 FEN；读写时检查能否从起始 FEN 重建。数据库游戏使用乐观版本冲突检查，前端保留 localStorage 存档并可登录后导入。
- 恢复：`GET /api/games`、`GET /api/games/{id}` 返回保存游戏；`GamesView.vue` 可以继续或重开。列表是通用历史游戏页，没有按机器人筛选或机器人战绩。

### 3.3 用户与页面

- 已有 `User`、登录身份和本地凭据，`GET /api/me` 可识别当前账号；用户模型目前没有 rating、胜平负统计等字段。
- 游戏按 `user_id` 隔离并有隐私同意、导出和删除生命周期。历史记录可存数据库或游客 localStorage；不能只新增机器人字段到前端本地状态，否则账号跨设备恢复及战绩统计不可靠。
- 当前 UI 的“对弈”Tab 是首页，“棋局”Tab 是记录页。推荐在现有主视图体系里增加“棋友”入口/选择页，用户选中棋友后进入现有棋盘对局；“棋局”页增加机器人、结果和筛选信息。
- `App.vue` 承载大量状态和流程，是新增大厅业务最可能触及的复杂文件。实施时应按当前组件/`lib` 模式把棋友目录 API、匹配逻辑和大厅界面拆为独立新增模块，不先做无关重构。

## 4. 机器人配置与引擎共享设计

### 推荐：静态目录 + 共享引擎 + 每局快照

新增 `apps/api/app/ai_friends.json`（待新增）作为 20 个机器人定义的静态目录，API 响应提供稳定 id、名称、头像或图标资源键、简介/风格标签、展示排序、匹配标签和强度预设键。将显示文案/资源与可执行的 strength profile 分开；客户端不得提交任意 depth、Threads、Hash 或候选阈值覆盖机器人策略。

在现有五档之上，新增受边界约束的 bot profile 配置（可先放 `engine_strength.py`，规模变大再独立到待新增 `ai_friend_profiles.py`）：例如 `profile_key` 引用、允许候选范围/损失上限、是否允许次优、思考时间微调。不要给 20 个机器人各自无约束的参数副本。第一批每个 profile 应用规则有可解释的选择，不承诺机器人的胜率/Elo；如需要“实力分”，先基于实测数据设计与校准。

创建棋局时 API 根据 `opponent_id` 查服务端目录，校验有效后将 `opponent_id`、`opponent_config_version` 和关键玩法参数快照写入 Game。历史棋局继续使用快照，目录未来改名/改强度不改变旧记录含义。静态目录无需新增 `AiFriend` 数据表，也无需在数据库迁移时复制 20 条种子数据；只有需要运营后台动态增删/发布机器人时，才另行评估数据库 `AiFriend` 模型和配置版本管理。

### 共享 Pikafish 的请求路径

20 个机器人只是 20 份身份和策略配置，不是 20 个引擎进程。每个 API worker 中使用一份既有 `PikafishEngine` 单例；所有对弈/提示/分析请求通过同一引擎队列/锁完成 `setoption -> position -> isready -> go -> bestmove`。候选合法过滤继续复用 `xiangqi.py`。

第一阶段推荐明确部署为一个 API worker（或接受每 worker 一引擎并限制 worker 数），并为引擎请求设最大等待时间、队列容量、负载错误响应与日志指标。当前 `asyncio.Lock` 可避免同一个进程中的 UCI 命令互相污染，但它不是跨进程锁。若未来必须多 worker/多副本且全服务严格只保留一套引擎，应把引擎所有权移至独立的本地 engine broker/进程，通过内部请求队列串行调用；此为后续架构选项，不建议为第一阶段引入消息队列或新框架。并行搜索进程池则需按 CPU/RAM 明确资源预算，不能把它描述成单引擎并发。

## 5. 数据模型/API 建议

数据库目前没有机器人目录和用户战绩。建议沿现有 `Game`/`GameMove` 扩展，而不是另造一张平行的对局历史表。

| 建议模型/字段 | 位置 | 用途 |
| --- | --- | --- |
| `AiFriend`（第一阶段不建 SQL 表） | 待新增 `apps/api/app/ai_friends.json`；目录读取/校验逻辑可放待新增 `apps/api/app/ai_friends.py` | 20 个稳定机器人 id 与展示信息/玩法 profile 映射；静态配置版本随应用发布。 |
| `Game.opponent_id`、`opponent_config_version`、`opponent_snapshot` | 修改 `apps/api/app/persistence.py`；迁移待新增 `apps/api/alembic/versions/0007_ai_friend_games.py` | 对手关联与历史配置快照；旧游戏字段 nullable，兼容旧存档。 |
| `Game.mode`、`result`、`termination_reason`、`finished_at`（具体字段按赛果定义核准） | 同上 | 区分人机/手动/其他模式；记录红胜/黑胜/和棋及规则终局原因。结果只由规则/用户认输等明确定义产生。 |
| Pydantic `AiFriendSummary`、带 opponent 的 create/response、`MatchRequest`、`ResignRequest`（若支持认输） | 修改 `apps/api/app/models.py` | API 字段约束、向后兼容 defaults 和具体错误。 |
| `UserGameStats`（首期不持久化） | 待新增 `apps/api/app/game_stats.py` | 从该用户已结束棋局按结果聚合胜/平/负、总局数和最近对局；避免冗余缓存与删除/更正一致性问题。达到性能门槛后再做缓存表。 |
| `GameMove` | 复用现有模型 | 保留每一着 AI/用户走法和完整重建信息。若需要归属角色，当前 side 已能与该局的用户执棋方/机器人执棋方对应；AI 决策元数据可先作为游戏配置/可选 event，不存引擎整段日志。 |

建议增加/扩展 API：`GET /api/ai-friends` 返回机器人目录；`POST /api/matches` 根据智能匹配或随机挑战策略选一个机器人并创建对局；保留现有 `POST /api/games` 以兼容旧棋局及非大厅模式。大厅走棋可新增 `POST /api/games/{id}/turns` 接收用户着法和 `expected_version`，服务端完成规则校验、用户着法持久化、必要时请求引擎、验证 AI 着法、追加 AI 着法并返回新版本/局面。内部引擎搜索与数据库事务分开，失败时定义为仅用户着法已保存且棋局等待重试/恢复，或先计算再短事务提交；必须选定单一、可恢复语义并测试。现有 `/api/engine/move` 继续为无持久化/分析类调用服务，避免直接破坏五档 API。

战绩可以从结束的 Game 聚合，需索引 `games(user_id, status, updated_at)` 或与产品查询相匹配的字段组合。每条历史记录展示 `opponent_id`、快照显示名、模式、开始/结束时间、赛果和终局原因。保留通用 `games` 端点、旧格式导入和 localStorage 兼容；迁移时旧记录机器人字段为空，不能默认伪造一个机器人身份或赛果。

## 6. 匹配规则建议

- **智能匹配**：第一阶段可依据用户选择的目标体验（休闲/练习/挑战）或已有可解释的近期战绩区间，从 20 个可用 bot profile 中筛选；再从候选中选择最近未交手/低重复的机器人。当前没有用户棋力评级数据，所以不能假定能提供准确“实力相当”。建议首版称为“推荐棋友”，输入只用显式选择的目标档或已有对局胜率区间；胜率样本不足时退化为随机并说明策略。
- **随机挑战**：服务端从启用机器人中用安全随机选择；可排除最近 N 局重复对象（N 是待定产品参数）。选中结果、目录版本和 profile 快照写进 Game，确保重试/恢复不换人。
- 两种方式均由服务端决策并校验 `opponent_id`，避免客户端篡改机器人参数。是否在第一阶段需要过滤已挑战、胜率推荐、分组标签，待产品确认。
- 统计样本仅纳入明确已结束的正式对局；本地摆棋、分析、复盘、重开副本和未完成局不能混入战绩。是否将认输/超时/断线计为赛果尚待产品定义。

## 7. 具体文件改造清单

### 需要修改的现有文件

| 文件 | 改造理由/建议 |
| --- | --- |
| `apps/api/app/persistence.py` | 在 `Game` 上增加可空对手身份/快照、模式、结果、结束原因等兼容字段；若运行时动态外键指向静态 JSON，不能建普通 SQL 外键。 |
| `apps/api/app/models.py` | 增加棋友目录、匹配、扩展创建/响应、正式对局回合请求和统计响应模型。 |
| `apps/api/app/main.py` | 增加目录/匹配/统计/大厅回合端点；修改 `_game_response`、Game create/import/append 以及导出流程，保持规则重放和用户隔离。当前文件已承担多业务，新增大厅端点宜委派给待新增 `game_hall.py` 的纯业务函数/路由模块。 |
| `apps/api/app/engine.py` | 修复 reset/start/stop 与 analyze 之间的生命周期竞态；增加有界排队/等待和取消恢复语义。 |
| `apps/api/app/engine_strength.py` | 暴露经过服务端校验的机器人策略 profile 映射，保持既有五个 key 和行为不变；不使用 UCI_Elo/Skill Level。 |
| `apps/api/app/settings.py` | 只有在目录路径/版本需要运行配置时才修改；静态随包 JSON 时无需改。 |
| `apps/api/alembic/versions/0006_game_events.py` | 不应回改已发布迁移；保持原文件不变。新增迁移以其为 down_revision。 |
| `apps/web/src/lib/api.ts` | 增加目录、匹配、统计和大厅 turn API 类型/调用。 |
| `apps/web/src/App.vue` | 集成棋友选择/匹配状态、开始新大厅对局和赛果状态；保持既有分析、复盘、教练、摆棋流程。建议适度委托给新组件。 |
| `apps/web/src/components/GamesView.vue` | 历史列表增加棋友、赛果和大厅筛选/显示，旧记录采用兼容展示。 |
| `apps/web/src/styles.css` | 沿用现有样式系统，增加大厅导航与棋友列表布局，不额外引入 UI 框架。 |
| `apps/web/src/lib/engineStrength.ts` | 如前端需要展示已有 strength profile，可扩展展示类型/映射；服务端仍是策略裁决方。现有五档 localStorage 兼容不可改变。 |
| `apps/web/src/lib/api.test.ts` 或待新增大厅测试文件 | 验证新端点 request/response、错误响应及超时行为。 |

### 明确待新增文件

| 文件 | 职责 |
| --- | --- |
| `apps/api/app/ai_friends.json` | 20 个机器人目录数据和配置版本；记录 profile key，不含任意客户端可控引擎参数。 |
| `apps/api/app/ai_friends.py` | 目录载入、唯一 id/引用校验、随机/推荐选择；是否需要独立模块可在实现时按规模决定。 |
| `apps/api/app/game_hall.py` | 大厅流程编排/服务逻辑，避免继续膨胀 `main.py`；是否作为独立 router 取决于当前 FastAPI 路由组织。 |
| `apps/web/src/components/AiFriendView.vue` | 棋友列表、智能推荐、随机挑战和选择状态。 |
| `apps/web/src/components/AiFriendCard.vue` | 机器人名片单元（若页面复杂度值得拆分）。 |
| `apps/web/src/lib/aiFriends.ts` | 前端目录类型/筛选呈现逻辑；不要在前端复制服务端权威匹配规则。 |
| `apps/api/alembic/versions/0007_ai_friend_games.py` | 新增迁移，添加 nullable 游戏字段和必要索引；只在方案获批并验证旧数据迁移后执行。 |
| `apps/api/tests/test_ai_friends.py` | 目录唯一性、profile 映射、随机/推荐边界、无效 id。 |
| `apps/api/tests/test_game_hall_api.py` | 认证、匹配/建局、用户着法+AI 应手、赛果、错误回滚/恢复和旧记录兼容。 |
| `apps/api/tests/test_engine_concurrency.py` | 同 worker 搜索串行、reset 与分析互斥、超时/取消后下一个请求可用；必要时用假 UCI 进程测试。 |
| `apps/web/src/components/AiFriendView.test.ts`（或项目已有 Vitest 约定） | 检查匹配选择、加载/空/失败状态、响应式棋友列表与导航。 |

具体迁移编号需再次确认生产数据库实际版本；README 记载当前 `0006_game_events`，但本次没有连接数据库验证实际部署状态。

## 8. 原五档能力兼容

1. 保留 `companion`、`beginner`、`progress`、`serious`、`full` 的请求 key、profile 数值、候选过滤规则和前端设置规范化，不把 bot id 当 difficulty。
2. 老棋局 `engine_settings` 继续由 `_normalized_engine_settings()` 和 `normalizeSavedEngineSettings()` 处理；新增 opponent 字段 nullable/有默认值，仅大厅新局必填。
3. 棋友 profile 通过服务端映射到既有 profile，并在必要时从候选 rank/损失阈值做小幅差异；五档控制、提示/分析/复盘的现有路径保持原语义。
4. API 响应增加字段但不删除现有字段；棋谱导入、游客迁移、用户数据导出/删除和历史加载均纳入迁移测试。
5. 新增回归测试确认同五档、同局面、同 seed 仍得到同一候选行为；如 intentionally 引入 profile 变化，机器人大厅路径单独标识，不覆盖既有五档 API。

## 9. 并发、可靠性与待验证项

**已确认风险**

- `asyncio.Lock` 只在单个 Python 进程有效；多个 Uvicorn worker/容器会多启引擎。`compose.yaml` 目前启动一个 Uvicorn 命令但带 `--reload`（开发配置），生产部署说明则直接运行一个 worker；真实生产 worker 数待运维配置确认。
- 单进程引擎搜索被完全串行化。用户等待时长受前序分析、复盘、提示和深度配置影响；20 个棋友增加的是逻辑选择数，不增加吞吐。
- reset 不走分析锁，需修正；`start()` 也没有独立启动锁，不应依赖多个并发请求触发安全启动。
- 目前用户 `engine_move` 与保存 `append_move` 分属 API 请求。大厅回合中搜索成功后客户端断线或数据库写入冲突时，必须设计幂等 turn id/版本检查与恢复行为。
- 调用端可请求的 threads/hash/time 需设总资源预算；五档 full 当前允许较大的单次资源占用。应结合服务器 CPU、内存和同时活跃用户确定队列与参数上限。

**待验证（不能从仓库源码单独确认）**

- 生产部署实际 Uvicorn worker/副本数、主机 CPU/RAM、目标并发对局量和可接受等待时间。
- Pikafish 实际发布版本对 `Threads`、`Hash`、`MultiPV`、`EvalFile` 的 option 清单/取值行为；不要假定未从引擎握手 option 列表验证的参数均受支持。
- 生产数据库真实 Alembic 版本、规模、索引情况和备份/迁移窗口；本次没有访问数据库。
- 首期智能匹配的“棋力相近”目标如何定义，以及有没有足够用户对局样本。当前无 Elo/评级数据，不能宣称匹配等强。
- 机器人头像/文案/性格、是否允许认输、和棋/超时/断线判负等产品赛果定义。
- 对局端点是否允许游客对战机器人，或必须先登录并接受隐私条款。当前持久化游戏端点要求 consented user；匿名正式局的生命周期尚无现成业务定义。

## 10. 开发顺序、验证和风险

| 阶段 | 工作 | 验证门槛 |
| --- | --- | --- |
| 0. 上线事实确认 | 查清部署 worker/副本、引擎版本与资源预算、产品赛果和访客规则。 | 有可接受的每局等待目标；确定首期只运行单 worker，或明确接受每 worker 独立引擎。 |
| 1. 引擎生命周期 | 为 start/reset/stop/search 建立一致的互斥和可取消恢复策略；增加等待上限/队列背压指标。 | 假 UCI 进程验证并发交错、reset、超时后恢复；现有 `test_engine.py` 通过。 |
| 2. 规则与档案 | 创建 20 个稳定棋友目录，profile 只引用允许的配置；明确每局结果的规则依据。 | id/profile 唯一；每个档位均覆盖正常/非法/边界策略；所有实际 AI 着法经过现有规则和长将/长捉校验。 |
| 3. 持久化兼容 | 定义 nullable metadata/result 字段和迁移；扩展 create/response/导出/导入。 | 空字段旧游戏读写不变；已结束赛果可重建/校验；迁移升级、备份恢复演练后再应用生产。 |
| 4. 大厅 API | 目录、推荐/随机匹配、正式对局回合服务端编排、赛果与统计。 | 两客户端同版本冲突、重复提交幂等、引擎失败/服务重启恢复、用户隔离、非用户对象访问、赛果规则测试通过。 |
| 5. 前端体验 | 新增棋友选择视图/匹配入口，复用现棋盘与历史组件。 | 加载/空/错误/断网状态；20 个条目窄屏可用；旧棋局恢复、五档设置与游客迁移回归。 |
| 6. 完整发布验证 | 后端相关测试、前端测试、生产构建和数据库迁移检查。 | 执行并报告 `pytest`（相关后端套件）、`npm test`、`npm run build`；在隔离测试库验证迁移和回滚策略，不对开发/生产库直接试迁移。 |

主要风险按优先级：引擎生命周期竞态可能中断搜索；单实例排队导致等待过长；多 worker 造成引擎数量和 CPU/RAM 随部署倍增；客户端分步提交造成游戏半回合/重复提交；结果/评级语义不清导致错误战绩；迁移或导出遗漏使历史记录无法恢复。按上述顺序先解并发和持久化语义，再做大厅 UI。

## 11. 本次未做的事情

未修改任何 Python、TypeScript、Vue、SQL、迁移或部署文件；未执行数据库迁移；未连接数据库或运行开发服务。仓库审查时发现未跟踪的 `test_suite.db`，本次未读取或修改它。

本方案提交评审后，下一阶段再根据确认的游客策略、赛果规则、匹配口径和部署并发目标编写实现计划；未经确认不执行数据库迁移或进入编码。
