# Ra3Copilot

Ra3Copilot 是面向 Red Alert 3 地图开发的本地 Agent 工作台。

## 桌面前端

默认入口会启动新的桌面前端，不再进入 `tui`：

```powershell
cd N:\workspace\ra3\Ra3Copilot\src
uv run python main.py
```

调试网页视图：

```powershell
uv run python main.py --debug
```

保留旧 TUI 入口：

```powershell
uv run python main.py --tui
```

## 导出 EXE

在项目根目录运行：

```powershell
cd N:\workspace\ra3\Ra3Copilot
.\build_exe.ps1
```

生成文件位于：

```text
src\dist\Ra3Copilot.exe
```

如果需要清理旧构建产物：

```powershell
.\build_exe.ps1 -Clean
```
