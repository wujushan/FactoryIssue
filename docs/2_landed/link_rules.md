# 链接生成规则

回答中的问题编号可跳转到 INFO 制程单页面，国内 CAR 编号可跳转到 CAR 报告页面，附件以文档名称打开预览。

- 站点地址、附件摘要用的 `SecretSalt`、巴西加密用的 AES 密钥与 IV **放运行配置，不写进本文，也不进代码仓库**。
- 站点地址分三项配置：国内 / 海外制程单、巴西制程单、附件预览。当前三项都填同一个 INFO 正式站点地址（下文统一写作 `{INFO_BASE_URL}`）。测试环境与正式环境都配置为正式站点地址，不拆两套。
- 链接参数里的 ID 是内部主键，只出现在 URL 中，不作为文字展示给用户。可点击文字分别用问题编号、文档名称。
- 打开链接后的登录与权限由目标页面自行处理，本助手不负责。CAR 报告页面链接同样如此：对所有用户生成，不看本助手的 CAR 报告权限。

## 制程单跳转链接

| 域 | 地址 |
|---|---|
| 国内 | `https://{INFO_BASE_URL}/#/QualityManage/ProblemDetail?id={ZCTracking_ProblemList.ID}` |
| 海外 | `https://{INFO_BASE_URL}/#/QualityManage/OverseasProblemAllDetail?id={OverseasProblemDetail.Id}` |
| 巴西 | `https://{INFO_BASE_URL}/#/BrazilProblem/AddBrazilProblemPage?type={encrypted_type}&ID={encrypted_id}` |

国内、海外的 `id` 为主键的十进制文本。

### 巴西参数加密

- `encrypted_type = EncryptByAES("check")`
- `encrypted_id = EncryptByAES(BrazilProblemList.ID 的十进制文本)`

`EncryptByAES` 原文（C#）：

```csharp
const string AES_IV = "read from config file";//16位
private const string _key = "read key from config file";//密钥
/// <summary>
/// AES加密算法
/// </summary>
/// <param name="input">明文字符串</param>
/// <param name="key">密钥（32位）</param>
/// <returns>字符串</returns>
public static string EncryptByAES(string input, string key = _key)
{
    byte[] keyBytes = Encoding.UTF8.GetBytes(key.Substring(0, 32));
    using (AesCryptoServiceProvider aesAlg = new AesCryptoServiceProvider())
    {
        aesAlg.Key = keyBytes;
        aesAlg.IV = Encoding.UTF8.GetBytes(AES_IV.Substring(0, 16));

        ICryptoTransform encryptor = aesAlg.CreateEncryptor(aesAlg.Key, aesAlg.IV);
        using (MemoryStream msEncrypt = new MemoryStream())
        {
            using (CryptoStream csEncrypt = new CryptoStream(msEncrypt, encryptor, CryptoStreamMode.Write))
            {
                using (StreamWriter swEncrypt = new StreamWriter(csEncrypt))
                {
                    swEncrypt.Write(input);
                }
                byte[] bytes = msEncrypt.ToArray();
                return ByteArrayToHexString(bytes);
            }
        }
    }
}
```

| 项 | 规则 |
|---|---|
| 算法 / 模式 / 填充 | AES / CBC / PKCS7 |
| 密钥 | 运行配置；取前 32 个字符，再按 UTF-8 编码成 32 字节（AES-256）。配置值须为 ASCII，否则编码后不是 32 字节 |
| IV | 运行配置；取前 16 个字符，再按 UTF-8 编码成 16 字节。配置值须为 ASCII |
| 明文 | UTF-8；`type` 只用 `check`（只读查看），不支持其他值 |
| 输出 | 密文字节转**大写**十六进制；拼进地址时不做 URL 编码 |

## CAR 报告链接（国内）

国内物料问题单关联了 CAR 报告（问题类型为物料问题，且 `ZCTracking_ProblemList.CARID` 有值）时：

```
https://{INFO_BASE_URL}/QualityManage/Vendor/VendorReportOutDetail.aspx?VendorReportOutID={tbIQCreportOut.fid}
```

| 项 | 规则 |
|---|---|
| `VendorReportOutID` | CAR 报告 ID 的十进制文本。即主表 `CARID`，与 `tbIQCreportOut.fid` 相同，生成链接不需要读取 CAR 报告表 |
| 站点地址 | 沿用国内 / 海外制程单那一项配置 |
| 地址形式 | 地址里没有 `#/`，与制程单链接不同，照原样拼接 |
| 摘要 / 加密 | 不需要 |
| 可点击文字 | CAR 编号；CAR 编号为空时用「CAR 报告」 |
| 权限 | 对所有用户生成，不看本助手的 CAR 报告权限；报告页面自行校验 |

`CARID` 为空、或问题类型不是物料问题的单不生成链接，与源系统管理页面一致。「关联了 CAR 报告」统一以「物料问题且 `CARID` 有值」为准：展示 CAR 编号、统计关联数与生成链接用同一判据（见 `privileges.md`「CAR 报告」）。

## 附件预览链接（三域相同）

附件已经对应到 `info.dbo.DocumentList` 的一行时：

```
https://{INFO_BASE_URL}/#/DocumentBusinessView?id={DocumentList.ID}&digest={digest}
```

| 参数 | 取值 |
|---|---|
| `id` | `DocumentList.ID` 的十进制文本，不补零 |
| `digest` | `GetDigest(id)` 的返回值 |

可点击文字用文档名称（`DocumentName`）。`EffectFlag = 1` 的文档不生成链接。各域如何选出文档行见各域业务描述与 `db_description/db_info_dbo_DocumentList.md`。

### GetDigest

入参 `tamperproofparams` 只传上面的 `id`，不拼接制程单号、业务名称或业务记录 ID。

```java
// digest是ID的加密字段，算法如下：
public static String GetDigest(String tamperproofparams)
{
    String Digest = "";
    String input = SecretSalt + tamperproofparams + SecretSalt;
    byte[] hashedDataBytes;
    System.Text.UTF8Encoding encoder = new System.Text.UTF8Encoding();
    System.Security.Cryptography.MD5CryptoServiceProvider md5Hasher = new System.Security.Cryptography.MD5CryptoServiceProvider();
    hashedDataBytes = md5Hasher.ComputeHash(encoder.GetBytes(input));
    Digest = Convert.ToBase64String(hashedDataBytes).TrimEnd("=".ToCharArray());

    //remove  "+" sign because it's creating problems on the url
    Digest = Digest.Replace("+", "");
    return Digest;
}
```

计算顺序：`SecretSalt + tamperproofparams + SecretSalt`，按 UTF-8 取 MD5，再 Base64，去掉末尾的 `=`，并去掉所有 `+`。
