using CommunityToolkit.Mvvm.ComponentModel;

namespace JustiLawAI.Models;

/// <summary>消息流里的卡片种类。</summary>
public enum MessageKind
{
    /// <summary>发出去的那次材料（右侧气泡）。</summary>
    Material,

    /// <summary>模型这一次的输出（左侧主卡片）。</summary>
    Output,

    /// <summary>调用失败，带可操作的下一步。</summary>
    Error,

    /// <summary>提示，不参与调用。</summary>
    Notice,
}

/// <summary>
/// 消息流里的一张卡。会被序列化进案件的 JSON 文件，所以属性名就是存档格式的一部分——
/// 改名等于让旧存档读不出来，要改请同时提供兼容读取。
/// </summary>
public sealed partial class TurnMessage : ObservableObject
{
    public MessageKind Kind { get; set; }

    /// <summary>材料卡/输出卡记的是材料名；错误卡记的是短标题。</summary>
    public string Title { get; set; } = string.Empty;

    /// <summary>副标题：材料卡是字数与时间，输出卡是模型名与用时。</summary>
    public string Subtitle { get; set; } = string.Empty;

    /// <summary>材料卡：原文。文件挂进来的那份留着备查，但不往界面上摊开。</summary>
    public string Body { get; set; } = string.Empty;

    /// <summary>
    /// 材料卡：这份材料是「挂进来的文件」还是「手打进去的文字」。
    /// 文件就显示成一个文件（只有名字和字数），手打的文字直接摊开展示。
    /// </summary>
    public bool IsFile { get; set; }

    /// <summary>输出卡：模型输出正文；错误卡：错误说明。流式过程中不断被改写。</summary>
    [ObservableProperty]
    private string _text = string.Empty;

    /// <summary>还在流式接收中——界面上显示转圈。</summary>
    [ObservableProperty]
    private bool _isStreaming;
}
