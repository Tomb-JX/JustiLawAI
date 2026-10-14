using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using JustiLawAI.Models;
using JustiLawAI.Services;

namespace JustiLawAI.Views;

/// <summary>
/// 设置面板。压在主窗口上的一块浮层，不是单独窗口。
/// 只编辑一份副本，点「保存」才把 <see cref="Result"/> 交回去。
/// </summary>
public partial class SettingsPanel : UserControl
{
    private readonly AppSettings _original;
    private bool _ready;

    /// <summary>点了保存之后的新配置。取消时它仍是进来时那份副本。</summary>
    public AppSettings Result { get; private set; }

    /// <summary>点了保存（且校验通过）。</summary>
    public event EventHandler? Saved;

    /// <summary>点了取消、右上角关闭，或者按了 Esc。</summary>
    public event EventHandler? Cancelled;

    /// <summary>偏好页里换了主题——只是预览，还没落盘。取消时要由外面调回原来那档。</summary>
    public event EventHandler<ThemeMode>? ThemePreview;

    public SettingsPanel(AppSettings current)
    {
        InitializeComponent();

        _original = current;
        Result = current.Clone();

        BaseUrlBox.Text = current.BaseUrl;
        ApiKeyBox.Text = current.ApiKey;
        ModelBox.Text = current.Model;
        PromptBox.Text = current.SystemPrompt;

        switch (current.Theme)
        {
            case ThemeMode.Dark: ThemeDark.IsChecked = true; break;
            case ThemeMode.Light: ThemeLight.IsChecked = true; break;
            default: ThemeSystem.IsChecked = true; break;
        }

        // 卡片贴合内容，但顶到窗口就停：超出部分交给里面那个 ScrollViewer。
        Loaded += (_, _) =>
        {
            var available = Window.GetWindow(this)?.ActualHeight ?? 900;
            Shell.MaxHeight = Math.Max(320, available - 96);
        };

        // 上面那几行赋值会触发 Checked，装完之后才允许预览。
        _ready = true;
    }

    /// <summary>让输入框拿到焦点，打开面板后可以直接打字。</summary>
    public void FocusFirstField() => BaseUrlBox.Focus();

    // ---------- 模型 / 偏好 两页 ----------

    private void OnPageChanged(object sender, RoutedEventArgs e)
    {
        // InitializeComponent 期间 IsChecked="True" 就会触发一次，那时两个页面还没建好。
        if (ModelPage is null || PreferencePage is null) { return; }

        var prefs = PrefsTab.IsChecked == true;
        ModelPage.Visibility = prefs ? Visibility.Collapsed : Visibility.Visible;
        PreferencePage.Visibility = prefs ? Visibility.Visible : Visibility.Collapsed;
    }

    private void OnThemeChanged(object sender, RoutedEventArgs e)
    {
        if (!_ready) { return; }
        ThemePreview?.Invoke(this, CurrentTheme());
    }

    private ThemeMode CurrentTheme()
    {
        if (ThemeDark.IsChecked == true) { return ThemeMode.Dark; }
        if (ThemeLight.IsChecked == true) { return ThemeMode.Light; }
        return ThemeMode.System;
    }

    // ---------- 测试连接 ----------

    private async void OnTestConnection(object sender, RoutedEventArgs e)
    {
        var probe = Snapshot();

        if (string.IsNullOrWhiteSpace(probe.BaseUrl))
        {
            SetTestResult("接口地址是空的。", "Danger");
            return;
        }

        TestButton.IsEnabled = false;
        SetTestResult("正在连接…", "InkSoft");

        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var models = await new OpenAiClient(probe).ListModelsAsync(timeout.Token);

            if (models.Count == 0)
            {
                SetTestResult("连上了，但接口没返回任何模型。", "Warn");
            }
            else
            {
                var shown = string.Join("、", models.Take(5));
                var more = models.Count > 5 ? $" 等 {models.Count} 个" : "";
                SetTestResult($"连上了：{shown}{more}", "Ok");
            }
        }
        catch (ApiException ex)
        {
            SetTestResult(ex.Message, "Danger");
        }
        catch (Exception ex)
        {
            SetTestResult($"测试失败：{ex.Message}", "Danger");
        }
        finally
        {
            TestButton.IsEnabled = true;
        }
    }

    private void SetTestResult(string text, string brushKey)
    {
        TestResult.Text = text;
        TestResult.Foreground = (Brush)FindResource(brushKey);
        TestResult.ToolTip = text;
    }

    // ---------- 保存 / 取消 ----------

    private void OnSave(object sender, RoutedEventArgs e)
    {
        var next = Snapshot();

        // 报错就地写在页脚里，不弹第二个窗口。
        if (string.IsNullOrWhiteSpace(next.BaseUrl))
        {
            ShowError("接口地址不能为空。");
            BaseUrlBox.Focus();
            return;
        }

        if (string.IsNullOrWhiteSpace(next.Model))
        {
            ShowError("模型名不能为空。");
            ModelBox.Focus();
            return;
        }

        ClearError();
        Result = next;
        Saved?.Invoke(this, EventArgs.Empty);
    }

    private void OnCancel(object sender, RoutedEventArgs e) => Cancelled?.Invoke(this, EventArgs.Empty);

    private void ShowError(string message)
    {
        ErrorText.Text = message;
        ErrorText.Visibility = Visibility.Visible;
    }

    private void ClearError()
    {
        ErrorText.Text = string.Empty;
        ErrorText.Visibility = Visibility.Collapsed;
    }

    private AppSettings Snapshot() => new()
    {
        BaseUrl = BaseUrlBox.Text.Trim(),
        ApiKey = ApiKeyBox.Text.Trim(),
        Model = ModelBox.Text.Trim(),
        SystemPrompt = PromptBox.Text,
        // 裁量类任务要可复现，界面上不给改。
        Temperature = _original.Temperature,
        Theme = CurrentTheme(),
    };
}
