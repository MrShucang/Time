namespace ScheduledShutdown.Models;

public enum ScheduleMode
{
    FixedTime,
    Countdown
}

public enum ScheduledAction
{
    Shutdown,
    Restart,
    LogOff,
    Sleep
}
