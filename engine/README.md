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

如果引擎安装在其他位置，可通过 `PIKAFISH_PATH` 和 `PIKAFISH_EVAL_FILE` 环境变量指定路径。

