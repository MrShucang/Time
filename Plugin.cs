using System.IO;
using ClassIsland.Core.Abstractions;
using ClassIsland.Core.Attributes;
using ClassIsland.Core.Extensions.Registry;
using ClassIsland.Shared.Helpers;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using ScheduledShutdown.Models;
using ScheduledShutdown.Services;
using ScheduledShutdown.Views;

namespace ScheduledShutdown;

[PluginEntrance]
public sealed class Plugin : PluginBase
{
    private readonly object _configGate = new();
    private string _settingsFile = string.Empty;
    private bool _configLoaded;

    public ScheduledShutdownSettings Settings { get; private set; } = new();

    public override void Initialize(HostBuilderContext context, IServiceCollection services)
    {
        _settingsFile = Path.Combine(PluginConfigFolder, "Settings.json");
        Settings = ConfigureFileHelper.LoadConfig<ScheduledShutdownSettings>(_settingsFile);
        Settings.Normalize();
        _configLoaded = true;

        services.AddSettingsPage<ScheduledShutdownSettingsPage>();
        services.AddSingleton<ScheduledShutdownService>();
        services.AddSingleton<IHostedService>(
            provider => provider.GetRequiredService<ScheduledShutdownService>());
        services.AddNotificationProvider<ScheduledShutdownNotificationProvider>();
    }

    public void SaveSettings()
    {
        lock (_configGate)
        {
            if (!_configLoaded)
            {
                return;
            }

            Settings.Normalize();
            ConfigureFileHelper.SaveConfig(_settingsFile, Settings);
        }
    }
}
