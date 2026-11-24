using ClassIsland.Core.Abstractions.Services.NotificationProviders;
using ClassIsland.Core.Attributes;
using ClassIsland.Core.Models.Notification;
using Avalonia.Threading;
using ScheduledShutdown.Models;

namespace ScheduledShutdown.Services;

[NotificationProviderInfo(
    "18F25E81-308D-4A55-AEB0-04CFF3356B12",
    "定时关机",
    "\uE7BA",
    "在定时关机、重启、注销或睡眠前显示提醒。")]
public sealed class ScheduledShutdownNotificationProvider : NotificationProviderBase
{
    private readonly ScheduledShutdownService _service;
    private NotificationRequest? _activeWarningRequest;
    private NotificationRequest? _activeScheduleStartedRequest;

    public ScheduledShutdownNotificationProvider(ScheduledShutdownService service)
    {
        _service = service;
        service.CountdownWarningDue += OnCountdownWarningDue;
        service.ScheduleStarted += OnScheduleStarted;
        service.ActionTriggered += OnActionTriggered;
        service.NotificationsDismissRequested += OnNotificationsDismissRequested;
        service.StartupShutdownBlocked += OnStartupShutdownBlocked;
    }

    private void OnCountdownWarningDue(
        object? sender,
        CountdownWarningEventArgs e)
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (_service.Deadline != e.Target)
            {
                return;
            }

            try
            {
                ShowCountdownWarning(
                    e.Remaining,
                    e.Action,
                    e.Target);
            }
            catch
            {
                // 提醒服务异常不能阻止系统动作。
            }
        });
    }

    private void OnScheduleStarted(
        object? sender,
        ScheduleStartedEventArgs e)
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (!_service.IsScheduled || _service.Deadline != e.Target)
            {
                return;
            }

            try
            {
                CancelActiveScheduleStartedNotification();

                var request = new NotificationRequest
                {
                    MaskContent = NotificationContent.CreateTwoIconsMask(
                        $"定时{e.ActionName}已启动",
                        factory: content => content.Duration = TimeSpan.FromSeconds(3)),
                    OverlayContent = NotificationContent.CreateSimpleTextContent(
                        $"{e.Target:MM月dd日 HH:mm:ss} {e.ActionName}",
                        content => content.Duration = TimeSpan.FromSeconds(4))
                };

                request.Completed += OnScheduleStartedCompleted;
                request.Canceled += OnScheduleStartedCompleted;
                _activeScheduleStartedRequest = request;
                ShowNotification(request);
            }
            catch
            {
                // 提醒服务不可用时不影响定时任务本身。
            }
        });
    }

    private void OnActionTriggered(
        object? sender,
        ActionTriggeredEventArgs e)
    {
        CancelActiveNotifications();

        Dispatcher.UIThread.Post(() =>
        {
            try
            {
                ShowActionTriggered(e.Message);
            }
            catch
            {
            }
        });
    }

    private void OnNotificationsDismissRequested(
        object? sender,
        EventArgs e)
    {
        if (Dispatcher.UIThread.CheckAccess())
        {
            CancelActiveNotifications();
        }
        else
        {
            Dispatcher.UIThread.Post(CancelActiveNotifications);
        }
    }

    private void OnStartupShutdownBlocked(
        object? sender,
        StartupShutdownBlockedEventArgs e)
    {
        Dispatcher.UIThread.Post(() =>
        {
            try
            {
                ShowNotification(new NotificationRequest
                {
                    MaskContent = NotificationContent.CreateTwoIconsMask(
                        "定时关机保护已触发",
                        factory: content => content.Duration = TimeSpan.FromSeconds(3)),
                    OverlayContent = NotificationContent.CreateSimpleTextContent(
                        $"系统启动后前 5 分钟不会执行定时关机。" +
                        $"原定于 {e.Target:MM月dd日 HH:mm:ss} 的关机计划未生效。" +
                        $"请在 {e.ProtectionEnds:HH:mm:ss} 后重新设置。",
                        content =>
                        {
                            content.Duration = TimeSpan.FromSeconds(10);
                            content.SpeechContent =
                                $"定时关机保护已触发，开机后五分钟内的关机计划未生效，" +
                                $"请在 {e.ProtectionEnds:HH:mm} 后重新设置。";
                        })
                });
            }
            catch
            {
                // 提醒服务不可用时不影响保护逻辑。
            }
        });
    }

    public void ShowCountdownWarning(
        TimeSpan remaining,
        ScheduledAction action,
        DateTimeOffset target)
    {
        CancelActiveWarning();

        var actionName = GetActionName(action);
        var request = new NotificationRequest
        {
            MaskContent = NotificationContent.CreateTwoIconsMask(
                $"定时{actionName}提醒",
                factory: content => content.Duration = TimeSpan.FromSeconds(4)),
            OverlayContent = NotificationContent.CreateSimpleTextContent(
                $"本机将在 {target:HH:mm:ss} {actionName}，请及时保存工作。可通过 ClassIsland 的“定时关机”设置页延期或取消。",
                content =>
                {
                    content.EndTime = target.LocalDateTime;
                    content.Duration = remaining > TimeSpan.Zero
                        ? remaining
                        : TimeSpan.FromSeconds(1);
                    content.SpeechContent =
                        $"距离定时{actionName}还有约 {Math.Max(1, (int)Math.Ceiling(remaining.TotalMinutes))} 分钟，请及时保存工作。";
                })
        };

        request.Completed += OnWarningCompleted;
        request.Canceled += OnWarningCompleted;
        _activeWarningRequest = request;
        ShowNotification(request);
    }

    public void ShowActionTriggered(string message)
    {
        ShowNotification(new NotificationRequest
        {
            MaskContent = NotificationContent.CreateTwoIconsMask(
                message,
                factory: content => content.Duration = TimeSpan.FromSeconds(4)),
            OverlayContent = NotificationContent.CreateSimpleTextContent(
                "定时关机插件已向系统发送命令。",
                content => content.Duration = TimeSpan.FromSeconds(3))
        });
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

    private void OnWarningCompleted(object? sender, EventArgs e)
    {
        if (ReferenceEquals(_activeWarningRequest, sender))
        {
            _activeWarningRequest = null;
        }
    }

    private void OnScheduleStartedCompleted(object? sender, EventArgs e)
    {
        if (ReferenceEquals(_activeScheduleStartedRequest, sender))
        {
            _activeScheduleStartedRequest = null;
        }
    }

    private void CancelActiveNotifications()
    {
        CancelActiveWarning();
        CancelActiveScheduleStartedNotification();
    }

    private void CancelActiveWarning()
    {
        var request = _activeWarningRequest;
        _activeWarningRequest = null;
        request?.Cancel();
    }

    private void CancelActiveScheduleStartedNotification()
    {
        var request = _activeScheduleStartedRequest;
        _activeScheduleStartedRequest = null;
        request?.Cancel();
    }
}
