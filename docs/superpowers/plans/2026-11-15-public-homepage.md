# 发布版首页实施计划

**Goal:** 将已确认的首页、练习卖点与服务诊断设计落实到现有 Vue 单页。

**Architecture:** 复用 App 中的对局与存档逻辑，新增独立首页练习组件和服务状态弹窗；只调整展示与入口，不修改后端合同和数据库。

**Tech Stack:** Vue 3、TypeScript、Vitest、原生 dialog。

**Spec:** docs/superpowers/specs/2026-11-15-public-homepage-design.md

## 约束

- 保留当前工作区已有改动，在 codex/public-homepage 分支增量实施，不自动提交或部署。
- 只用既有五档引擎策略；云端大厅仍不允许悔棋，练习不计正式战绩。
- 后端 pytest 单进程；macOS 验证不能代表其他平台。

## 任务

- [x] 1. 在 App.test.ts 添加行为回归：登录后 startPractice('beginner') 仍进入普通练习、保留旧云端记录、忙碌时不切换；首页 SSR 不渲染棋盘与技术状态；首次载入保留大厅。
- [x] 2. 运行 `npm test -- src/App.test.ts`，确认新增测试因入口尚不存在而失败。
- [x] 3. 新增 HomePracticeHero.vue，`start` 事件只传五档策略之一；App.startPractice 通过现有 resetGame 先保存再切换；顶部导航和账号帮助菜单取代原页头；首页隐藏棋盘。
- [x] 4. 新增 ServiceStatusDialog.vue，原生 showModal、Escape/关闭、刷新事件，技术细节折叠；App 传入用户功能状态与诊断项。
- [x] 5. 调整 AiFriendView 范围说明与棋友挑战；增加未完成对局继续入口，移除挂载时自动进入对局。
- [x] 6. 添加响应式样式，运行前端全量测试、生产构建、后端大厅三组测试；浏览器实际检查首页、诊断与手机布局。
