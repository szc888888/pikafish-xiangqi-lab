# 账号、隐私与 PostgreSQL 备份运行手册

## 部署前配置

在服务进程环境中配置以下变量，勿将真实值提交到仓库：

```text
APP_ENV=production
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/chess
EMAIL_VERIFICATION_REQUIRED=false
SESSION_SECRET=<至少 32 个随机字符>
COOKIE_SECURE=1
PRIVACY_POLICY_VERSION=v1.0
PRIVACY_OPERATOR_NAME=<实际运营主体>
PRIVACY_CONTACT_EMAIL=<实际隐私联系邮箱>
PRIVACY_EFFECTIVE_DATE=<YYYY-MM-DD>
PRIVACY_THIRD_PARTY_DISCLOSURE=<真实的身份/模型服务提供方、处理地点和保留说明>
PRIVACY_BACKUP_STORAGE_DESCRIPTION=<备份存储地点与保留安排的公开说明>
PRIVACY_POLICY_APPROVED=1
# 仅在 EMAIL_VERIFICATION_REQUIRED=true 时需要以下邮件配置
MAIL_HOST=<SMTP 主机>
MAIL_PORT=587
MAIL_FROM=<发件地址>
MAIL_USERNAME=<SMTP 用户名>
MAIL_PASSWORD=<SMTP 凭据>
MAIL_TLS_MODE=starttls
PUBLIC_BASE_URL=https://<your-domain>
BACKUP_OUTPUT_DIR=<异机挂载的备份目录>
DELETION_LEDGER_PATH=<独立持久存储上的 deletion-ledger.jsonl>
BACKUP_ENCRYPTION_KEY=<32 字节随机密钥的 Base64>
```

`APP_ENV=production` 会校验上述关键配置、政策披露和人工审核标志，缺项时拒绝启动。运营方应先核实隐私政策内容和第三方数据处理事实，再设置 `PRIVACY_POLICY_APPROVED=1`；该标志不代替法律审核。第一版默认 `EMAIL_VERIFICATION_REQUIRED=false`，注册后直接允许登录，不依赖 SMTP；如启用邮件验证，设置 `EMAIL_VERIFICATION_REQUIRED=true`，此时注册和找回密码需要 SMTP，邮箱验证链接有效 24 小时，密码重置链接有效 30 分钟，均为一次性。重置密码会使旧会话失效。

生成备份密钥：`python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"`。将密钥保存到系统密钥管理或运行账号的安全环境中；丢失密钥无法恢复备份。Windows 计划任务需要运行账号持久配置 `BACKUP_ENCRYPTION_KEY`、`BACKUP_OUTPUT_DIR` 和 `DELETION_LEDGER_PATH`，其中删除账本不得位于备份文件目录内。备份脚本在没有删除事件时也会创建空账本，供恢复校验。`MAIL_TLS_MODE=ssl` 可用于隐式 TLS 端口；其他模式被拒绝。

## 迁移与备份

安装与 PostgreSQL 服务端兼容的 `pg_dump`、`pg_restore`、`psql`、`createdb`，并使其在 `PATH`，或设置 `PG_BIN_DIR`。从 `D:\chess\apps\api` 执行 `alembic upgrade head`。当前目标版本是 `0003_email_actions`。

```powershell
cd D:\chess
pwsh -File .\scripts\backup-chess.ps1 -WhatIf
pwsh -File .\scripts\backup-chess.ps1
pwsh -File .\scripts\install-backup-task.ps1 -WhatIf
pwsh -File .\scripts\install-backup-task.ps1
```

备份脚本先清理过期删除请求、过期导出文件并写入删除账本，再执行 PostgreSQL custom-format dump、校验目录、使用 AES-256-GCM 加密，最后删除临时明文。导出包包含账号资料、第三方身份、隐私同意、棋局棋谱和完整复盘结果，不包含密码哈希或邮件令牌。默认保留至少 30 天；备份目录应位于独立主机、卷或账户，并限制访问。计划任务每天本地时间 02:00 运行。运维监控需检查任务退出码、最近成功时间、备份大小及异地复制状态。

## 恢复演练

必须使用**最新的外部删除账本**，不能只用备份当时的账本。恢复脚本强制创建新的隔离数据库，禁止覆盖 `DATABASE_URL` 中的在线库：

```powershell
pwsh -File .\scripts\restore-chess.ps1 -Archive <加密备份路径> -TargetDatabase chess_restore_drill -LedgerPath <最新删除账本路径> -WhatIf
pwsh -File .\scripts\restore-chess.ps1 -Archive <加密备份路径> -TargetDatabase chess_restore_drill -LedgerPath <最新删除账本路径> -ConfirmRestore
```

恢复过程先验证加密文件、创建隔离库并执行 `pg_restore`，然后重放删除账本，再检查 Alembic 版本。重放仅清理恢复数据库中的账号数据，不触碰在线导出文件；如另外恢复了导出存储，需按删除账本清理对应文件。演练后还需抽样从 `initial_fen` 和棋谱重建棋局、检查复盘记录、确认已删除账号不存在；每月至少演练一次。恢复脚本不会自动切换线上流量。

当前实现是每日全量备份。**WAL 归档、15 分钟 RPO、2 小时 RTO、异地复制与告警尚需结合正式 PostgreSQL 托管环境配置和实测**，不能只凭脚本宣称满足。备份密钥、SMTP 凭据、运营主体信息和客户端工具未配置前，本项目不具备正式发布条件。
