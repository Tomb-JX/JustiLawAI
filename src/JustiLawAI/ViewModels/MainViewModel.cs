using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JustiLawAI.Models;
using JustiLawAI.Services;

namespace JustiLawAI.ViewModels;

/// <summary>
/// 主界面的状态与动作。
///
/// 界面是「左侧案件列表 + 中间消息流 + 底部输入区」：一次发送 = 往消息流里追加
/// 一张材料卡和一张输出卡，输出卡边收边写。文件对话框、拖放这类纯 UI 动作留在
/// View 的 code-behind 里。
/// </summary>
public partial class MainViewModel : ObservableObject
{
    private CancellationTokenSource? _cancellation;
    private bool _switchingCase;

    public MainViewModel()
    {
        Settings = SettingsStore.Load();

        var stored = CaseStore.List();
        if (stored.Count == 0)
        {
            stored = new List<CaseItem> { CaseStore.Create(CaseStore.InboxName) };
        }

        foreach (var item in stored)
        {
            Cases.Add(item);
        }

        SelectCase(Cases[0]);

        // 存档没落在首选位置时要说一声，否则用户会去 %APPDATA% 找一个不存在的文件。
        if (AppStorage.FallbackReason is not null)
        {
            StatusText = AppStorage.FallbackReason;
        }
    }

    /// <summary>流式更新或新增卡片后触发，View 据此把消息流滚到底。</summary>
    public event EventHandler? StreamUpdated;

    /// <summary>当前生效的配置。改了之后必须走 <see cref="ApplySettings"/>。</summary>
    public AppSettings Settings { get; private set; }

    public ObservableCollection<CaseItem> Cases { get; } = new();

    public ObservableCollection<TurnMessage> Messages { get; } = new();

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CaseSummary))]
    private CaseItem? _selectedCase;

    /// <summary>待发送的材料。文件就是文件，内容不往输入框里倒。</summary>
    public ObservableCollection<Attachment> Attachments { get; } = new();

    /// <summary>有没有挂材料。列表本身不通知这个，改完手工刷一下。</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SendCommand))]
    private bool _hasAttachments;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(InputSummary))]
    [NotifyCanExecuteChangedFor(nameof(SendCommand))]
    private string _inputText = string.Empty;

    [ObservableProperty]
    private string _statusText = "就绪";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SendCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopCommand))]
    private bool _isBusy;

    public string InputSummary => InputText.Length == 0 ? "空" : $"{InputText.Length} 字";

    public string ModelSummary => $"{Settings.Model} · {Settings.BaseUrl}";

    public string CaseSummary => SelectedCase?.Name ?? CaseStore.InboxName;

    private bool CanSend() =>
        !IsBusy && (!string.IsNullOrWhiteSpace(InputText) || Attachments.Count > 0);

    private bool CanStop() => IsBusy;

    // ---------- 案件切换 ----------

    partial void OnSelectedCaseChanged(CaseItem? value)
    {
        if (_switchingCase || value is null)
        {
            return;
        }

        SelectCase(value);
    }

    private void SelectCase(CaseItem item)
    {
        // 赋值会触发 OnSelectedCaseChanged，这里用开关挡住，免得自己调自己。
        _switchingCase = true;
        try
        {
            SelectedCase = item;
        }
        finally
        {
            _switchingCase = false;
        }

        Messages.Clear();
        foreach (var message in CaseStore.Load(item))
        {
            Messages.Add(message);
        }

        // 空案件不再塞一张「开始一个新案件」的说明卡：新案子进去就是一片空的。
        StatusText = $"{item.Name} · {Messages.Count} 张卡片";
        StreamUpdated?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>新建案件并切过去。名字由 View 弹窗输入。</summary>
    public void CreateCase(string name)
    {
        var item = CaseStore.Create(name);

        var existing = Cases.FirstOrDefault(c => string.Equals(c.Name, item.Name, StringComparison.CurrentCulture));
        if (existing is not null)
        {
            SelectCase(existing);
            StatusText = $"案件「{existing.Name}」已经存在，切过去了";
            return;
        }

        Cases.Insert(0, item);
        SelectCase(item);
        StatusText = $"已新建案件「{item.Name}」";
    }

    /// <summary>删掉一个案件。删不掉就把原因写在状态栏，不假装成功。</summary>
    public void DeleteCase(CaseItem item)
    {
        try
        {
            CaseStore.Delete(item);
        }
        catch (Exception ex)
        {
            StatusText = $"删不掉「{item.Name}」：{ex.Message}";
            return;
        }

        var index = Cases.IndexOf(item);

        // 必须在 RemoveAt 之前判：把手选的案件从集合里摘掉时，ListBox 的
        // SelectedItem 双向绑定会立刻把 SelectedCase 置成 null，
        // 之后再 ReferenceEquals 就永远是 false，整段「删的是当前案件」会被跳过，
        // SelectedCase 停在 null，之后每次发送都静默不落盘。
        var wasSelected = ReferenceEquals(SelectedCase, item);

        if (index >= 0)
        {
            Cases.RemoveAt(index);
        }

        if (wasSelected)
        {
            SelectedCase = null;
            Messages.Clear();

            if (Cases.Count > 0)
            {
                // 删的是中间那条就落回同位置，删的是最后一条就往前挪一格。
                SelectCase(Cases[Math.Min(index, Cases.Count - 1)]);
            }
            else
            {
                // 最后一个案件也删了：把空收件箱建回来，界面不至于空着。
                CreateCase(CaseStore.InboxName);
            }
        }

        StatusText = $"已删除案件「{item.Name}」";
    }

    // ---------- 输入区 ----------

    /// <summary>把一份材料挂到输入区。读不了会抛，由 View 弹窗。</summary>
    public void LoadMaterial(string path)
    {
        var name = Path.GetFileName(path);

        if (Attachments.Any(a => string.Equals(a.Path, path, StringComparison.OrdinalIgnoreCase)))
        {
            StatusText = $"「{name}」已经在待发送里了";
            return;
        }

        var text = DocumentReader.Read(path);

        Attachments.Add(new Attachment { Path = path, Name = name, Text = text });
        HasAttachments = true;
        StatusText = $"已加入 {name} · {text.Length} 字";
    }

    /// <summary>把一份已经读出来的文本挂成材料（拖进来的可能不是文件路径）。</summary>
    public void AddTextMaterial(string name, string text)
    {
        Attachments.Add(new Attachment { Path = name, Name = name, Text = text });
        HasAttachments = true;
        StatusText = $"已加入 {name} · {text.Length} 字";
    }

    [RelayCommand]
    private void RemoveAttachment(Attachment item)
    {
        if (Attachments.Remove(item))
        {
            HasAttachments = Attachments.Count > 0;
            StatusText = $"已移除「{item.Name}」";
        }
    }

    [RelayCommand]
    private void ClearComposer()
    {
        InputText = string.Empty;
        Attachments.Clear();
        HasAttachments = false;
        StatusText = "已清空输入区";
    }

    [RelayCommand]
    private void Stop() => _cancellation?.Cancel();

    // ---------- 发送 ----------

    [RelayCommand(CanExecute = nameof(CanSend))]
    private async Task SendAsync()
    {
        // 材料是文件，拼进请求；输入框里手打的文字跟在后头，当"要模型做什么"。
        var parts = new List<string>();

        foreach (var attachment in Attachments)
        {
            parts.Add($"【材料：{attachment.Name}】\n{attachment.Text}");
        }

        var typed = InputText.Trim();
        if (typed.Length > 0)
        {
            parts.Add(typed);
        }

        var text = string.Join("\n\n", parts);

        var material = Attachments.Count switch
        {
            0 => "直接输入",
            1 => Attachments[0].Name,
            _ => $"{Attachments.Count} 份材料",
        };

        _cancellation = new CancellationTokenSource();
        var token = _cancellation.Token;

        IsBusy = true;
        StatusText = "正在请求…";

        var stamp = DateTime.Now.ToString("HH:mm");

        // 挂进来的文件在界面上就是文件，不摊开；手打的文字直接显示。
        foreach (var attachment in Attachments)
        {
            Messages.Add(new TurnMessage
            {
                Kind = MessageKind.Material,
                IsFile = true,
                Title = attachment.Name,
                Subtitle = $"{attachment.CharCount} 字 · {stamp}",
                Body = attachment.Text,
            });
        }

        if (typed.Length > 0)
        {
            Messages.Add(new TurnMessage
            {
                Kind = MessageKind.Material,
                IsFile = false,
                Title = "直接输入",
                Subtitle = $"{typed.Length} 字 · {stamp}",
                Body = typed,
            });
        }

        var output = new TurnMessage
        {
            Kind = MessageKind.Output,
            Title = material,
            Subtitle = $"{Settings.Model} · 生成中…",
            IsStreaming = true,
        };
        Messages.Add(output);
        StreamUpdated?.Invoke(this, EventArgs.Empty);

        var request = new List<Services.ChatMessage>();
        if (!string.IsNullOrWhiteSpace(Settings.SystemPrompt))
        {
            request.Add(new Services.ChatMessage("system", Settings.SystemPrompt));
        }

        request.Add(new Services.ChatMessage("user", text));

        var buffer = new StringBuilder();
        var clock = Stopwatch.StartNew();

        try
        {
            var client = new OpenAiClient(Settings);
            await foreach (var piece in client.ChatStreamAsync(request, token))
            {
                buffer.Append(piece);
                output.Text = buffer.ToString();
                StreamUpdated?.Invoke(this, EventArgs.Empty);
            }

            clock.Stop();
            output.IsStreaming = false;
            output.Subtitle = $"{Settings.Model} · {buffer.Length} 字 · 用时 {clock.Elapsed.TotalSeconds:F1} 秒";
            StatusText = $"完成 · {buffer.Length} 字 · 用时 {clock.Elapsed.TotalSeconds:F1} 秒";

            // 顺利发出去了才清场：失败时材料和文字都留着，改完能直接重发。
            Attachments.Clear();
            HasAttachments = false;
            InputText = string.Empty;
        }
        catch (OperationCanceledException)
        {
            clock.Stop();
            output.IsStreaming = false;
            output.Text = buffer + "\n\n（已停止，上面是已经收到的部分）";
            output.Subtitle = $"{Settings.Model} · 已停止 · 用时 {clock.Elapsed.TotalSeconds:F1} 秒";
            StatusText = "已停止";
        }
        catch (ApiException ex)
        {
            clock.Stop();
            output.IsStreaming = false;

            // 已经收到的部分留在输出卡里——失败不该把结果一起丢掉。
            output.Subtitle = $"{Settings.Model} · 失败";

            Messages.Add(new TurnMessage
            {
                Kind = MessageKind.Error,
                Title = "调用接口失败",
                Subtitle = $"用时 {clock.Elapsed.TotalSeconds:F1} 秒",
                Text = ex.Message + "\n\n可以这样处理：\n" +
                       "· 到「设置」核对接口地址与模型名（「测试连接」能列出模型就说明地址对了）\n" +
                       "· 确认本地模型服务已经起来；没有模型时可以用 tools\\stub_server.py 先走通链路\n" +
                       "· 输入内容还在输入框里，处理完直接再点「发送」",
            });

            StatusText = "失败";
        }
        finally
        {
            _cancellation.Dispose();
            _cancellation = null;
            IsBusy = false;
            Persist();
            StreamUpdated?.Invoke(this, EventArgs.Empty);
        }
    }

    private void Persist()
    {
        if (SelectedCase is null)
        {
            if (Messages.Count > 0)
            {
                StatusText = "没有选中的案件，这次的记录没能存下来";
            }

            return;
        }

        try
        {
            CaseStore.Save(SelectedCase, Messages);
        }
        catch (Exception ex)
        {
            StatusText = $"留痕写入失败（材料还在，但这次记录没存下来）：{ex.Message}";
        }
    }

    // ---------- 设置 ----------

    /// <summary>设置窗口点「保存」后调用。</summary>
    public void ApplySettings(AppSettings settings)
    {
        Settings = settings;

        // 主题跟着配置走（面板里点选时已经预览过了，这里只是把取消过的预览钉下来）。
        ThemeService.SetMode(settings.Theme);

        try
        {
            SettingsStore.Save(settings);
            StatusText = "设置已保存";
        }
        catch (Exception ex)
        {
            // 设置已经生效（本次运行有效），只是没落盘——说清楚，别假装存好了。
            StatusText = $"设置本次运行有效，但没能写入配置文件：{ex.Message}";
        }

        OnPropertyChanged(nameof(ModelSummary));
    }
}
