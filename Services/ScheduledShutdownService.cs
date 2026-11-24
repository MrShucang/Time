using System.Diagnostics;
using ClassIsland.Core.Models.Notification;
using Microsoft.Extensions.Hosting;
using ScheduledShutdown.Models;

namespace ScheduledShutdown.Services;

public sealed class CountdownWarningEventArgs(
    TimeSpan remaining,
    ScheduledAction action,
    DateTimeOffset target) : EventArgs
{
    public TimeSpan Remaining { get; } = remaining;

    public ScheduledAction Action { get; } = action;

    public DateTimeOffset Target { get; } = target;
}

public sealed class ScheduleStartedEventArgs(
    DateTimeOffset target,
    string actionName) : EventArgs
{
    public DateTimeOffset Target { get; } = target;

    public string ActionName { get; } = actionName;
}

public sealed class ActionTriggeredEventArgs(string message) : EventArgs
{
    public string Message { get; } = message;
}

public sealed class StartupShutdownBlockedEventArgs(
    DateTimeOffset target,
    DateTimeOffset protectionEnds) : EventArgs
{
    public DateTimeOffset Target { get; } = target;

    public DateTimeOffset ProtectionEnds { get; } = protectionEnds;
}

public sealed class ScheduledShutdownService : IHostedService, IDisposable
{
    private static readonly TimeSpan WarningLeadTime = TimeSpan.FromMinutes(5);
    private static readonly TimeSpan StartupShutdownProtectionWindow =
        TimeSpan.FromMinutes(5);

    private readonly Plugin _plugin;
    private readonly object _gate = new();

    private CancellationTokenSource? _scheduleCancellation;
    private Task _worker = Task.CompletedTask;
    private DateTimeOffset? _deadline;
    private bool _warningShown;
    private bool _systemCommandIssued;
    private string _statusText = "未设置定时任务";
    private string _detailText = "可在下方选择执行时间和动作。";

    public ScheduledShutdownService(Plugin plugin)
    {
        _plugin = plugin;
    }

    public event EventHandler? StateChanged;

    public event EventHandler<CountdownWarningEventArgs>? CountdownWarningDue;

    public event EventHandler<ScheduleStartedEventArgs>? ScheduleStarted;

    public event EventHandler<ActionTriggeredEventArgs>? ActionTriggered;

    public event EventHandler? NotificationsDismissRequested;

    public event EventHandler<StartupShutdownBlockedEventArgs>?
        StartupShutdownBlocked;

    public ScheduledShutdownSettings Settings => _plugin.Settings;

    public bool IsScheduled
    {
        get
        {
            lock (_gate)
            {
                return _deadline is not null || _systemCommandIssued;
            }
        }
    }

    public DateTimeOffset? Deadline
    {
        get
        {
            lock (_gate)
            {
                return _deadline;
            }
        }
    }

    public TimeSpan? Remaining
    {
        get
        {
            var deadline = Deadline;
            return deadline is null
                ? null
                : TimeSpan.FromSeconds(
                    Math.Max(0, (deadline.Value - DateTimeOffset.Now).TotalSeconds));
        }
    }

    public string StatusText
    {
        get
        {
            lock (_gate)
            {
                return _statusText;
            }
        }
    }

    public string DetailText
    {
        get
        {
            lock (_gate)
            {
                return _detailText;
            }
        }
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        ResumePersistedSchedule();
        return Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        CancellationTokenSource? cancellation;

        lock (_gate)
        {
            cancellation = _scheduleCancellation;
            _scheduleCancellation = null;
        }

        cancellation?.Cancel();

        try
        {
            await _worker.WaitAsync(TimeSpan.FromSeconds(2), cancellationToken);
        }
        catch (OperationCanceledException)
        {
        }
        catch (TimeoutException)
        {
        }

        cancellation?.Dispose();
    }

    public bool TryStartSchedule(out string error)
    {
        error = string.Empty;

        if (IsScheduled)
        {
            error = "已有正在运行的定时任务，请先取消。";
            return false;
        }

        DateTimeOffset target;
        var now = DateTimeOffset.Now;

        if (Settings.Mode == ScheduleMode.FixedTime)
        {
            target = new DateTimeOffset(
                now.Year,
                now.Month,
                now.Day,
                Settings.Hour,
                Settings.Minute,
                0,
                now.Offset);

            if (target <= now)
            {
                target = target.AddDays(1);
            }
        }
        else
        {
            if (Settings.CountdownHours == 0 && Settings.CountdownMinutes == 0)
            {
                error = "倒计时至少需要 1 分钟。";
                return false;
            }

            target = now
                .AddHours(Settings.CountdownHours)
                .AddMinutes(Settings.CountdownMinutes);
        }

        if (IsProtectedStartupShutdown(Settings.Action, target, now))
        {
            var protectionEnds = GetStartupProtectionEnd(now);
            StartupShutdownBlocked?.Invoke(
                this,
                new StartupShutdownBlockedEventArgs(target, protectionEnds));
            error =
                $"为保护开机后的系统，启动后前 5 分钟不会执行定时关机。" +
                $"请在 {protectionEnds:HH:mm:ss} 后重新设置。";
            return false;
        }

        var cyclePending = Settings.Mode == ScheduleMode.FixedTime && Settings.CycleEnabled;
        StartScheduleAt(target, cyclePending);
        return true;
    }

    public void DelaySchedule(TimeSpan delay)
    {
        DateTimeOffset target;

        lock (_gate)
        {
            if (_deadline is null && !_systemCommandIssued)
            {
                return;
            }

            target = (_deadline ?? DateTimeOffset.Now).Add(delay);
            if (_systemCommandIssued)
            {
                TryRunCommand("shutdown", ["/a"]);
                _systemCommandIssued = false;
            }
        }

        NotificationsDismissRequested?.Invoke(this, EventArgs.Empty);
        StartScheduleAt(target, Settings.CyclePending);
        SetStatus(
            $"已延期 {delay.TotalMinutes:0} 分钟",
            $"新的执行时间：{target:MM月dd日 HH:mm:ss}");
    }

    public void CancelSchedule(bool clearCyclePending = true)
    {
        CancellationTokenSource? cancellation;
        bool abortSystemCommand;

        lock (_gate)
        {
            cancellation = _scheduleCancellation;
            _scheduleCancellation = null;
            _deadline = null;
            _warningShown = false;
            abortSystemCommand = _systemCommandIssued;
            _systemCommandIssued = false;

            if (clearCyclePending)
            {
                Settings.CyclePending = false;
            }
        }

        cancellation?.Cancel();
        cancellation?.Dispose();

        if (abortSystemCommand)
        {
            TryRunCommand("shutdown", ["/a"]);
        }

        NotificationsDismissRequested?.Invoke(this, EventArgs.Empty);
        Settings.PendingDeadline = null;
        _plugin.SaveSettings();
        SetStatus("已取消定时任务", "可重新选择一个时间开始。");
    }

    private void ResumePersistedSchedule()
    {
        if (Settings.PendingDeadline is null)
        {
            return;
        }

        var now = DateTimeOffset.Now;
        var pending = Settings.PendingDeadline.Value;

        if (pending > now)
        {
            if (IsProtectedStartupShutdown(Settings.Action, pending, now))
            {
                BlockStartupShutdown(pending);
                return;
            }

            StartScheduleAt(pending, Settings.CyclePending, announce: false);
            return;
        }

        if (Settings.CyclePending && Settings.Mode == ScheduleMode.FixedTime)
        {
            var next = new DateTimeOffset(
                now.Year,
                now.Month,
                now.Day,
                Settings.Hour,
                Settings.Minute,
                0,
                now.Offset);

            if (next <= now)
            {
                next = next.AddDays(1);
            }

            StartScheduleAt(next, true, announce: false);
            return;
        }

        Settings.PendingDeadline = null;
        Settings.CyclePending = false;
        _plugin.SaveSettings();
        SetStatus(
            "上次定时任务已失效",
            "ClassIsland 未在计划时间运行，任务没有执行。");
    }

    private void StartScheduleAt(
        DateTimeOffset target,
        bool cyclePending,
        bool announce = true)
    {
        CancellationTokenSource cancellation;
        Task worker;

        lock (_gate)
        {
            _scheduleCancellation?.Cancel();
            _scheduleCancellation?.Dispose();

            cancellation = new CancellationTokenSource();
            _scheduleCancellation = cancellation;
            _deadline = target;
            _warningShown = false;
            _systemCommandIssued = false;

            Settings.PendingDeadline = target;
            Settings.CyclePending = cyclePending;
            _plugin.SaveSettings();

            worker = WaitAndExecuteAsync(target, cancellation.Token);
            _worker = worker;
        }

        var actionName = GetActionName(Settings.Action);
        SetStatus("定时任务运行中", $"{target:MM月dd日 HH:mm:ss} {actionName}");

        if (announce)
        {
            ScheduleStarted?.Invoke(
                this,
                new ScheduleStartedEventArgs(target, actionName));
        }
    }

    private async Task WaitAndExecuteAsync(
        DateTimeOffset target,
        CancellationToken cancellationToken)
    {
        try
        {
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var remaining = target - DateTimeOffset.Now;

                if (remaining <= TimeSpan.Zero)
                {
                    break;
                }

                if (Settings.EnableFiveMinuteWarning && remaining <= WarningLeadTime)
                {
                    ShowWarningOnce(remaining, target);
                }

                RaiseStateChanged();
                await Task.Delay(
                    remaining < TimeSpan.FromMilliseconds(250)
                        ? remaining
                        : TimeSpan.FromMilliseconds(250),
                    cancellationToken);
            }

            if (IsProtectedStartupShutdown(
                    Settings.Action,
                    target,
                    DateTimeOffset.Now))
            {
                BlockStartupShutdown(target);
                return;
            }

            await ExecuteScheduledActionAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private void ShowWarningOnce(
        TimeSpan remaining,
        DateTimeOffset target)
    {
        var shouldShow = false;

        lock (_gate)
        {
            if (!_warningShown)
            {
                _warningShown = true;
                shouldShow = true;
            }
        }

        if (!shouldShow)
        {
            return;
        }

        var action = Settings.Action;
        CountdownWarningDue?.Invoke(
            this,
            new CountdownWarningEventArgs(remaining, action, target));
    }

    private async Task ExecuteScheduledActionAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        NotificationsDismissRequested?.Invoke(this, EventArgs.Empty);

        var action = Settings.Action;
        var force = Settings.Force;
        var actionName = GetActionName(action);
        var cyclePending = Settings.Mode == ScheduleMode.FixedTime && Settings.CycleEnabled;
        var succeeded = TryRunAction(action, force, out var error);

        lock (_gate)
        {
            _deadline = null;
            _scheduleCancellation = null;
            _warningShown = false;
            _systemCommandIssued =
                succeeded &&
                action is ScheduledAction.Shutdown or ScheduledAction.Restart;
            Settings.PendingDeadline = null;
            Settings.CyclePending = cyclePending;
        }

        _plugin.SaveSettings();

        if (succeeded)
        {
            var detail = action is ScheduledAction.Shutdown or ScheduledAction.Restart
                ? "系统将在 15 秒后执行，如需中止可立即在插件中再次取消。"
                : "系统已开始执行定时动作。";
            SetStatus($"已触发{actionName}", detail);
            ActionTriggered?.Invoke(
                this,
                new ActionTriggeredEventArgs($"正在{actionName}"));
        }
        else
        {
            SetStatus($"{actionName}执行失败", error);
        }

        await Task.CompletedTask;
    }

    private static bool TryRunAction(
        ScheduledAction action,
        bool force,
        out string error)
    {
        switch (action)
        {
            case ScheduledAction.Shutdown:
                return TryRunCommand(
                    "shutdown",
                    force
                        ? ["/s", "/t", "15", "/f"]
                        : ["/s", "/t", "15"],
                    out error);
            case ScheduledAction.Restart:
                return TryRunCommand(
                    "shutdown",
                    force
                        ? ["/r", "/t", "15", "/f"]
                        : ["/r", "/t", "15"],
                    out error);
            case ScheduledAction.LogOff:
                return TryRunCommand("shutdown", ["/l"], out error);
            case ScheduledAction.Sleep:
                return TryRunCommand(
                    "rundll32.exe",
                    ["powrprof.dll,SetSuspendState", "0,1,0"],
                    out error);
            default:
                error = "未知的系统动作。";
                return false;
        }
    }

    private static bool TryRunCommand(
        string fileName,
        IReadOnlyList<string> arguments,
        out string error)
    {
        error = string.Empty;

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };

            foreach (var argument in arguments)
            {
                startInfo.ArgumentList.Add(argument);
            }

            using var process = Process.Start(startInfo);
            if (process is null)
            {
                error = "系统没有启动对应的命令进程。";
                return false;
            }

            if (fileName.Equals("shutdown", StringComparison.OrdinalIgnoreCase) &&
                arguments.Contains("/l", StringComparer.OrdinalIgnoreCase))
            {
                return true;
            }

            process.WaitForExit(5000);
            if (!process.HasExited || process.ExitCode == 0)
            {
                return true;
            }

            error = $"系统命令返回错误代码 {process.ExitCode}。";
            return false;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
    }

    private static bool TryRunCommand(
        string fileName,
        IReadOnlyList<string> arguments)
    {
        return TryRunCommand(fileName, arguments, out _);
    }

    private static string GetActionName(ScheduledAction action)
    {
        return action switch
        {
            ScheduledAction.Shutdown => "关机",
            ScheduledAction.Restart => "重启",
            ScheduledAction.LogOff => "注销",
            ScheduledAction.Sleep => "睡眠",
            _ => "执行系统操作"
        };
    }

    private static DateTimeOffset GetStartupProtectionEnd(DateTimeOffset now)
    {
        var uptime = TimeSpan.FromMilliseconds(
            Math.Max(0, Environment.TickCount64));
        var protectionRemaining = StartupShutdownProtectionWindow - uptime;

        return protectionRemaining > TimeSpan.Zero
            ? now + protectionRemaining
            : now;
    }

    private static bool IsProtectedStartupShutdown(
        ScheduledAction action,
        DateTimeOffset target,
        DateTimeOffset now)
    {
        return action == ScheduledAction.Shutdown &&
               target < GetStartupProtectionEnd(now);
    }

    private void BlockStartupShutdown(DateTimeOffset target)
    {
        CancellationTokenSource? cancellation;

        lock (_gate)
        {
            cancellation = _scheduleCancellation;
            _scheduleCancellation = null;
            _deadline = null;
            _warningShown = false;
            _systemCommandIssued = false;
            Settings.PendingDeadline = null;
            Settings.CyclePending = false;
        }

        cancellation?.Cancel();
        NotificationsDismissRequested?.Invoke(this, EventArgs.Empty);
        StartupShutdownBlocked?.Invoke(
            this,
            new StartupShutdownBlockedEventArgs(
                target,
                GetStartupProtectionEnd(DateTimeOffset.Now)));
        _plugin.SaveSettings();
        SetStatus(
            "已阻止开机后 5 分钟内的定时关机",
            $"本次计划时间 {target:MM月dd日 HH:mm:ss} 未被写入系统关机命令。");
    }

    private void SetStatus(string status, string detail)
    {
        lock (_gate)
        {
            _statusText = status;
            _detailText = detail;
        }

        RaiseStateChanged();
    }

    private void RaiseStateChanged()
    {
        StateChanged?.Invoke(this, EventArgs.Empty);
    }

    public void Dispose()
    {
        _scheduleCancellation?.Cancel();
        _scheduleCancellation?.Dispose();
    }
}
