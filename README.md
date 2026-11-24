# 定时关机

一个 ClassIsland 2 插件，可在 ClassIsland 内安排关机、重启、注销或睡眠。

## 功能

- 指定具体时间，或在指定倒计时后执行。
- 支持关机、重启、注销和睡眠。
- 关机、重启可以选择强制关闭未保存的程序。
- 执行前 5 分钟通过 ClassIsland 原生提醒提示。
- 支持延期 10 分钟与取消任务。
- 支持恢复循环计划，并自动保存上一次配置。
- 开机后前 5 分钟内不会执行定时关机，也不会恢复落在该时段内的关机计划；触发保护时会通过 ClassIsland 提醒告知。
- 关闭设置页后任务仍在 ClassIsland 后台继续。

## 使用

安装插件并重启 ClassIsland，打开“应用设置”中的“定时关机”页面即可使用。

定时任务只在 ClassIsland 运行期间计时。启用循环计划后，ClassIsland 下次启动会恢复指定时间计划。

## 构建

需要 .NET 8 SDK：

```powershell
dotnet build -c Release
dotnet publish -c Release -o cipx/publish
```

将 `cipx/publish` 目录打包为 ZIP 并改扩展名为 `.cipx`，即可作为插件包分发。

也可以直接运行项目中的一键构建脚本：

```powershell
.\build-plugin.ps1
```

脚本会优先使用项目内 `.dotnet\dotnet.exe`，否则使用系统安装的 `dotnet`，并输出 `cipx\ScheduledShutdown.cipx`。

如果系统执行策略禁止运行 PowerShell 脚本，可双击或运行 `build-plugin.bat`。

## 旧版实现

仓库根目录的 `auto_shutdown.py`、`app_icon.ico` 和启动脚本是迁移前的 Python 桌面程序，保留用于对照和回退，不属于 ClassIsland 插件运行时。

## 许可证

本项目使用 [MIT License](LICENSE) 开源。
