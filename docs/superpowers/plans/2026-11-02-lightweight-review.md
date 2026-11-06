# 轻量 AI 陪练 Implementation Plan

**Goal:** 对弈中使用独立快照复盘弹窗，终局自动生成最多三个关键时刻，并支持局面追问。

**Architecture:** 复用现有规则、复盘与教练 API。新增 reviewSummary 负责筛选与短解释；useReviewSession 管理不可变快照、请求序列和隔离问答；ReviewDialog 负责响应式弹窗；App 只连接入口和终局触发。

**Tech Stack:** Vue 3、TypeScript、Vitest、FastAPI、pytest。

**Spec:** docs/superpowers/specs/2026-11-02-lightweight-review-dialog-design.md

## Constraints

- 只分析 1–120 个半回合。复盘不写入主棋盘、棋谱或行棋方。
- 复用规则验证和引擎分析，不用 cp/mate 代替规则终局判断。
- 保留用户 App.vue 已有的 v-show 改动。不新增依赖、存档字段或迁移。

## Tasks

- [x] 1. 先写 reviewSummary.test.ts、useReviewSession.test.ts 和规则终局测试，验证筛选、mate 不伪造 cp、快照隔离、旧请求、问答局面和终局边界；运行 npm test -- 对应测试，确认缺少功能导致失败。
- [x] 2. 实现 reviewSummary.ts、useReviewSession.ts 与 xiangqi.ts 的 terminalStatus，运行同组测试确认通过。
- [x] 3. 新建 ReviewSummary.vue、ReviewDialog.vue，增加 App.vue 入口、自动终局检测、旧快照提示及独立聊天。保留现有复盘页，添加关键时刻区。响应式 CSS、焦点约束和 Escape/遮罩关闭。
- [x] 4. 复查所有交互：手动与自动触发、无走法、引擎不可用、超长、报错重试、关闭后继续对弈、变更棋局后的旧结果、持久化快照 409 降级。
- [x] 5. 运行 python -m pytest -q（apps/api）、npm test 与 npm run build（apps/web），检查 git diff --check，检查桌面/窄屏浏览器实际展示；更新本计划结果和 README 使用说明。

## 验证结果（2026-11-03）

- `cd apps/api; python -m pytest -q`：149 passed，34 条既有第三方库弃用警告，66.65 秒。
- `cd apps/web; npm test`：18 个测试文件、64 项测试通过。
- `cd apps/web; npm run build`：vue-tsc 与 Vite 构建通过。
- `git diff --check`：无空白错误（Windows 行尾提示不影响检查）。
- 浏览器使用实际 Pikafish 验证：对弈中按钮、加载与结果、推荐局面、AI 实际追问、关闭及 Escape、桌面 1280×900 与窄屏 390×844、手动与引擎落子将死后的自动摘要。截图保存在 docs/images/lightweight-review.png 和 lightweight-review-mobile.png。
- 独立代码审阅发现负 mate 已必败局面被误报为新增严重失误，已补回归测试并修正为 unknown；原有 mate 正负视角误判也已修正。
- 完整测试暴露的原有 auth 参数错误处理重复读 body 挂起，已改用 FastAPI 的异常 body 并补回归测试；原有日志测试改为比较状态码数值，避免依赖日志 handler 的字符串化顺序。

## 首版边界

- 一句话说明为引擎数据模板；更深入的原因解释由用户主动追问 AI。
- 大模型不可用时，小结与引擎推荐仍可查看。
- 关闭浏览器后弹窗及追问会话不保留。已同步的云端棋局沿用持久化复盘；云端棋谱已变化（409）则回退为当前冻结快照的临时复盘。
- 本功能不新增分段复盘界面；超过 120 个半回合时说明整局复盘上限。
