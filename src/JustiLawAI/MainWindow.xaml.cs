using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using JustiLawAI.Models;
using JustiLawAI.Services;
using JustiLawAI.ViewModels;
using JustiLawAI.Views;
using Microsoft.Win32;
using Wpf.Ui.Controls;

namespace JustiLawAI;

/// <summary>
/// 主窗口。这里只放纯 UI 动作（文件对话框、拖放、滚动、另存、浮层），状态都在 <see cref="MainViewModel"/>。
/// 布局是「左侧案件 + 中间消息流 + 底部输入区」，观感走 Fluent。
///
/// 设置页、新建案件、提示与确认都压在主窗口的浮层里（<see cref="OverlayHost"/>），
/// 不再另开顶层窗口——对话框和内容在同一个窗口里。
/// </summary>
public partial class MainWindow : FluentWindow
{
    private readonly MainViewModel _viewModel = new();

    public MainWindow()
    {
        InitializeComponent();
        DataContext = _viewModel;

        // 输入框是多行的，所以 Enter 只换行，Ctrl+Enter 才发送。
        InputBindings.Add(new KeyBinding(_viewModel.SendCommand, Key.Enter, ModifierKeys.Control));

        // 流式过程中每来一段就滚到底，不然用户得自己往下拖。
        _viewModel.StreamUpdated += (_, _) => Dispatcher.BeginInvoke(
            System.Windows.Threading.DispatcherPriority.Background,
            new Action(() => StreamScroll.ScrollToEnd()));

        // 浮层开着的时候 Esc 关掉它。
        PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.Escape && IsOverlayOpen)
            {
                HideOverlay();
                e.Handled = true;
            }
        };
    }

    // ---------- 浮层 ----------

    private bool IsOverlayOpen => OverlayHost.Visibility == Visibility.Visible;

    private void ShowOverlay(UIElement panel)
    {
        OverlayBody.Content = panel;
        OverlayHost.Visibility = Visibility.Visible;
    }

    private void HideOverlay()
    {
        OverlayHost.Visibility = Visibility.Collapsed;
        OverlayBody.Content = null;
    }

    /// <summary>窗口内提示，替代原来的 MessageBox。</summary>
    private void ShowNotice(string title, string message)
    {
        var panel = new NoticePanel(title, message);
        panel.Confirmed += (_, _) => HideOverlay();
        panel.Dismissed += (_, _) => HideOverlay();
        ShowOverlay(panel);
    }

    // ---------- 左侧案件栏的收起 / 展开 ----------

    private bool _sidebarCollapsed;

    /// <summary>
    /// 左栏是不是收着的。案件行模板在 DataTemplate 里，拿不到字段，
    /// 所以用窗口自己当绑定源，让行里的 TextBlock 跟着它藏时间、换折行。
    /// </summary>
    public static readonly DependencyProperty SidebarCollapsedProperty =
        DependencyProperty.Register(
            nameof(SidebarCollapsed), typeof(bool), typeof(MainWindow),
            new PropertyMetadata(false));

    public bool SidebarCollapsed
    {
        get => (bool)GetValue(SidebarCollapsedProperty);
        private set => SetValue(SidebarCollapsedProperty, value);
    }

    /// <summary>
    /// 左栏收起成一条窄轨：只剩顶上的展开按钮、底下的设置图标，
    /// 案件列表还在，但每一条只留名字（时间那行和标题都藏起来）。
    /// 展开就原样复原。
    /// </summary>
    private void OnToggleSidebar(object sender, RoutedEventArgs e)
    {
        _sidebarCollapsed = !_sidebarCollapsed;
        SidebarCollapsed = _sidebarCollapsed;

        if (_sidebarCollapsed)
        {
            SidebarTitle.Visibility = Visibility.Collapsed;
            NewCaseButton.Visibility = Visibility.Collapsed;
            SettingsLabel.Visibility = Visibility.Collapsed;

            SidebarColumn.MinWidth = 0;
            SidebarColumn.Width = new GridLength(108);
            // 窄轨里表头只剩这一颗按钮，让它自己缩到内容宽、在整条轨里居中，
            // 不能再用展开态那种「左对齐 + 右边留给标题」的边距。
            SidebarHeader.HorizontalAlignment = HorizontalAlignment.Center;
            SidebarHeader.Margin = new Thickness(0, 14, 0, 6);
            CaseList.Margin = new Thickness(6, 0, 6, 10);
            SettingsBox.Margin = new Thickness(0);
            SettingsButton.HorizontalAlignment = HorizontalAlignment.Center;

            SidebarToggleIcon.Symbol = SymbolRegular.PanelLeftExpand24;
            SidebarToggle.ToolTip = "展开案件列表";
            AutomationProperties.SetName(SidebarToggle, "展开案件列表");
        }
        else
        {
            SidebarTitle.Visibility = Visibility.Visible;
            NewCaseButton.Visibility = Visibility.Visible;
            SettingsLabel.Visibility = Visibility.Visible;

            SidebarColumn.MinWidth = 200;
            SidebarColumn.Width = new GridLength(250);
            SidebarHeader.HorizontalAlignment = HorizontalAlignment.Stretch;
            SidebarHeader.Margin = new Thickness(18, 16, 12, 8);
            CaseList.Margin = new Thickness(10, 0, 10, 12);
            SettingsBox.Margin = new Thickness(12, 0, 12, 0);
            SettingsButton.HorizontalAlignment = HorizontalAlignment.Left;

            SidebarToggleIcon.Symbol = SymbolRegular.PanelLeftContract24;
            SidebarToggle.ToolTip = "收起案件列表";
            AutomationProperties.SetName(SidebarToggle, "收起案件列表");
        }
    }

    // ---------- 打开材料 ----------

    private void OnOpenFile(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择案件材料",
            Filter = DocumentReader.FileDialogFilter,
            Multiselect = true,
        };

        if (dialog.ShowDialog(this) == true)
        {
            foreach (var file in dialog.FileNames)
            {
                LoadFile(file);
            }
        }
    }

    private void LoadFile(string path)
    {
        if (!DocumentReader.IsSupported(path))
        {
            ShowNotice(
                "这个格式还不支持",
                $"{Path.GetExtension(path)}\n当前支持：{string.Join("、", DocumentReader.SupportedExtensions)}");
            return;
        }

        try
        {
            _viewModel.LoadMaterial(path);
        }
        catch (Exception ex)
        {
            ShowNotice("读不了这个文件", ex.Message);
        }
    }

    // ---------- 拖放 ----------

    private void OnDragOver(object sender, DragEventArgs e)
    {
        e.Effects = e.Data.GetDataPresent(DataFormats.FileDrop)
            ? DragDropEffects.Copy
            : DragDropEffects.None;
        e.Handled = true;
    }

    private void OnDrop(object sender, DragEventArgs e)
    {
        if (!e.Data.GetDataPresent(DataFormats.FileDrop))
        {
            return;
        }

        if (e.Data.GetData(DataFormats.FileDrop) is string[] { Length: > 0 } files)
        {
            // 拖多少就挂多少，都是文件，不下沉成文字。
            foreach (var file in files)
            {
                LoadFile(file);
            }
        }
    }

    // ---------- 案件 ----------

    private void OnNewCase(object sender, RoutedEventArgs e)
    {
        var panel = new NewCasePanel(
            "给这个案件起个名字（比如案号或当事人），之后可以随时切回来。",
            DateTime.Now.ToString("yyyy-MM-dd") + " 案件");

        panel.Confirmed += (_, _) =>
        {
            HideOverlay();
            _viewModel.CreateCase(panel.Value);
        };
        panel.Cancelled += (_, _) => HideOverlay();

        ShowOverlay(panel);
    }

    /// <summary>右键案件时先把它选中，这样右键菜单针对的就是看得见的那一条。</summary>
    private void OnCaseListRightClick(object sender, MouseButtonEventArgs e)
    {
        if (e.OriginalSource is not DependencyObject source)
        {
            return;
        }

        if (ItemsControl.ContainerFromElement(CaseList, source) is ListBoxItem item)
        {
            item.IsSelected = true;
        }
    }

    private void OnDeleteCase(object sender, RoutedEventArgs e)
    {
        if (CaseList.SelectedItem is not CaseItem item)
        {
            return;
        }

        var panel = new NoticePanel(
            "删除案件",
            $"「{item.Name}」的存档会被删掉，里面的卡片一并消失，删了找不回来。",
            "删除");

        panel.Confirmed += (_, _) =>
        {
            HideOverlay();
            _viewModel.DeleteCase(item);
        };
        panel.Dismissed += (_, _) => HideOverlay();

        ShowOverlay(panel);
    }

    // ---------- 另存为 ----------

    /// <summary>输出卡右上角的「另存为」。sender 的 DataContext 就是那张卡。</summary>
    private void OnSaveMessage(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { DataContext: TurnMessage message })
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(message.Text))
        {
            ShowNotice("这张卡是空的", "还没有可保存的内容。");
            return;
        }

        SaveText(message.Title, message.Text);
    }

    private void SaveText(string suggestedName, string content)
    {
        var stem = Path.GetFileNameWithoutExtension(suggestedName);
        if (string.IsNullOrWhiteSpace(stem))
        {
            stem = "分析结果";
        }

        var dialog = new SaveFileDialog
        {
            Title = "另存为",
            Filter = "文本文件|*.txt|Markdown|*.md|所有文件|*.*",
            FileName = $"{stem}-分析结果.txt",
        };

        if (dialog.ShowDialog(this) != true)
        {
            return;
        }

        try
        {
            File.WriteAllText(dialog.FileName, content, new UTF8Encoding(true));
            _viewModel.StatusText = $"已保存到 {dialog.FileName}";
        }
        catch (Exception ex)
        {
            ShowNotice("保存失败", ex.Message);
        }
    }

    // ---------- 设置 ----------

    private void OnOpenSettings(object sender, RoutedEventArgs e)
    {
        var panel = new SettingsPanel(_viewModel.Settings.Clone());

        // 偏好页里点主题立刻预览；取消就退回原来那档，别把没保存的选择留在界面上。
        panel.ThemePreview += (_, mode) => ThemeService.SetMode(mode);
        panel.Saved += (_, _) =>
        {
            HideOverlay();
            _viewModel.ApplySettings(panel.Result);
        };
        panel.Cancelled += (_, _) =>
        {
            ThemeService.SetMode(_viewModel.Settings.Theme);
            HideOverlay();
        };

        ShowOverlay(panel);
    }
}
