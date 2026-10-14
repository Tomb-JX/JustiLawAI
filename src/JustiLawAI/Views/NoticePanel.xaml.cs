using System.Windows;
using System.Windows.Controls;

namespace JustiLawAI.Views;

/// <summary>
/// 窗口内的提示卡片。给 <paramref name="confirmText"/> 就是「确认」，不给就只有一个「好」。
/// </summary>
public partial class NoticePanel : UserControl
{
    /// <summary>点了确认按钮（确认式的卡片）。</summary>
    public event EventHandler? Confirmed;

    /// <summary>点了取消 / 关掉。提示式的卡片也会走这里。</summary>
    public event EventHandler? Dismissed;

    public NoticePanel(string title, string message, string? confirmText = null)
    {
        InitializeComponent();

        TitleText.Text = title;
        MessageText.Text = message;

        if (confirmText is null)
        {
            ConfirmButton.Content = "好";
            CancelButton.Visibility = Visibility.Collapsed;
        }
        else
        {
            ConfirmButton.Content = confirmText;
            ConfirmButton.Style = (Style)FindResource("MacDangerButton");
        }

        Loaded += (_, _) => ConfirmButton.Focus();
    }

    private void OnConfirm(object sender, RoutedEventArgs e) => Confirmed?.Invoke(this, EventArgs.Empty);

    private void OnCancel(object sender, RoutedEventArgs e) => Dismissed?.Invoke(this, EventArgs.Empty);
}
