namespace JustiLawAI.Models;

/// <summary>界面主题。只影响这台机器上的观感，不影响发给模型的内容。</summary>
public enum ThemeMode
{
    /// <summary>跟着 Windows 的浅色 / 深色走（默认）。</summary>
    System,

    /// <summary>固定浅色。</summary>
    Light,

    /// <summary>固定深色。</summary>
    Dark,
}

/// <summary>
/// 应用配置。这是「简单版」的全部可配置面——只够把材料送给模型、把结果拿回来。
/// </summary>
public sealed class AppSettings
{
    /// <summary>OpenAI 兼容接口地址，例如 http://127.0.0.1:8000/v1</summary>
    public string BaseUrl { get; set; } = "http://127.0.0.1:8000/v1";

    /// <summary>本地服务通常留空。</summary>
    public string ApiKey { get; set; } = "";

    public string Model { get; set; } = "justilaw";

    public string SystemPrompt { get; set; } = DefaultSystemPrompt;

    /// <summary>裁量类任务要可复现，默认 0。</summary>
    public double Temperature { get; set; } = 0.0;

    /// <summary>界面主题。老配置文件里没有这一项，反序列化后就是默认的「跟随系统」。</summary>
    public ThemeMode Theme { get; set; } = ThemeMode.System;

    public AppSettings Clone() => new()
    {
        BaseUrl = BaseUrl,
        ApiKey = ApiKey,
        Model = Model,
        SystemPrompt = SystemPrompt,
        Temperature = Temperature,
        Theme = Theme,
    };

    public const string DefaultSystemPrompt =
        """
        你是辅助公安法制审核的助手。用户会给出赌博类行政案件的笔录等材料。

        请阅读材料并输出：

        1. 案件事实摘要
        2. 可认定的事实要素（赌资数额、参赌人数、抽头渔利、是否提供赌博条件、组织形式、前科劣迹、从轻或者减轻情节）。
           每一项都要引用材料原文作为依据；材料没有写明的，写「材料未载明」——不要推测，也不要把没写当成零。
        3. 拟适用的法律条文
        4. 裁量考虑要点

        用中文回答，条理清晰。
        """;
}
