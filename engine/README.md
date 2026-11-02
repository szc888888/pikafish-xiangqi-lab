# Pikafish 引擎

引擎二进制文件和 NNUE 网络不提交到源码仓库。Windows x86-64 用户可在项目根目录运行安装脚本，从 Pikafish 官方 Releases 下载并安装最新版本：

```powershell
.\scripts\install-engine.ps1
```

安装前预览但不写入文件：

```powershell
.\scripts\install-engine.ps1 -WhatIf
```

更新已有文件时显式允许覆盖：

```powershell
.\scripts\install-engine.ps1 -Force
```

如需固定 Pikafish 版本，可将官方 tag 传给 `-Version`，例如：

```powershell
.\scripts\install-engine.ps1 -Version Pikafish-2026-09-06
```

脚本从 <https://github.com/official-pikafish/Pikafish/releases> 获取官方发布包，并将文件安装为本目录下的 `pikafish.exe` 和 `pikafish.nnue`。也可以手动下载 Windows x86-64 universal 发布包并放入此目录。

Docker 使用 Linux x86-64 引擎。手动预先安装时运行：

```powershell
.\scripts\install-engine.ps1 -Platform Linux -InstallDirectory .\engine\linux-x86-64
```

`start-docker.ps1` 会在缺少 Linux 引擎或 NNUE 时自动执行这一步，从 Pikafish 官方 Releases 下载当前最新版本，放到 `engine/linux-x86-64/`。首次 Docker 启动需要能够访问 GitHub。此目录已加入 `.gitignore`，引擎和网络文件不会进入源码提交。容器启动时会将只读挂载的文件复制到容器内并设置可执行权限，Windows 的 `pikafish.exe` 不会被拿来运行。

如果引擎安装在其他位置，可通过 `PIKAFISH_PATH` 和 `PIKAFISH_EVAL_FILE` 环境变量指定路径。引擎程序和 NNUE 必须来自同一个兼容版本。

