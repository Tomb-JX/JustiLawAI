using System.IO;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using JustiLawAI.Models;

namespace JustiLawAI.Services;

/// <summary>
/// 案件存档：一个案件 = <see cref="Root"/> 下的一个 JSON 文件，里面是那条消息流。
///
/// 放在 %APPDATA% 而不是仓库里，是因为案件材料含个人信息——绝不能进版本库，
/// 也不该因为你换了工作目录就找不到。设置窗口底部会显示这个目录的实际路径。
/// </summary>
public static class CaseStore
{
    /// <summary>第一次打开时用的默认案件名。</summary>
    public const string InboxName = "未归档";

    private static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);

    private static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        // 不转义中文，存档得能直接用记事本读。
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        Converters = { new JsonStringEnumConverter() },
    };

    public static string Root => AppStorage.CasesDirectory;

    /// <summary>按名字倒序列出全部案件（新案件的名字通常带日期，所以看起来就是时间倒序）。</summary>
    public static IReadOnlyList<CaseItem> List()
    {
        var items = new List<CaseItem>();

        try
        {
            Directory.CreateDirectory(Root);

            foreach (var file in Directory.EnumerateFiles(Root, "*.json"))
            {
                var item = new CaseItem
                {
                    Name = Path.GetFileNameWithoutExtension(file),
                    FilePath = file,
                };

                Describe(file, item);
                items.Add(item);
            }
        }
        catch (Exception)
        {
            // 列不出来不该让软件起不来——退化成「一个案件都没有」，用户照样能用。
            return items;
        }

        items.Sort((a, b) => string.Compare(b.Name, a.Name, StringComparison.CurrentCulture));
        return items;
    }

    public static CaseItem Create(string name)
    {
        var safe = Sanitize(name);
        var item = new CaseItem { Name = safe };

        try
        {
            Directory.CreateDirectory(Root);

            var path = Path.Combine(Root, safe + ".json");
            if (!File.Exists(path))
            {
                File.WriteAllText(path, "[]", Utf8NoBom);
            }

            item.FilePath = path;
            Describe(path, item);
        }
        catch (Exception)
        {
            // 存不下来就只留在内存里；Save 时会再报一次，用户能看见。
            item.FilePath = string.Empty;
        }

        return item;
    }

    /// <summary>
    /// 删掉一个案件的存档文件。删不掉就抛出去，让界面如实说，别假装删成功了。
    /// </summary>
    public static void Delete(CaseItem item)
    {
        if (string.IsNullOrEmpty(item.FilePath))
        {
            return;
        }

        if (File.Exists(item.FilePath))
        {
            File.Delete(item.FilePath);
        }

        // 万一上次写盘崩在半路，临时文件也一起清掉。
        var temp = item.FilePath + ".tmp";
        if (File.Exists(temp))
        {
            File.Delete(temp);
        }
    }

    public static List<TurnMessage> Load(CaseItem item)    {
        try
        {
            if (!File.Exists(item.FilePath))
            {
                return new List<TurnMessage>();
            }

            var json = File.ReadAllText(item.FilePath, Encoding.UTF8);
            return JsonSerializer.Deserialize<List<TurnMessage>>(json, Json) ?? new List<TurnMessage>();
        }
        catch (Exception)
        {
            // 存档坏了不该让软件打不开——当空案件继续，原文件留在原地等你自己处理。
            return new List<TurnMessage>();
        }
    }

    public static void Save(CaseItem item, IEnumerable<TurnMessage> messages)
    {
        if (string.IsNullOrEmpty(item.FilePath))
        {
            throw new IOException($"没有可写目录（当前是 {Root}），这次记录没能存下来。");
        }

        Directory.CreateDirectory(Root);

        var json = JsonSerializer.Serialize(messages.ToList(), Json);

        // 先写临时文件再替换：中途崩了也不会留下半截 JSON。
        var temp = item.FilePath + ".tmp";
        File.WriteAllText(temp, json, Utf8NoBom);
        File.Move(temp, item.FilePath, overwrite: true);

        Describe(item.FilePath, item);
    }

    /// <summary>案件名要能当文件名用：去掉路径分隔符与保留字符，长度截到 60。</summary>
    public static string Sanitize(string name)
    {
        var trimmed = (name ?? string.Empty).Trim();

        var invalid = Path.GetInvalidFileNameChars();
        var builder = new StringBuilder(trimmed.Length);
        foreach (var ch in trimmed)
        {
            builder.Append(Array.IndexOf(invalid, ch) >= 0 ? '_' : ch);
        }

        var safe = builder.ToString().Trim('.', ' ');
        if (safe.Length == 0)
        {
            safe = "案件";
        }

        return safe.Length > 60 ? safe[..60] : safe;
    }

    /// <summary>按存档文件的修改时间填列表里的那两行：<c>MM-dd HH:mm 更新</c> 与窄轨用的 <c>MM-dd</c>。</summary>
    private static void Describe(string file, CaseItem item)
    {
        try
        {
            var stamp = File.GetLastWriteTime(file);
            item.Summary = stamp.ToString("MM-dd HH:mm") + " 更新";
            item.Date = stamp.ToString("MM-dd");
        }
        catch (Exception)
        {
            item.Summary = string.Empty;
            item.Date = string.Empty;
        }
    }
}
