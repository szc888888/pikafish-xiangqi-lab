# Pikafish Xiangqi Lab

Pikafish Xiangqi Lab 是一个面向中文用户的象棋对弈、分析和复盘工作台。前端提供棋盘交互，后端通过 UCI 协议调用 Pikafish；棋规校验由项目规则模块负责，引擎负责评估和给出建议。

> `start.ps1` 用于本机开发和体验，不是生产部署脚本。正式上线前请完成本文的生产配置，并按[账号、隐私与 PostgreSQL 备份运行手册](docs/operations/account-and-backup.md)执行部署检查。

## 项目特点

- **象棋规则优先**：棋盘、走法、将军与终局等规则在项目规则模块校验；引擎着法在执行前仍需校验，避免把引擎评估当作规则裁判。
- **多个对弈强度档位**：提供轻松陪练、入门练习、进阶对手、认真对弈、全力挑战五档。档位是体验预设，不代表经过校准的等级分；分析、提示和复盘仍使用完整引擎分析。
- **分析与复盘**：支持 MultiPV 候选着法、主变化、FEN 局面分析，以及逐半回合复盘；复盘棋谱最多 120 个半回合。
- **棋局数据持久化**：账号、棋局、走法记录、复盘结果和隐私同意记录可保存至数据库；支持数据导出、账号删除请求及删除恢复流程。
- **账号选择**：支持第三方 OIDC 登录；未配置 OIDC 时提供邮箱和密码注册/登录。首版默认不要求邮件验证，因此不依赖 SMTP。若启用邮箱验证和密码找回，需另配邮件服务。
- **可选 AI 教练**：未配置大语言模型也可使用引擎对弈、分析和复盘；配置 OpenAI 兼容服务后可进行连续教练问答、思路解释和棋盘图片识别。
- **备份工具**：提供 PostgreSQL 加密备份、Windows 每日计划任务和隔离数据库恢复脚本；备份密钥及删除账本需独立、安全保存。

## 技术栈

| 部分 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Vitest |
| API | Python 3.11+、FastAPI、Uvicorn、Pydantic |
| 数据存储 | SQLAlchemy、Alembic；生产环境使用 PostgreSQL，未设置数据库地址时本地开发默认 SQLite |
| 身份认证 | OIDC、Argon2 密码哈希、Cookie 会话 |
| 象棋引擎 | Pikafish UCI 与配套 NNUE 网络 |

## 环境准备

- Windows 开发环境：Python 3.11 或更新版本、Node.js/npm。
- PostgreSQL：本地开发可使用 SQLite；需要验证账号、棋局持久化或生产配置时，准备 PostgreSQL 数据库和专用数据库账号。
- Pikafish：从[官方 Releases](https://github.com/official-pikafish/Pikafish/releases)下载与运行平台匹配的程序及 NNUE 文件。引擎可选；不安装时棋盘和局面编辑仍可使用，但无法进行引擎分析。

## 本机开发

### 1. 配置环境变量

后端从项目根目录的 `.env` 读取环境变量。首次运行可创建该文件；不要提交真实密码、令牌或密钥：

```dotenv
# 可省略；省略时使用 apps/api/chess.db 本地 SQLite 数据库
# PostgreSQL 示例请替换账号、密码和主机：
# DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/chess

# 可选：仅在需要 AI 教练、思路解释或图片识别时配置
AGENT_OPENAI_BASE_URL=https://<openai-compatible-host>/v1
AGENT_OPENAI_API_KEY=<your-api-key>
AGENT_OPENAI_MODEL=<your-model-name>
```

本地会话密钥可设置为随机值，例如在 PowerShell 中生成：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将输出填入 `.env` 的 `SESSION_SECRET`。正式部署必须设置强随机会话密钥，不能使用开发默认值。

### 2. 安装后端依赖并初始化数据库

在 PowerShell 中：

```powershell
cd D:\chess\apps\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
```

如果使用 PostgreSQL，请先创建 `chess` 数据库，并在项目根目录 `.env` 设置正确的 `DATABASE_URL`，再执行迁移。当前 Alembic 最新迁移为 `0004_game_engine_settings`。不要在已有数据的数据库上使用会删除表的重置操作。

### 3. 准备 Pikafish（可选）

将官方发布包中的引擎程序及对应 `.nnue` 文件放在 `engine` 目录。Windows 默认查找 `engine/pikafish.exe`；也可以在 `.env` 指定路径：

```dotenv
PIKAFISH_PATH=D:\chess\engine\pikafish.exe
PIKAFISH_EVAL_FILE=D:\chess\engine\pikafish.nnue
```

可查看 [引擎目录说明](engine/README.md)。程序和 NNUE 必须来自相互兼容的版本。

### 4. 启动服务

推荐在项目根目录运行 Windows 一键开发启动脚本：

```powershell
cd D:\chess
.\start.ps1
```

该脚本启动或复用后端 `127.0.0.1:8000` 和 Vite 前端 `127.0.0.1:1239`，日志写入根目录 `logs/`。可先检查脚本解析出的路径和命令而不启动服务：

```powershell
.\start.ps1 -DryRun
```

也可以分别启动，便于调试：

```powershell
# 终端一：后端
cd D:\chess\apps\api
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 终端二：前端
cd D:\chess\apps\web
npm install
npm run dev
```

打开 <http://127.0.0.1:1239>。API 健康检查地址为 <http://127.0.0.1:8000/api/health>。

## 生产部署流程

仓库没有 Docker Compose、生产进程管理器或反向代理配置。下面是部署步骤和边界；需由部署环境提供 HTTPS、静态文件服务、进程守护和 PostgreSQL 运维。

1. **准备运行环境**：部署前端静态文件和 API 到受控主机；安装 Python 3.11+、Node.js 构建环境、PostgreSQL 客户端工具，以及与服务器平台匹配的 Pikafish 和 NNUE。
2. **准备 PostgreSQL**：创建独立数据库和权限受限的服务账号；配置防火墙、网络访问和定期维护。不要在公网暴露数据库端口。
3. **配置生产密钥与隐私信息**：通过服务管理器或密钥管理系统注入环境变量，不要将 `.env`、密钥或真实凭据放入版本库。生产模式要求以下配置齐全，否则 API 会拒绝启动：

   ```dotenv
   APP_ENV=production
   DATABASE_URL=postgresql+psycopg://<user>:<password>@<private-host>:5432/chess
   SESSION_SECRET=<至少 32 个字符的随机值>
   COOKIE_SECURE=1
   PUBLIC_BASE_URL=https://<your-domain>
   PRIVACY_POLICY_VERSION=v1.0
   PRIVACY_OPERATOR_NAME=<实际运营主体>
   PRIVACY_CONTACT_EMAIL=<隐私联系邮箱>
   PRIVACY_EFFECTIVE_DATE=<YYYY-MM-DD>
   PRIVACY_THIRD_PARTY_DISCLOSURE=<第三方服务、处理地点及数据说明>
   PRIVACY_BACKUP_STORAGE_DESCRIPTION=<备份位置及保留安排>
   PRIVACY_POLICY_APPROVED=1
   BACKUP_OUTPUT_DIR=<备份目录>
   DELETION_LEDGER_PATH=<独立保存的删除账本路径>
   BACKUP_ENCRYPTION_KEY=<32 字节随机密钥的 Base64>
   ```

   `PRIVACY_POLICY_APPROVED=1` 是运营方完成内容核实后设置的发布门槛，不代替法律审核。隐私页面会读取运营主体、联系邮箱和政策说明；部署前应核验页面展示内容与实际数据处理相符。

4. **运行数据库迁移**：在发布新版本前备份数据库，再从 `apps/api` 执行 `alembic upgrade head`。应用启动时会检查生产数据库的 Alembic 版本，不匹配则拒绝启动。
5. **构建前端并托管静态文件**：执行 `cd apps/web; npm install; npm run build`，将 `apps/web/dist` 发布到 HTTPS 站点。仓库当前未包含 npm lock 文件，因此这里使用 `npm install`。由 Nginx、Caddy 或云负载均衡将 `/api` 和 `/auth` 转发给仅监听内网的 Uvicorn API。设置正确的 Host、转发协议和 Cookie 安全属性。
6. **守护 API 进程**：在 `apps/api` 的 Python 环境中运行 `uvicorn app.main:app --host 127.0.0.1 --port 8000`，由 systemd、Windows 服务管理器或容器平台负责启动和守护；生产中不要使用 `--reload` 或 Vite 开发服务器。Uvicorn 应仅对反向代理开放，并配置进程重启策略、日志收集、资源限制和健康检查。
7. **验证发布与恢复流程**：检查 `/api/health`、注册/登录、棋局存取、引擎状态、隐私政策状态和 HTTPS Cookie；按[运行手册](docs/operations/account-and-backup.md)配置加密备份、计划任务及恢复演练。

OIDC 如需启用，另行配置 `OIDC_ISSUER`、`OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET` 和与身份提供商登记地址一致的 `OIDC_REDIRECT_URI`。邮箱密码注册/登录默认不要求验证邮件；启用 `EMAIL_VERIFICATION_REQUIRED=true` 后，必须配置 SMTP 邮件发送参数及 HTTPS `PUBLIC_BASE_URL`。

**发布注意事项：** 当前仓库提供的是应用代码与备份脚本，不包含可直接上线的完整基础设施配置。备份是每日全量方案；WAL/PITR、异地复制、告警、RPO/RTO 目标需要结合实际 PostgreSQL 服务单独配置并通过演练验证。尚未填入真实运营主体、隐私联系方式、第三方披露、密钥和备份存储配置前，不应把站点视为可正式运营。

## 常用测试

```powershell
# 后端测试
cd D:\chess\apps\api
.\.venv\Scripts\Activate.ps1
python -m pytest

# 前端测试与生产构建
cd D:\chess\apps\web
npm test
npm run build
```

## 相关文档

- [账号、隐私与 PostgreSQL 备份运行手册](docs/operations/account-and-backup.md)：生产配置、加密备份、计划任务和恢复演练。
- [Pikafish 引擎目录说明](engine/README.md)：引擎和 NNUE 安装方式。
- [项目研发规范](AGENTS.md)：象棋规则、棋盘坐标、存档及测试要求。
