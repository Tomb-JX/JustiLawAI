using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using JustiLawAI.Models;

namespace JustiLawAI.Services;

public sealed record ChatMessage(string Role, string Content);

/// <summary>
/// OpenAI 兼容接口的极简客户端。
/// 只做两件事：列模型（用来「测试连接」）、流式对话。
/// </summary>
public sealed class OpenAiClient
{
    // 超时交给 CancellationToken 管：流式响应可能持续几分钟，
    // HttpClient.Timeout 一旦触发会把正在读的流也切掉。
    private static readonly HttpClient Http = new() { Timeout = Timeout.InfiniteTimeSpan };

    private readonly AppSettings _settings;

    public OpenAiClient(AppSettings settings) => _settings = settings;

    /// <summary>接口地址，去掉尾部斜杠后才能安全拼接路径。</summary>
    public string NormalizedBaseUrl => _settings.BaseUrl.Trim().TrimEnd('/');

    /// <summary>拉模型列表。本地服务没起、地址写错、模型名不对，都能在这一步暴露。</summary>
    public async Task<IReadOnlyList<string>> ListModelsAsync(CancellationToken cancellationToken = default)
    {
        using var request = NewRequest(HttpMethod.Get, "/models");
        using var response = await SendAsync(request, cancellationToken).ConfigureAwait(false);

        var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        using var document = JsonDocument.Parse(body);

        var models = new List<string>();
        if (document.RootElement.TryGetProperty("data", out var data) && data.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in data.EnumerateArray())
            {
                if (item.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String)
                {
                    var name = id.GetString();
                    if (!string.IsNullOrEmpty(name))
                    {
                        models.Add(name);
                    }
                }
            }
        }

        return models;
    }

    /// <summary>流式对话：模型每吐一段文本就 yield 一段，界面上就是「一个字一个字往外冒」。</summary>
    public async IAsyncEnumerable<string> ChatStreamAsync(
        IEnumerable<ChatMessage> messages,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var payload = new Dictionary<string, object?>
        {
            ["model"] = _settings.Model,
            ["temperature"] = _settings.Temperature,
            ["stream"] = true,
            ["messages"] = messages
                .Select(m => new { role = m.Role, content = m.Content })
                .ToArray(),
        };

        using var request = NewRequest(HttpMethod.Post, "/chat/completions");
        request.Content = new StringContent(
            JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

        using var response = await SendAsync(request, cancellationToken).ConfigureAwait(false);
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var reader = new StreamReader(stream, Encoding.UTF8);

        while (true)
        {
            var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
            if (line is null)
            {
                break;
            }

            // SSE：只认 data: 行，其余（event:/注释/空行）忽略。
            if (line.Length == 0 || !line.StartsWith("data:", StringComparison.Ordinal))
            {
                continue;
            }

            var data = line[5..].Trim();
            if (data is "[DONE]")
            {
                break;
            }

            var piece = ExtractDelta(data);
            if (!string.IsNullOrEmpty(piece))
            {
                yield return piece;
            }
        }
    }

    /// <summary>从一行 SSE 的 JSON 里取出增量文本。解析不了就返回 null，不打断整个流。</summary>
    private static string? ExtractDelta(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            if (!document.RootElement.TryGetProperty("choices", out var choices)
                || choices.ValueKind != JsonValueKind.Array
                || choices.GetArrayLength() == 0)
            {
                return null;
            }

            if (!choices[0].TryGetProperty("delta", out var delta)
                || !delta.TryGetProperty("content", out var content))
            {
                return null;
            }

            return content.ValueKind == JsonValueKind.String ? content.GetString() : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private HttpRequestMessage NewRequest(HttpMethod method, string path)
    {
        var request = new HttpRequestMessage(method, NormalizedBaseUrl + path);
        if (!string.IsNullOrWhiteSpace(_settings.ApiKey))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _settings.ApiKey.Trim());
        }

        return request;
    }

    private static async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        HttpResponseMessage response;
        try
        {
            response = await Http
                .SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            throw new ApiException($"连不上接口：{ex.Message}", ex);
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ApiException("请求超时。");
        }

        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            var status = (int)response.StatusCode;
            response.Dispose();
            throw new ApiException($"接口返回 HTTP {status}：{Shorten(body)}");
        }

        return response;
    }

    private static string Shorten(string text) => text.Length <= 400 ? text : text[..400] + "…";
}
