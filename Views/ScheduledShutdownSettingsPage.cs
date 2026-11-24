using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using ClassIsland.Core.Abstractions.Controls;
using ClassIsland.Core.Attributes;
using ScheduledShutdown.Models;
using ScheduledShutdown.Services;

namespace ScheduledShutdown.Views;

[SettingsPageInfo(
    "shucang.scheduledshutdown.settings",
    "定时关机",
    "\uE7BA",
    "\uE7BA")]
public sealed class ScheduledShutdownSettingsPage : SettingsPageBase
{
    private readonly ScheduledShutdownService _service;
    private readonly Plugin _plugin;

    private readonly TextBlock _statusText = new();
    private readonly TextBlock _detailText = new();
    private readonly Button _startButton = new() { Content = "开始定时" };
    private readonly Button _cancelButton = new() { Content = "取消定时" };
    private readonly Button _delayButton = new() { Content = "延期 10 分钟" };

    private readonly ComboBox _modeBox = new();
    private readonly ComboBox _actionBox = new();
    private readonly NumericUpDown _hourBox = CreateNumberBox(0, 23, 0);
    private readonly NumericUpDown _minuteBox = CreateNumberBox(0, 59, 0);
    private readonly NumericUpDown _countdownHourBox = CreateNumberBox(0, 99, 0);
    private readonly NumericUpDown _countdownMinuteBox = CreateNumberBox(0, 59, 0);
    private readonly CheckBox _forceBox = new() { Content = "强制关闭未保存的程序" };
    private readonly CheckBox _cycleBox = new() { Content = "ClassIsland 下次启动时恢复此计划" };
    private readonly CheckBox _warningBox = new() { Content = "执行前 5 分钟显示提醒" };
    private readonly StackPanel _fixedTimePanel = new() { Spacing = 8 };
    private readonly StackPanel _countdownPanel = new() { Spacing = 8 };

    public ScheduledShutdownSettingsPage(
        ScheduledShutdownService service,
        Plugin plugin)
    {
        _service = service;
        _plugin = plugin;

        Content = BuildContent();
        LoadSettingsIntoControls();
        AttachEvents();
        UpdateModePanels();
        RefreshState();
        _service.StateChanged += OnServiceStateChanged;
    }

    private Control BuildContent()
    {
        var title = new TextBlock
        {
            Text = "⏰ 定时关机",
            FontSize = 28,
            FontWeight = FontWeight.SemiBold
        };

        var subtitle = new TextBlock
        {
            Text = "由 ClassIsland 在后台计时；关闭设置页不会取消任务。",
            Opacity = 0.7,
            Margin = new Thickness(0, 4, 0, 18),
            TextWrapping = TextWrapping.Wrap
        };

        _statusText.FontSize = 24;
        _statusText.FontWeight = FontWeight.SemiBold;
        _statusText.HorizontalAlignment = HorizontalAlignment.Center;
        _detailText.Opacity = 0.72;
        _detailText.TextAlignment = TextAlignment.Center;
        _detailText.TextWrapping = TextWrapping.Wrap;
        _detailText.Margin = new Thickness(0, 6, 0, 0);

        var statePanel = new Border
        {
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(18),
            Margin = new Thickness(0, 0, 0, 14),
            BorderThickness = new Thickness(1),
            Child = new StackPanel
            {
                Spacing = 4,
                Children =
                {
                    _statusText,
                    _detailText
                }
            }
        };

        _modeBox.ItemsSource = new[]
        {
            "指定时间",
            "从现在开始倒计时"
        };
        _actionBox.ItemsSource = new[]
        {
            "关机",
            "重启",
            "注销",
            "睡眠"
        };

        _modeBox.Width = 240;
        _actionBox.Width = 160;

        var modeRow = CreateSettingRow(
            "定时方式",
            "指定时间会在当天时间已过时自动安排到次日。",
            _modeBox);

        var fixedTimeRow = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,Auto"),
            ColumnSpacing = 8
        };
        fixedTimeRow.Children.Add(_hourBox);
        AddToColumn(fixedTimeRow, CreateLabel("时"), 1);
        AddToColumn(fixedTimeRow, _minuteBox, 2);
        AddToColumn(fixedTimeRow, CreateLabel("分"), 3);

        _fixedTimePanel.Children.Add(CreateLabel("在以下时间执行："));
        _fixedTimePanel.Children.Add(fixedTimeRow);
        _fixedTimePanel.Children.Add(_cycleBox);

        var countdownRow = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,Auto"),
            ColumnSpacing = 8
        };
        countdownRow.Children.Add(_countdownHourBox);
        AddToColumn(countdownRow, CreateLabel("小时"), 1);
        AddToColumn(countdownRow, _countdownMinuteBox, 2);
        AddToColumn(countdownRow, CreateLabel("分钟"), 3);

        var presets = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8
        };
        presets.Children.Add(CreatePresetButton("30 分钟", 0, 30));
        presets.Children.Add(CreatePresetButton("1 小时", 1, 0));
        presets.Children.Add(CreatePresetButton("2 小时", 2, 0));

        _countdownPanel.Children.Add(CreateLabel("从现在开始倒计时："));
        _countdownPanel.Children.Add(countdownRow);
        _countdownPanel.Children.Add(presets);

        var modePanels = new StackPanel
        {
            Spacing = 12,
            Margin = new Thickness(0, 8, 0, 0),
            Children =
            {
                _fixedTimePanel,
                _countdownPanel
            }
        };

        var actionRow = CreateSettingRow(
            "执行动作",
            "关机与重启会先由 Windows 延迟 15 秒执行。",
            _actionBox);

        var optionPanel = new StackPanel
        {
            Spacing = 10,
            Margin = new Thickness(0, 8, 0, 0),
            Children =
            {
                _forceBox,
                _warningBox
            }
        };

        _startButton.MinWidth = 130;
        _cancelButton.MinWidth = 130;
        _delayButton.MinWidth = 150;
        _startButton.Classes.Add("accent");

        var buttonRow = new WrapPanel
        {
            ItemSpacing = 10,
            LineSpacing = 10,
            Margin = new Thickness(0, 18, 0, 0),
            Children =
            {
                _startButton,
                _delayButton,
                _cancelButton
            }
        };

        var footer = new TextBlock
        {
            Text =
                "到点前可在提醒或本页取消任务。循环计划会在 ClassIsland 下次启动时恢复。",
            Opacity = 0.62,
            Margin = new Thickness(0, 14, 0, 0),
            TextWrapping = TextWrapping.Wrap
        };

        var settingsPanel = new StackPanel
        {
            Spacing = 12,
            Children =
            {
                modeRow,
                modePanels,
                actionRow,
                optionPanel
            }
        };

        var body = new StackPanel
        {
            MaxWidth = 760,
            Spacing = 8,
            Children =
            {
                title,
                subtitle,
                statePanel,
                settingsPanel,
                buttonRow,
                footer
            }
        };

        return new ScrollViewer
        {
            Padding = new Thickness(24),
            HorizontalScrollBarVisibility =
                Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            Content = body
        };
    }

    private void LoadSettingsIntoControls()
    {
        var settings = _service.Settings;
        _modeBox.SelectedIndex = settings.Mode == ScheduleMode.FixedTime ? 0 : 1;
        _actionBox.SelectedIndex = (int)settings.Action;
        _hourBox.Value = settings.Hour;
        _minuteBox.Value = settings.Minute;
        _countdownHourBox.Value = settings.CountdownHours;
        _countdownMinuteBox.Value = settings.CountdownMinutes;
        _forceBox.IsChecked = settings.Force;
        _cycleBox.IsChecked = settings.CycleEnabled;
        _warningBox.IsChecked = settings.EnableFiveMinuteWarning;
    }

    private void AttachEvents()
    {
        _modeBox.SelectionChanged += (_, _) =>
        {
            SettingsFromControls();
            UpdateModePanels();
        };
        _actionBox.SelectionChanged += (_, _) =>
        {
            SettingsFromControls();
            UpdateControlAvailability();
        };

        _hourBox.ValueChanged += (_, _) => SettingsFromControls();
        _minuteBox.ValueChanged += (_, _) => SettingsFromControls();
        _countdownHourBox.ValueChanged += (_, _) => SettingsFromControls();
        _countdownMinuteBox.ValueChanged += (_, _) => SettingsFromControls();
        _forceBox.IsCheckedChanged += (_, _) => SettingsFromControls();
        _cycleBox.IsCheckedChanged += (_, _) => SettingsFromControls();
        _warningBox.IsCheckedChanged += (_, _) => SettingsFromControls();

        _startButton.Click += (_, _) =>
        {
            SettingsFromControls();
            if (!_service.TryStartSchedule(out var error))
            {
                _statusText.Text = "无法开始定时";
                _detailText.Text = error;
                return;
            }

            RefreshState();
        };

        _cancelButton.Click += (_, _) =>
        {
            _service.CancelSchedule();
            RefreshState();
        };

        _delayButton.Click += (_, _) =>
        {
            _service.DelaySchedule(TimeSpan.FromMinutes(10));
            RefreshState();
        };
    }

    private void SettingsFromControls()
    {
        var settings = _service.Settings;
        settings.Mode = _modeBox.SelectedIndex == 1
            ? ScheduleMode.Countdown
            : ScheduleMode.FixedTime;
        settings.Action = (ScheduledAction)Math.Clamp(
            _actionBox.SelectedIndex,
            0,
            3);
        settings.Hour = ToInt(_hourBox.Value, 22);
        settings.Minute = ToInt(_minuteBox.Value);
        settings.CountdownHours = ToInt(_countdownHourBox.Value, 1);
        settings.CountdownMinutes = ToInt(_countdownMinuteBox.Value);
        settings.Force = _forceBox.IsChecked == true;
        settings.CycleEnabled = _cycleBox.IsChecked == true;
        settings.EnableFiveMinuteWarning = _warningBox.IsChecked == true;
        settings.Normalize();
        _plugin.SaveSettings();
        UpdateControlAvailability();
    }

    private void UpdateModePanels()
    {
        var fixedTime = _modeBox.SelectedIndex != 1;
        _fixedTimePanel.IsVisible = fixedTime;
        _countdownPanel.IsVisible = !fixedTime;
        _cycleBox.IsEnabled = fixedTime && !_service.IsScheduled;
        UpdateControlAvailability();
    }

    private void UpdateControlAvailability()
    {
        var running = _service.IsScheduled;
        var needsForce = _actionBox.SelectedIndex is 0 or 1;
        var fixedTime = _modeBox.SelectedIndex != 1;

        _startButton.IsEnabled = !running;
        _cancelButton.IsEnabled = running;
        _delayButton.IsEnabled = running;
        _modeBox.IsEnabled = !running;
        _actionBox.IsEnabled = !running;
        _hourBox.IsEnabled = !running && fixedTime;
        _minuteBox.IsEnabled = !running && fixedTime;
        _countdownHourBox.IsEnabled = !running && !fixedTime;
        _countdownMinuteBox.IsEnabled = !running && !fixedTime;
        _forceBox.IsEnabled = !running && needsForce;
        _cycleBox.IsEnabled = !running && fixedTime;
        _warningBox.IsEnabled = !running;
    }

    private void OnServiceStateChanged(object? sender, EventArgs e)
    {
        Avalonia.Threading.Dispatcher.UIThread.Post(RefreshState);
    }

    private void RefreshState()
    {
        var remaining = _service.Remaining;
        _statusText.Text = remaining is null
            ? _service.StatusText
            : FormatRemaining(remaining.Value);
        _detailText.Text = _service.DetailText;
        UpdateControlAvailability();
    }

    private static string FormatRemaining(TimeSpan remaining)
    {
        var totalHours = (int)remaining.TotalHours;
        return $"{totalHours:00}:{remaining.Minutes:00}:{remaining.Seconds:00}";
    }

    private Button CreatePresetButton(string text, int hours, int minutes)
    {
        var button = new Button
        {
            Content = text
        };
        button.Click += (_, _) =>
        {
            _countdownHourBox.Value = hours;
            _countdownMinuteBox.Value = minutes;
        };
        return button;
    }

    private static Grid CreateSettingRow(
        string title,
        string description,
        Control control)
    {
        var text = new StackPanel
        {
            Spacing = 3,
            Children =
            {
                new TextBlock
                {
                    Text = title,
                    FontWeight = FontWeight.SemiBold
                },
                new TextBlock
                {
                    Text = description,
                    Opacity = 0.65,
                    TextWrapping = TextWrapping.Wrap,
                    MaxWidth = 470
                }
            }
        };

        var grid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,Auto"),
            ColumnSpacing = 18
        };
        grid.Children.Add(text);
        AddToColumn(grid, control, 1);
        return grid;
    }

    private static TextBlock CreateLabel(string text)
    {
        return new TextBlock
        {
            Text = text,
            VerticalAlignment = VerticalAlignment.Center
        };
    }

    private static NumericUpDown CreateNumberBox(
        decimal minimum,
        decimal maximum,
        decimal value)
    {
        return new NumericUpDown
        {
            Minimum = minimum,
            Maximum = maximum,
            Value = value,
            Increment = 1,
            FormatString = "00",
            Width = 110,
            ClipValueToMinMax = true
        };
    }

    private static void AddToColumn(
        Grid grid,
        Control control,
        int column)
    {
        Grid.SetColumn(control, column);
        grid.Children.Add(control);
    }

    private static int ToInt(decimal? value, int fallback = 0)
    {
        return value is null ? fallback : (int)Math.Round(value.Value);
    }
}
