using CommunityToolkit.Mvvm.ComponentModel;

namespace JustiLawAI.Models;

/// <summary>左侧列表里的一个案件。一个案件 = 一个 JSON 存档文件。</summary>
public sealed partial class CaseItem : ObservableObject
{
    public string Name { get; set; } = string.Empty;

    /// <summary>存档文件的完整路径。</summary>
    public string FilePath { get; set; } = string.Empty;

    /// <summary>列表第二行的小字，由 <see cref="Services.CaseStore"/> 按文件时间填。</summary>
    [ObservableProperty]
    private string _summary = string.Empty;

    /// <summary>
    /// 只到日期的短标记（MM-dd）。左栏收起成窄轨时用它顶掉案件名——
    /// 窄轨塞不下名字，日期一眼能认出是哪天办的。同样由 CaseStore 按文件时间填。
    /// </summary>
    [ObservableProperty]
    private string _date = string.Empty;

    /// <summary>
    /// 读到 UI Automation 里就是案件名。默认会暴露成类名，
    /// 屏幕阅读器和自动化脚本都只能看到「JustiLawAI.Models.CaseItem」。
    /// </summary>
    public override string ToString() => Name;
}
