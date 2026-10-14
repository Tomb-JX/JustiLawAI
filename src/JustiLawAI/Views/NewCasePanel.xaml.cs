using System.Windows;
using System.Windows.Controls;

namespace JustiLawAI.Views;

/// <summary>输案件名的小面板。压在主窗口上，确定时名字非空。</summary>
public partial class NewCasePanel : UserControl
{
    /// <summary>点了确定（且名字非空）。</summary>
    public event EventHandler? Confirmed;

    /// <summary>点了取消，或者按了 Esc。</summary>
    public event EventHandler? Cancelled;

    public NewCasePanel(string prompt, string initial = "")
    {
        InitializeComponent();

        PromptText.Text = prompt;
        ValueBox.Text = initial;

        Loaded += (_, _) =>
        {
            ValueBox.Focus();
            ValueBox.SelectAll();
        };
    }

    public string Value => ValueBox.Text.Trim();

    private void OnOk(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(Value))
        {
            ErrorText.Visibility = Visibility.Visible;
            ValueBox.Focus();
            return;
        }

        Confirmed?.Invoke(this, EventArgs.Empty);
    }

    private void OnCancel(object sender, RoutedEventArgs e) => Cancelled?.Invoke(this, EventArgs.Empty);
}
