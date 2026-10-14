using System.IO;
using System.Text;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace JustiLawAI.Services;

/// <summary>
/// 读案件材料。支持纯文本与 Word（.docx）。
///
/// 纯文本：中文笔录在很多单位还是 GBK/GB18030，所以不能直接用 File.ReadAllText——
/// 那样会解出乱码而不是报错，等到送进模型才发现，已经晚了。
///
/// .docx：只取正文里的段落与表格文字，不带样式、批注、修订痕迹。
/// </summary>
public static class DocumentReader
{
    /// <summary>当前支持的扩展名。</summary>
    public static readonly string[] SupportedExtensions =
    {
        ".txt", ".md", ".markdown", ".log", ".csv", ".json", ".xml", ".html", ".htm", ".docx"
    };

    /// <summary>打开文件对话框用的过滤器。</summary>
    public const string FileDialogFilter =
        "案件材料|*.txt;*.md;*.markdown;*.log;*.csv;*.json;*.xml;*.html;*.docx|" +
        "纯文本|*.txt;*.md;*.log;*.csv|" +
        "Word 文档|*.docx|" +
        "所有文件|*.*";

    public static bool IsSupported(string path) =>
        SupportedExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);

    public static string Read(string path) =>
        Path.GetExtension(path).Equals(".docx", StringComparison.OrdinalIgnoreCase)
            ? ReadDocx(path)
            : ReadText(path);

    /// <summary>纯文本：按 BOM → 严格 UTF-8 → GB18030 的顺序判定编码。</summary>
    private static string ReadText(string path)
    {
        var bytes = File.ReadAllBytes(path);

        // 有 BOM 的按 BOM 判，最可靠。
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
        {
            return Encoding.UTF8.GetString(bytes, 3, bytes.Length - 3);
        }

        if (bytes.Length >= 2 && bytes[0] == 0xFF && bytes[1] == 0xFE)
        {
            return Encoding.Unicode.GetString(bytes, 2, bytes.Length - 2);
        }

        if (bytes.Length >= 2 && bytes[0] == 0xFE && bytes[1] == 0xFF)
        {
            return Encoding.BigEndianUnicode.GetString(bytes, 2, bytes.Length - 2);
        }

        // 无 BOM：先严格解 UTF-8（遇到非法字节会抛），失败再按 GB18030（GBK 的超集）解。
        try
        {
            return new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true)
                .GetString(bytes);
        }
        catch (DecoderFallbackException)
        {
            return Encoding.GetEncoding("GB18030").GetString(bytes);
        }
    }

    /// <summary>Word：按文档顺序取每个段落的文字；表格单元格里的段落也在其中。</summary>
    private static string ReadDocx(string path)
    {
        RejectLegacyDoc(path);

        try
        {
            using var document = WordprocessingDocument.Open(path, isEditable: false);
            var body = document.MainDocumentPart?.Document?.Body;
            if (body is null)
            {
                return string.Empty;
            }

            var buffer = new StringBuilder();
            foreach (var paragraph in body.Descendants<Paragraph>())
            {
                foreach (var run in paragraph.Descendants<Text>())
                {
                    buffer.Append(run.Text);
                }

                // 空段落也保留，段间空行是笔录里区分问答的可见结构。
                buffer.Append('\n');
            }

            return buffer.ToString().TrimEnd('\n');
        }
        catch (Exception ex) when (ex is not IOException and not UnauthorizedAccessException)
        {
            // OpenXml 对损坏文件抛的是 InvalidDataException / OpenXmlPackageException 之类，
            // 直接冒出去用户看不懂，这里换成一句能照着做的话。
            throw new InvalidDataException(
                "这个文件没法按 .docx 打开。" + Environment.NewLine +
                "常见原因：文件其实是旧版 .doc（需要另存为 .docx 或 .txt）、" +
                "被 Word 占用、或者是 WPS 的加密文档。" + Environment.NewLine +
                "原始错误：" + ex.Message);
        }
    }

    /// <summary>.doc（OLE 复合文档）的魔数是 D0 CF 11 E0；提前拦下来给一句人话。</summary>
    private static void RejectLegacyDoc(string path)
    {
        using var stream = File.OpenRead(path);
        Span<byte> head = stackalloc byte[4];
        if (stream.Read(head) == 4 && head[0] == 0xD0 && head[1] == 0xCF && head[2] == 0x11 && head[3] == 0xE0)
        {
            throw new InvalidDataException(
                "这是旧版 .doc 文件，不是 .docx。请在 Word 里「另存为」→ 选择 .docx 或 .txt 后再打开。");
        }
    }
}
