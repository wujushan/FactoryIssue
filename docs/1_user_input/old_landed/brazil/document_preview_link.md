# 8D 报告预览链接

> 信源：`1_user_input/brazil/8D报告预览链接规则.md` + 业务确认（2026-07-15）。  
> **BASE URL / SecretSalt** 一律 `.env`（或运行配置）注入，**不入库、本文不写明文**。  
> 与制程单跳转（`problem_link.md`）**不是**同一套域名/算法。

## 对用户行为

| 项 | 口径 |
|----|------|
| 可见文案 | **文档名**（`DocumentList.DocumentName`），带**可点击跳转** |
| 谁拼链接 | **本系统**按配置拼出预览 URL |
| 链入主键 | URL 的 `id` = **`DocumentList.ID`**（十进制字符串，不补零）；**无**其它业务字段参与 digest |
| 打开后鉴权 | **不由本系统关注**（目标页自行处理登录/权限） |
| 已删除文档 | `EffectFlag ≠ 0` **排除、不展示**（含不生成链接） |

明细中列出 8D 时：展示可点文档名；全称、扩展名、路径、添加时间等仍可按查询需要附带，**链接锚点文案以文档名为准**。

## URL 形态

```
{DOCUMENT_PREVIEW_BASE_URL}/#/DocumentBusinessView?id={document_id}&digest={digest}
```

| 参数 | 值 | 说明 |
|------|-----|------|
| `id` | `DocumentList.ID` 的十进制字符串 | 明文，不补零；例：`12345` |
| `digest` | `GetDigest(id)` | 防篡改校验串 |

`DOCUMENT_PREVIEW_BASE_URL`：运行配置。**测试与生产均配置为正式生产链接**（不拆两套域名）。

## GetDigest（实现约束）

与源业务系统对齐（信源伪代码语义）：

| 步骤 | 规则 |
|------|------|
| 入参 | `tamperproofparams` = 上述 `id` 字符串（仅 ID，无其它字段） |
| 拼接 | `SecretSalt + tamperproofparams + SecretSalt` |
| 哈希 | UTF-8 编码后做 **MD5** |
| 输出 1 | MD5 结果做 **Base64** |
| 输出 2 | **去掉**尾部 `=` |
| 输出 3 | **去掉**所有 `+`（避免破坏 URL） |

`SecretSalt`：运行配置（`.env`），**禁止**写入仓库或治理正文。

配置项建议名（实现可调整，须可注入、可不入库）：

- `DOCUMENT_PREVIEW_BASE_URL`
- `DOCUMENT_PREVIEW_SECRET_SALT`

## 展示范围（与挂接规则一致）

仅对同时满足以下条件的文档生成预览链接并展示给用户：

| 项 | 口径 |
|----|------|
| `BusinessType` | `巴西制程问题单8D报告` |
| `frecid` | 属于该制程单过程行的 `BrazilProblemProcess.ID` |
| `EffectFlag` | **仅 `0`**（已删除不展示） |

## 与制程单跳转

**无关**。制程单只读页见 `problem_link.md`（AES）；本规则为文档预览页（MD5 digest）。

## 信源原文说明

`1_user_input` 中的示例域名为占位；落地以 `.env` 正式生产 URL 与 Salt 为准。
