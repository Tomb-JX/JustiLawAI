namespace JustiLawAI.Models;

/// <summary>
/// 一份已经挂到输入区的材料。
/// 它是一个文件，不是一个字符串——内容只在发送时拼进请求，不往输入框里倒。
/// </summary>
public sealed class Attachment
{
    /// <summary>源文件的绝对路径。</summary>
    public required string Path { get; init; }

    /// <summary>显示用的文件名。</summary>
    public required string Name { get; init; }

    /// <summary>读出来的正文。挂载时就定下来，发送前不再读盘。</summary>
    public required string Text { get; init; }

    public int CharCount => Text.Length;

    public string Summary => $"{CharCount} 字";
}
