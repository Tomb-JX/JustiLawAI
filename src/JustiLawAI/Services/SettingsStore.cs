using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using JustiLawAI.Models;

namespace JustiLawAI.Services;

/// <summary>
/// 配置落盘：默认 <c>%APPDATA%\JustiLawAI\settings.json</c>，实际位置由
/// <see cref="AppStorage"/> 选定（首选位置写不进去时会退到别处）。
/// </summary>
public static class SettingsStore
{
    // 枚举写成字符串（"System" / "Light" / "Dark"），跟案件存档一个路子：
    // 光看配置文件就知道是什么，将来枚举顺序变了也不会读错。
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    public static string ConfigPath => AppStorage.SettingsFile;

    public static AppSettings Load()
    {
        try
        {
            if (!File.Exists(ConfigPath))
            {
                return new AppSettings();
            }

            var json = File.ReadAllText(ConfigPath);
            return JsonSerializer.Deserialize<AppSettings>(json) ?? new AppSettings();
        }
        catch (Exception)
        {
            // 配置文件损坏不该让程序起不来，直接退回默认值。
            return new AppSettings();
        }
    }

    public static void Save(AppSettings settings)
    {
        var directory = Path.GetDirectoryName(ConfigPath)!;
        Directory.CreateDirectory(directory);
        File.WriteAllText(ConfigPath, JsonSerializer.Serialize(settings, JsonOptions));
    }
}
