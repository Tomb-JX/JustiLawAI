using System.Text;
using System.Windows;
using JustiLawAI.Services;

namespace JustiLawAI;

/// <summary>
/// Interaction logic for App.xaml
/// </summary>
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        // .NET 8 默认不带 GB18030。中文笔录大量是 GBK 编码，
        // 不注册这个提供程序，DocumentReader 的编码回退会直接抛异常。
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

        // 主题按配置里存的那一档来（跟随系统 / 固定浅色 / 固定深色）。
        // 必须在 base.OnStartup 之前——StartupUri 指定的主窗口是在 base 之后才创建的。
        ThemeService.Start(SettingsStore.Load().Theme);

        base.OnStartup(e);
    }
}
