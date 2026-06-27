# Ra3Copilot

Ra3Copilot 是一个本地 Agent 工作台，内置 RA3 地图开发优化场景，并预留得力助手等扩展入口。

欢迎页当前支持：

- 打开或新建本地项目，然后与 Agent 交互。
- 进入 RA3 地图开发场景，把文件夹标记为地图工程。
- 进入得力助手场景，查看所有已绑定 QQ Bot 等 IM 入口的项目。

新建项目时，RA3 地图和通用工作区使用独立的默认保存目录；任意项目都可以在“当前工作区 / IM 接入”中绑定 QQ Bot。

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

## 测试

运行 daemon 认证、入口分派与项目类型的最小测试：

```powershell
cd N:\workspace\ra3\Ra3Copilot\src
uv run python -B -m unittest discover -s tests -v
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
