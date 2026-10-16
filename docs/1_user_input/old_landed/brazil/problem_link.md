# 制程单跳转链接

> 信源：`1_user_input/brazil/制程单号跳转链接规则.md` + 业务确认（2026-07-15）。  
> **密钥 / IV / 正式域名**一律运行配置注入，**不入库、本文不写明文**。

## 对用户行为

| 项 | 口径 |
|----|------|
| 可见文案 | **`OrderNumber`**（如 `BR2404001`） |
| 交互 | 本系统拼出**可点击跳转链接**（列表、回答中出现制程单号时适用） |
| 链入主键 | 加密入参为 **`BrazilProblemList.ID`**（十进制字符串，不补零），**不是** `OrderNumber` |
| 打开后鉴权 | **不由本系统关注**（目标页自行处理登录/权限） |

## URL 形态

```
{BRAZIL_PROBLEM_BASE_URL}/#/BrazilProblem/AddBrazilProblemPage?type={encrypted_type}&ID={encrypted_id}
```

| 参数 | 明文 | 说明 |
|------|------|------|
| `type` | 固定字符串 `check` | 仅只读查看；**不**支持其它 type |
| `ID` | `BrazilProblemList.ID` 的十进制字符串 | 例：`195` |

`BRAZIL_PROBLEM_BASE_URL`：运行配置。**测试与生产均配置为生产环境 URL**（不拆两套域名）。

`encrypted_*` = `EncryptByAES(明文)`，结果为**大写十六进制**；拼进查询串时**不做** URL-encode。

## EncryptByAES（实现约束）

与源业务系统对齐：

| 项 | 规则 |
|----|------|
| 算法 | AES |
| 模式 | CBC |
| Padding | PKCS7 |
| Key | 运行配置（UTF-8，取前 32 字节） |
| IV | 运行配置（UTF-8，取前 16 字节） |
| 明文编码 | UTF-8 |
| 输出 | 密文字节 → 大写 hex（等价常见 `byte[]`→hex；示例里的 `ByteArrayToHexString`） |

配置项建议名（实现可调整，须可注入、可不入库）：

- `BRAZIL_PROBLEM_BASE_URL`
- `BRAZIL_PROBLEM_LINK_AES_KEY`
- `BRAZIL_PROBLEM_LINK_AES_IV`

## 与 8D 预览

**无关**。8D 文档预览见 `document_preview_link.md`（另一套域名 + MD5 digest）；不与本规则共用 BASE URL / 密钥。

## 信源原文说明

`1_user_input` 中的 key/IV 为**算法示例**；落地以运行配置为准，治理文档与代码仓库**禁止**复制业务密钥明文。
