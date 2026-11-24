namespace ScheduledShutdown.Models;

public sealed class ScheduledShutdownSettings
{
    public ScheduleMode Mode { get; set; } = ScheduleMode.FixedTime;

    public int Hour { get; set; } = 22;

    public int Minute { get; set; }

    public int CountdownHours { get; set; } = 1;

    public int CountdownMinutes { get; set; }

    public ScheduledAction Action { get; set; } = ScheduledAction.Shutdown;

    public bool Force { get; set; } = true;

    public bool CycleEnabled { get; set; }

    public bool EnableFiveMinuteWarning { get; set; } = true;

    public DateTimeOffset? PendingDeadline { get; set; }

    public bool CyclePending { get; set; }

    public void Normalize()
    {
        Hour = Math.Clamp(Hour, 0, 23);
        Minute = Math.Clamp(Minute, 0, 59);
        CountdownHours = Math.Clamp(CountdownHours, 0, 99);
        CountdownMinutes = Math.Clamp(CountdownMinutes, 0, 59);

        if (!Enum.IsDefined(Mode))
        {
            Mode = ScheduleMode.FixedTime;
        }

        if (!Enum.IsDefined(Action))
        {
            Action = ScheduledAction.Shutdown;
        }

        if (Mode != ScheduleMode.FixedTime)
        {
            CyclePending = false;
        }
    }
}
