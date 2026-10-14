using System.IO;

namespace JustiLawAI.Services;

/// <summary>
/// 决定「配置和案件存档放哪儿」。
///
/// 首选 <c>%APPDATA%\JustiLawAI</c>，但不能假设它一定写得进去：企业策略、
/// 漫游配置异常、杀毒软件的受控文件夹访问，都会让 <c>Directory.CreateDirectory</c>
/// 直接抛 UnauthorizedAccessException。之前主窗口的构造函数里就因为这个把整个软件带崩了。
/// 所以这里按顺序试几个位置，用第一个真能写进去的，并记下为什么退而求其次。
/// </summary>
public static class AppStorage
{
    /// <summary>实际生效的基目录。</summary>
    public static string Root { get; }

    /// <summary>没落在首选位置时的说明，供界面提示用户；正常情况是 null。</summary>
    public static string? FallbackReason { get; }

    public static string SettingsFile => Path.Combine(Root, "settings.json");

    public static string CasesDirectory => Path.Combine(Root, "cases");

    static AppStorage()
    {
        var roaming = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "JustiLawAI");

        var local = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "JustiLawAI");

        var candidates = new List<(string Path, string Reason)>
        {
            (roaming, string.Empty),
            (local, "漫游配置目录不可写"),
            (Path.Combine(AppContext.BaseDirectory, "JustiLawAI-data"), "用户配置目录不可写"),
            (Path.Combine(Path.GetTempPath(), "JustiLawAI"), "前几个位置都不可写"),
        };

        foreach (var (path, reason) in candidates)
        {
            if (string.IsNullOrWhiteSpace(path) || !TryPrepare(path))
            {
                continue;
            }

            Root = path;
            // 只报目录名不报全路径：这行字要挤在输入区那一行里。全路径在设置窗口里能看到。
            FallbackReason = path == roaming ? null : $"{reason}，存档改放 {Path.GetFileName(path)}";
            return;
        }

        // 连临时目录都不行：还能跑，但什么都存不下来。
        Root = Path.GetTempPath();
        FallbackReason = "找不到可写目录，配置与案件记录不会被保存";
    }

    /// <summary>建目录，并真的写一个探针文件——只看目录在不在是不够的。</summary>
    private static bool TryPrepare(string path)
    {
        try
        {
            Directory.CreateDirectory(path);
            var probe = Path.Combine(path, ".writable");
            File.WriteAllText(probe, string.Empty);
            File.Delete(probe);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
