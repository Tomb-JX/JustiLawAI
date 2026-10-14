using System.Windows;
using JustiLawAI.Models;
using Microsoft.Win32;
using Wpf.Ui.Appearance;

namespace JustiLawAI.Services;

/// <summary>
/// 浅色 / 深色。用哪套由设置里的 <see cref="ThemeMode"/> 决定：跟着系统、固定浅色、固定深色。
///
/// 做两件事：
///   1. 让 WPF-UI 的控件（按钮、滚动条、输入框、右键菜单）切到对应的 Fluent 主题；
///   2. 换掉本应用自己的色板（Themes/Light.xaml 与 Themes/Dark.xaml，
///      取值照 DeepSeek Harness 的设计令牌）。
///
/// 换色板的顺序是关键：MergedDictionaries 倒序查找，所以新色板要加到最后、
/// 再把旧的那本移除，这样它才能盖过 WPF-UI 自带的令牌。
/// </summary>
public static class ThemeService
{
    private const string LightSource = "pack://application:,,,/Themes/Light.xaml";
    private const string DarkSource = "pack://application:,,,/Themes/Dark.xaml";

    private static ResourceDictionary? _palette;
    private static ThemeMode _mode = ThemeMode.System;

    /// <summary>当前是否深色。</summary>
    public static bool IsDark { get; private set; }

    /// <summary>当前选的是哪一档。</summary>
    public static ThemeMode Mode => _mode;

    /// <summary>在 App.OnStartup 里调用一次，把配置里存的那一档传进来。</summary>
    public static void Start(ThemeMode mode = ThemeMode.System)
    {
        _mode = mode;
        Apply(Resolve());
        SystemEvents.UserPreferenceChanged += OnUserPreferenceChanged;
    }

    /// <summary>设置里改了主题。设置面板里点一下就调它，取消时再调回原来那档。</summary>
    public static void SetMode(ThemeMode mode)
    {
        _mode = mode;
        Apply(Resolve());
    }

    /// <summary>这一档到底该用深色还是浅色。</summary>
    private static bool Resolve() => _mode switch
    {
        ThemeMode.Light => false,
        ThemeMode.Dark => true,
        _ => IsSystemDark(),
    };

    /// <summary>系统设置里改了浅色 / 深色就跟着换——只有「跟随系统」这一档才听。</summary>
    private static void OnUserPreferenceChanged(object sender, UserPreferenceChangedEventArgs e)
    {
        // 只认跟主题有关的几类，别的（开机、鼠标、电源）不理会。
        if (e.Category is not (UserPreferenceCategory.General
            or UserPreferenceCategory.Color
            or UserPreferenceCategory.VisualStyle))
        {
            return;
        }

        if (_mode != ThemeMode.System) { return; }

        var app = Application.Current;
        if (app is null) { return; }

        app.Dispatcher.Invoke(() => Apply(IsSystemDark()));
    }

    /// <summary>
    /// 读注册表判断系统在用什么。AppsUseLightTheme：0 = 深色，1 = 浅色。
    /// 读不到就按浅色走——查不出来的时候给个亮的总比给个黑的强。
    /// </summary>
    public static bool IsSystemDark()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");

            return key?.GetValue("AppsUseLightTheme") is int light && light == 0;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>换成指定的主题。</summary>
    public static void Apply(bool dark)
    {
        IsDark = dark;

        // 1. 先让 WPF-UI 把控件主题换掉。它会顺带把系统强调色也刷一遍，
        //    所以本应用的颜色必须在这一步之后覆盖。
        ApplicationThemeManager.Apply(dark ? ApplicationTheme.Dark : ApplicationTheme.Light);

        var app = Application.Current;
        if (app is null) { return; }

        // 2. 再盖我们的色板。
        var next = new ResourceDictionary
        {
            Source = new Uri(dark ? DarkSource : LightSource, UriKind.Absolute),
        };

        var merged = app.Resources.MergedDictionaries;
        var previous = _palette;

        // 先加后删：中间不会出现“这些键找不到”的空档，界面不会闪回默认色。
        merged.Add(next);
        if (previous is not null)
        {
            merged.Remove(previous);
        }

        _palette = next;
    }
}
