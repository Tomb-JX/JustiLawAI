namespace JustiLawAI.Services;

/// <summary>
/// 调用模型接口失败时抛出。消息是给用户看的，所以必须是人话。
/// </summary>
public sealed class ApiException : Exception
{
    public ApiException(string message, Exception? innerException = null)
        : base(message, innerException)
    {
    }
}
