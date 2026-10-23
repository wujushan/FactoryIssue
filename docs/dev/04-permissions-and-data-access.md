# 04 · 权限与受控取数（数据查询模块必读）

这一章是数据查询模块的核心，也是三条红线里最容易踩坑的两条：**权限**与**数字处理**。
读完你应能：写对 `field_mappings`、理解行/列权限怎么被自动注入、正确用 `ctx.data` 取数、用沙箱做统计。

## 心智模型：权限落在框架层，不靠你「记得拼」

```
INFO 授权树 ──► AgentNode(privileges) ──► ctx.agent_node
                                              │
manifest.field_mappings ──────────────────────┘   平台构造 ScopedDataAccess
                                                        │
                                                        ▼
你的模块  ── ctx.data.fetch(spec) ──►  按查询表选 dataScope → 注入 row-scope WHERE + 每个列引用过白名单  ──► DataFrame
```

**列级权限管到哪些位置**（`.fetch()` 全覆盖，`.query()` 只有第一格）：

```
              select   filter   order_by   join 的 on   group_by/having   聚合的参数   {"$column"}   裸 where 串
.fetch(spec)    ✅       ✅        ✅          ✅            ✅              ✅          ✅        ⚠️ 不过（打 flag）
.query(...)     ✅       ——        ——          ——            ——              ——          ——        ⚠️ 不过（打 flag）
.raw(sql)       ❌       ❌        ❌          ❌            ❌              ❌          ❌            ❌
```

> 「聚合的参数」那一格是最容易被当成例外的一格：`AVG(salary_amt)` 与 `SELECT salary_amt` **同权**。
> `where` 一次泄露一个 bit，聚合直接返回明文——分组键足够细时，聚合就是投影。

- 权限规则**不是你写的**——是 INFO 按用户下发的 `privileges`，随 `ctx.agent_node` 到达。
- **协议 v1.1：`privileges.dataScope` 按表**——每张表一套 `{name, mode, row, column}`；取数时按你查询的物理表选出对应规则。
- 行级规则的值是**字面量**（如部门 ID `DEPT_1001`）：协议不再有 `${currentUser.*}` 模板占位，「仅当前用户所属部门」等语义由 `level.code` 表达（业务仓自定义），框架不回填用户属性。
- 你写的是 **`field_mappings`**：把协议里的「权限字段」翻译成你库里的「物理列」。
- 你**只能经 `ctx.data` 取数**；DataScopeFilter 在取数前编译进 SQL，你拿不到裸连接、绕不过去。**LLM 永不参与权限判断。**

## 先声明你要用的数据源（`manifest.data_sources`）

取数前，先在 manifest 里声明**本模块用哪些数据源**。这是「别名解耦」的落点：你只认**别名**，
见不到连接串；别名 → 物理库（INFO/ERP 实例、镜像/治理 PG 库）的绑定是平台部署期配置
（`data_sources.json`），你不关心也改不了。

```python
from forge_core.module import DataSourceRef

manifest = ModuleManifest(
    code="MAT",
    name="物料助手",
    data_sources=[
        DataSourceRef(alias="info", kind="sqlserver", description="INFO 物料主数据",
                      tables=["INFODB.dbo.Material"]),
        DataSourceRef(alias="erp",  kind="sqlserver", description="ERP 库存/价格",
                      tables=["ERPDB.dbo.Stock", "ERPDB.dbo.Price"]),
    ],
    field_mappings={...},
)
```

**一个模块可声明多个源**（如物料助手同时用 `info` + `erp`）；跨实例关联在 pandas 里做（见 `.raw()` 与
「双直连」）。G1 原始表的 source **只能是 `info` / `erp`**（一律直连热备副本，不再有直连↔镜像切换的技术决策）；
`forge_mart_<code>` 只在需治理/向量化时作为产物库出现。**不同数据用不同源**是常态，如实声明即可。

声明带来三重保障：

- **启动即校验**：平台启动时检查你声明的每个别名都已在 `data_sources.json` 登记，缺一个就**拒绝启动**
  （`DATA_SOURCE_NOT_REGISTERED`）——别名漂移在上线前就暴露，而不是首个查询才报错。
- **运行期防越库**：`ctx.data` 只放行你声明过的别名；`.query(source=...)` 用了未声明的别名（哪怕平台里
  确实配了别的模块的库）→ 直接 `PermissionDenied`。跨模块数据一律走模块总线，不许越库直查。
- **可对账 + G1 收口冒烟**：`tables` 与 `docs/2_landed/db_description/` 的落盘表一一对应（**表族**例外：同构分库/动态分表
  在 db_description 里一族一份文件，`tables` 仍按实际要连接的具体物理表逐个声明——可连接表图的边端必须是真实的某张表）；G1 收尾由模块仓 MR 上的
  `forge data check`（advisory）真连内网验证 info/erp 可达 + 声明的表/字段真实存在（只读 `information_schema`，
  不碰业务行），开发者不接触数据库账号。见 [06-cli-reference](06-cli-reference.md) 的 `data check`。

### 别名/库/schema/表/列各在哪指定

`data_sources` 与 `field_mappings` 只承载**别名**与**列**两维；库/schema/表在取数调用里给：

| 维度 | 指定位置（`fetch` / `query`） |
|---|---|
| **实例** | **别名**（`data_sources[].alias` → `spec["source"]` / `query(source=...)`）——一别名 = 一台 SQLServer 实例 / 一个 PG database |
| **库名 database** | SQLServer：表名写三段式 `db.schema.table`；PG：由该别名的 DSN 固定（换库=换别名） |
| **schema** | 写进表名（`schema.table`） |
| **表名** | `spec["from"]`（多表时还有 `spec["joins"][].table`）/ `query(table=...)` |
| **物理列** | `field_mappings` 的值（协议字段 → 物理列） |

> 例：`ctx.data.fetch(QuerySpec.model_validate({"source": "erp", "from": "ERPDB.dbo.Stock", "select": ["qty"]}))`
> ——`erp` 定实例、`ERPDB.dbo.Stock` 定库/schema/表、`select` 是物理列。`.query("erp", "ERPDB.dbo.Stock", select=["qty"])` 同理。

### 原始取数直连 info/erp；mart 只用于治理/向量化（G2 判是否需 mart）

原始结构化取数**一律直连 `info`/`erp`**——这两个数据源别名的连接串物理指向各自的**只读热备副本**
（info/erp 各有实时热备份，取一个专用于读，不打主库、无同步延迟）。因此 **G1 原始表的 `source` 只能是 `info` / `erp`**，
不再有「直连 vs 镜像」的逐源权衡。

`forge_mart_<code>`（PG）只在**需要数据治理（清洗/标准化）或非结构化字段向量化**时出现，是这些 profile 的**产物库**
（治理后表 + 向量表），不是原样镜像。**是否需要 mart 是 G2 决策**：据是否需治理/向量化判断（`governance-etl` /
`semantic-retrieval`），落 `docs/decisions/`。`forge_mart_<code>` 的建库/账号由平台运维一次性准备（业务仓够不到，找平台方）。

> 📌 2026-07-10 变更：原「直连原始库 vs 镜像库 是 G2 决策」已作废——
> **原始结构化取数一律直连 info/erp**（只读热备副本），镜像库已退役。

**走治理/向量产物库（mart）时，权限必须能焊回来**：
INFO 的 `privileges` 用的是与库无关的**协议字段**词汇，`field_mappings` 负责把它锚定到你**这个源**的物理列——
所以同一协议字段在原始库和镜像库里的物理列**可以不同**，按别名分别映射即可。但 `field_mappings` 只能**重指已存在的列**，
不能凭空造列，因此治理/ETL 有两条硬义务：

- **透传权限承载列**：任何用户 `privileges` 可能引用的协议字段——row 规则的 `field`、column 白/黑名单的列——
  其物理列**必须存在于镜像库**。治理把它丢了 → 编译时无列可指 → `fail-closed`
  `PermissionDenied`，**不是静默放行**。
- **别把权限维度预聚合掉**：镜像若做预聚合/物化，**不能跨越权限维度聚合**（否则行级过滤失去可施加的粒度）；
  要么把权限维度保留到行级，要么在建 mart 时就等效施加该限制（如物化视图预过滤）。
  > ⚠️ 这条**只管建 mart**，与查询期的 `fetch()` `group_by` 无关——后者安全，因为 `WHERE`（含行级
  > scope）先于 `GROUP BY` 执行。区别在于 mart 是给所有人共用的物化产物，那时还没有「当前用户」。
  > 见下文「聚合与分组」。

## `field_mappings` 怎么写

结构：`{数据源别名: {协议权限字段: 物理列名}}`。写在 manifest 里（别名须是 `data_sources` 里声明过的）：

```python
manifest = ModuleManifest(
    code="SALES_QUERY",
    name="销售查询",
    field_mappings={
        "sales_db": {                 # 数据源别名（= spec["source"] / query(source=)、平台数据源配置的 key）
            "departmentId": "dept_id",   # 协议权限字段 -> 物理列
            "region": "region_code",
            "salesTier": "tier",
        },
    },
)
```

- **左边（协议字段）**：权限规则（`privileges.dataScope[*].table` 的 row/column）引用的字段名，由 INFO/权限协议定义。
- **右边（物理列）**：你数据库表里的真实列名，**可以是中文**（见下文「中文物理列名」）。
- 缺映射就 **fail-closed**：某条 row/column 规则引用的协议字段在这里查不到物理列 → 整个查询被拒绝（`PermissionDenied`），不是「忽略该规则」。所以规则可能用到的字段都要映射齐。

> 协议 v1.1 起行级规则值为**字面量**（如部门 ID），不再有 `${currentUser.*}` 模板；`field_mappings` 只需覆盖
> row/column 规则引用的协议字段即可（不必再为「用户属性回填」预留字段）。

#### 同一别名下不同表的物理列名不同时（表级映射，2026-08-06）

别名内 value 为**字符串** = 源级默认映射；为 **dict** = 该 key 是表名、值是这张表的覆盖映射：

```python
field_mappings={
    "erp": {
        "departmentId": "dept_id",                        # 源级默认（多数表用它）
        "ERPDB.dbo.orders": {"departmentId": "ord_dept"},  # orders 这张表的部门列另有其名
    },
}
```

表级条目**只覆盖同名协议字段**，同别名下的其余源级条目照常生效。表名按**尾段匹配**（写
`orders` / `dbo.orders` / `ERPDB.dbo.orders` 都能命中查询表），与 `dataScope` 的选表规则同源。

**什么时候必须写**：同一 source 下两张表的权限承载列物理名不同时。不写的后果是查 B 表却拿 A 表的
列名去编译 `WHERE`——运气好报 `Invalid column name`，运气不好 B 表恰有同名异义列，那就是**静默的
错误过滤**（查出来的行是错的，且没人看得出来）。

> ⚠️ 多个表名 key 同时命中同一张表（如同时写了 `orders` 与 `ERPDB.dbo.orders`）→ fail-closed
> `AmbiguousFieldMappingError`，框架不猜用哪套。
>
> 主子表（协议 v1.3）里被引用的子表字段、`inherit_parent` 回溯的父表字段，都按**那张表自己**的
> 表级映射解析（表名取四段式协议名的尾段，段数与查询表相同）——父子表的权限承载列不必同名，
> 不同名时照上面的写法给子表补一条表级覆盖即可。

#### 集合字段（`manifest.collection_fields`，协议 v1.3）

INFO 的行级规则可以对「逻辑上是集合」的字段用 `CONTAINS` / `CONTAINS_ANY` / `NOT_CONTAINS`
（如「团队成员包含当前用户」）。协议只定义逻辑语义，**物理存储格式由你登记**——没登记的字段一旦
被这样引用，取数即 `CollectionFieldUnresolved`（fail-closed，协议明令不得退化为子串 `LIKE`）：

```python
collection_fields={"erp": [
    {"field": "followerIds", "format": "delimited"},                    # 源级默认，分隔符默认 ","
    {"field": "teamMembers", "table": "dbo.project_team", "format": "json_array"},  # 仅该表
]}
```

- `field` 是**协议字段**；物理列照旧由 `field_mappings` 给。`table` 空 = 该别名下所有表，非空 = 仅该表
  （尾段匹配，与表级映射同规则），同字段时表级覆盖源级。
- `delimited`：分隔串，**逐元素精确**比较（`U001` 不会命中 `U0010`），不裁剪空白；NULL/空串 = 空集合。
  `separator` 限 1–8 个字符，不得含引号、`% _ [ ] ! \` 与控制字符（它们会拼进 SQL 字面量与 LIKE 模式）。
- `json_array`：标量 JSON 数组，元素按文本比较；仅 PostgreSQL / SQL Server（OPENJSON，兼容级别 ≥130），
  **MySQL 5.6 不支持**。某行的值不是合法 JSON 数组时**整条查询报错**（比协议「该行拒绝」更严，同属 fail-closed）。
- 集合元素只接受字符串或整数（整数按十进制文本比较）；布尔、浮点、null、对象一律 `InvalidOperatorValue`。

#### 中文物理列名（2026-08-12 起支持）

物理列名/表名**可以是中文**——`field_mappings` 的右边、`select`、`filter`、`group_by`、`order_by`、
`joins` 的关联列、`label`、向量化的 `text_columns` 与权限承载列，一律照写：

```python
ctx.data.fetch(QuerySpec.model_validate({
    "source": "erp", "from": "ERPDB.dbo.订单表",
    "select": [{"field": "订单金额", "agg": "SUM", "label": "金额合计"}],
    "group_by": ["部门编码"],
}))
```

框架按方言加引号（SQL Server `[订单金额]`、PG `"订单金额"`），你不用自己引。**授权树里的表名仍由
INFO 下发**，那是协议侧的事，与物理列名无关。

仍然被拒的（**不是针对中文，是针对能改变 SQL 结构的字符**）：

- 引号 `"`、方括号 `]`、分号 `;`、点 `.`（点是表限定分隔符）、**任何空白**（含全角空格 U+3000）；
- **零宽字符**（U+200B 等）——从 Word/Excel 复制列名最常带进来的东西，肉眼完全看不见，故错误信息会
  **点名码位**（`'​'(U+200B)`）；
- **数字开头**（`2024年销量`）——沿用既有约定，需要的话提；
- **超长**：PG 是 63 **字节**（UTF-8 下一个汉字 3 字节 → 21 个汉字到顶），SQL Server 是 128 **字符**。
  超了报错而不是交给 DB——PG 对超长标识符是**静默截断**，截断后要么找不到列、要么撞上另一列。

> 名字一律按 **NFC** 归一后再比较与拼接。所以 `field_mappings` 里的中文列名与 spec 里的即使来自不同
> 输入法/不同文档，也会被认成同一列——这条对**权限判定**尤其要紧（不归一的话黑名单会静默放过它
> 本该拦下的列）。
> 错误类型是 `IdentifierInvalid`（`QuerySpecInvalid` 族，`retryable=True`），**不是**权限错误。

## 权限模型速览（`ctx.agent_node.privileges`）

你通常**只读不改**，但要看懂 fail-closed 边界：

```python
Privileges(
    version="1.0",
    defaultEffect=Effect.DENY | Effect.ALLOW,   # 关键项缺失/异常时的兜底开关
    level=PrivilegeLevel(code=..., description=...),   # 业务仓自定义语义（框架不解释）
    dataScope=[                                  # 协议 v1.1：按表数组
        DataScopeItem(table=TableScope(
            name="inst.db.schema.tbl",           # 四段式全名
            mode=ScopeMode.ALLOW,                # 表级：ALLOW 继续行/列 / DENY 禁表 / None=按 defaultEffect
            row=RowScope(...), column=ColumnScope(...), cell={...},  # cell 预留、暂不解析
        )),
    ],
)
```

- **`privileges` 为 `{}` 或缺失 → 解析为 `None` = 未声明约束 = 全放开**（不会反转成「全拒绝」）。
- **`TableScope`**：`name`（四段式）、`mode`（`ALLOW`/`DENY`/`None`=未给）、`row`/`column`/`cell`。取数按你查询的物理表选出对应 `TableScope`。
- **`RowScope`**：`mode`（`ALLOW` 白名单 / `DENY` 黑名单 / `None`=未给）、`logic`（默认 `OR`）、`rules: list[RuleGroup]`；`RuleGroup(logic, conditions)`，`Condition(table, field, operator, value)`（`value` 为字面量；`table` 可选，见下方主子表），operator ∈ `EQ/NEQ/NE/GT/GE/LT/LE/IN/NOT_IN/LIKE/IS_NULL/NOT_NULL` 与集合类 `CONTAINS/CONTAINS_ANY/NOT_CONTAINS`（需登记 `collection_fields`，见上）。**`row` 只决定本表自身**。
- **`ColumnScope`**：`mode` + `rules: list[ColumnRule(field)]`。
- **表级默认权限**（协议 v1.1）：查询表**未在** `dataScope` 声明、或 `table.mode` 缺失/非法 → 按 `defaultEffect`（`DENY`→整表拒绝、`ALLOW`→放行）；`table.mode=DENY` → 整表拒绝；表名非四段式/重复/歧义 → `fail-closed`（`InvalidTableScopeError`）。
- **`defaultEffect` 兜底范围**：表级（未声明/缺 `table.mode`）、`row` 缺 `mode`、`column` 缺 `mode` 时用 `defaultEffect` 决定放行/拒绝。「`row` 声明了但 `rules` 为空」由 mode 语义决定（空 ALLOW 白名单=拒绝、空 DENY 黑名单=放行）。
- **主子表（协议 v1.3，1.2 的 `row.affect_parent` 已删除且不兼容）**：`TableScope.sub_tables`（最多 3 级）+ 每子表 `relation.mappings`（父子等值关联）。两种联动：
  - **条件引用后代表字段**：`Condition.table` = 某张后代表的四段式全名（严格相等、在后代里唯一）。编成沿 relation 嵌套的 `EXISTS`，判定「存在满足条件的关联行」；**同一条 AND rule 内**引用同一后代表的条件由**同一行**满足（孙表行挂在同一行子表下），OR rule 与不同 rule 各自独立。被引用表自身的 mode/row/column 不参与（基于全部关联行），引用也不授予对它的读取权。
  - **`inherit_parent: true`（子表上）**：子表行仅在至少一行关联父表行**最终可访问**时才可访问，与子表自身 mode/row AND 叠加；整个 `row` 缺失时子表不另加行级限制。只继承直接父表，逐级传递要每一级都开；被继承的父表表级不可访问 → 子表按**表级拒绝**报 `TableDenied`。
  - **子表可被直接查询**：选表在整棵 `sub_tables` 树里找，命中子表就按它自己的 mode/row/column（+ inherit_parent）管控。同一张表在整个 dataScope 里命中多处 → `InvalidTableScopeError`（歧义，不合成）。
  - **fail-closed**：缺 relation / mappings 空 / 超 3 级 / 同父重复子表名 / 条件 `table` 不是非空字符串、不是后代表或不唯一（`InvalidFieldTableReference`）/ 集合操作符 value 形态错（`InvalidOperatorValue`）——**整个 dataScope 一起校验**，坏规则挂在这次没查的表上也中断。
  - 在 `.fetch()` / `.query()` / `.raw()` / `.search()`（`row_scope_sql`）上**全部生效**；`fetch()` 多表查询里每张表各自编译，EXISTS 别名全程共享计数器、互不相撞。
- **`type` 与 KB 项（协议 v1.2）**：`dataScope[*]` 可带 `type`（严格大写 `DB`/`KB`，缺失按 `DB`）。`type=KB` 时用 `directory` 递归目录白名单替代 `table`——**由知识库路径 `ctx.knowledge` 消费，`ctx.data` 的 DB 取数直接跳过 KB 项**；`type` 非 DB/KB 或 DB 项载荷错配（缺 `table`/含 `directory`）→ `fail-closed`。

### 「无 privileges = 全放开」与高敏模块的 opt-in fail-closed

默认语义是**历史兼容的 fail-OPEN**：AgentNode 没带 `privileges`（缺失或 `{}`）→ 不施加任何行/列/表过滤（模块级授权即「用户能否用这个模块」仍由授权树硬校验，不受影响）。这意味着若 INFO **漏发**了本应下发的 privileges，框架会放行而非拦截。

- 是否做数据细粒度管控，**取决于 INFO 下发的 privileges**——取 INFO 授权树是**平台统一负责**的（网关 `AuthProvider.fetch_agent_tree`），业务模块只被动接收注入的 `ctx.agent_node`，自己不碰 INFO。
- 普通模块**无需任何声明**即可享受这套默认（不写 privileges 解析、不写 `field_mappings` 也能取数=全放开）。
- **高敏模块**若不接受「漏发即放行」，在 manifest 里置 **`require_privileges=True`** 显式反转为 fail-closed：privileges 缺失/空时 `ctx.data` 取数直接抛 `PrivilegesRequiredError`。这是业务侧声明、平台侧强制（`bus` 构造 `ctx.data` 时读该标志注入）。

> **📌 行列权限现在是按需取的**（决策 2026-08-29「数据权限按需获取与每助手管控开关」，对业务模块
> 完全透明）：助手树仍一次性取回，但**树里带的 `privileges` 平台不用**——平台在路由目标确定之后、
> 调用你的模块之前，按你的模块编码单独向 INFO 拉一次行列权限，拉不到就直接拒绝该轮（你的 `handle`
> 一行都不会执行）。你拿到的 `ctx.agent_node` 与 `ctx.data` 用法一字未变。三处值得知道的差别：
>
> - `require_privileges=True` 的判据**升级**为「有没有成功拉到」：INFO 明确答复「该助手无行列管控」
>   （空 `Data`）时**放行**，而不再一律拒绝——「漏发」与「确实无管控」终于分得开了；
> - 管理员可在 Console「配置」页**逐助手关闭数据权限管控**，关闭后该助手取数不施加任何表/行/列
>   过滤。排查「为什么这个人能看到全部数据」时，先看这个开关；
> - 知识库权限**不在本次范围**：仍走 `sub_agents` 载体，行为一字未变。



```python
manifest = ModuleManifest(
    code="SALARY_QUERY", name="薪酬查询",
    require_privileges=True,          # 缺 privileges 即拒绝取数，不默认放开
    data_sources=[...], field_mappings={...},
)
```

## 受控取数 `ctx.data`

`ctx.data` 是平台注入的 `DataAccessPort`（实现 = `forge_data.ScopedDataAccess`）。未配数据源时为 `None`，取数前先判空。

三个入口，**受管控的面越往后越窄**——选最靠前那个能干活的：

| 入口 | 形态 | 行级权限 | 列级权限 | 行数上限 | 审计标记 |
|---|---|---|---|---|---|
| `.fetch(spec)` | 声明式 `QuerySpec`（含多表 JOIN、GROUP BY 聚合） | ✅ | ✅ **spec 的每一个列引用位置**（含聚合参数） | ✅ `FORGE_QUERY_MAX_ROWS`，超限**报错** | 无（用了 `raw_where` 才有） |
| `.query(...)` | 单表 + 裸 `where` 串 | ✅ | ⚠️ 只有 `select` | ❌ **不施加** | `where` 非空即 `raw_where` |
| `.raw(sql, ...)` | 手写 SQL | ✅ | ❌ **完全不施加** | ❌ **不施加** | `raw`（+ `select_star`） |

外加一个不取数的 `.describe()`：列出**当前用户**够得着的表与允许的连接，供你（或 LLM）据以组 spec。

> **行数上限只是 `.fetch()` 的安全网，不是平台级的取数闸门。** `.query()` / `.raw()` 不注入
> `TOP`/`LIMIT`、也不判行数——几万行明细要喂进确定性计算（`ctx.stats` / pandas）时，它们照常
> 取得回来，不必为此分批再在内存里合并。代价换成了另外三条，都在你这边：**SQL Server 单条
> 语句最多 2100 个参数**（IN 列表长了得自己切批，平台内部按 2000 一批）、整份结果一次进内存、
> 以及一轮问答的时延（`FORGE_REQUEST_BUDGET_SECONDS` 默认 300 秒是跨模块调用的熔断阈值，
> 不会中途掐断你的 `handle()`，但网关之外的反代与客户端各有各的超时）。
> **十万行以上的明细别走问答期**——那是[后台导出任务](02-sdk-reference.md#后台导出任务ctxfilessubmit_export大批量明细)
> 的活（流式取数、总行数上限按百万级配、边取边写文件）。

### `.fetch(spec)` —— 结构化取数（**推荐，一等形态**）

交一份声明式 `QuerySpec`（pydantic，可直接 `model_validate` 吃下 LLM 吐的 JSON），框架校验后编译成 SQL：

```python
from forge_core.dataquery import QuerySpec

df = ctx.data.fetch(QuerySpec.model_validate({
    "source": "sales_db",                 # = manifest.data_sources 里的别名
    "from": "fact_sales",                 # 物理表名（与 .query(table=) 同源）
    "select": ["region_code", "amount", {"field": "sale_date", "label": "d"}],
    "filter": {
        "logic": "AND",
        "groups": [{"logic": "AND", "conditions": [
            {"field": "sale_date", "operator": "GE", "value": {"$relative": "-30d"}},
            {"field": "status", "operator": "NE", "value": "VOID", "include_nulls": True},
            {"field": "actual_end", "operator": "GT", "value": {"$column": "plan_end"}},
            {"field": "title", "operator": "CONTAINS", "value": "紧急"},
        ]}],
    },
    "order_by": [{"field": "amount", "direction": "DESC"}],
    "limit": 500,
}))   # -> pandas.DataFrame
```

**为什么值得从 `.query()` 迁过来**：`.query(where=...)` 的裸字符串**不过列级白名单**——列级权限禁止你 `select` 的列，你照样能 `where="salary_amt > 50000"` 再从返回行数二分反推它的值。`fetch` 里 `select` / `filter` / `order_by`、以及跨列比较 `{"$column": ...}` 引用的**目标列**，全部过同一个列级白名单，无权即 `ColumnNotPermitted`。

**算子**：`EQ` `NE` `GT` `GE` `LT` `LE` `IN` `NOT_IN` `BETWEEN` `CONTAINS` `STARTS_WITH` `ENDS_WITH` `NOT_CONTAINS` `NOT_STARTS_WITH` `NOT_ENDS_WITH` `IS_NULL` `NOT_NULL`。

- **`include_nulls`**：SQL 是三值逻辑，`status <> 'VOID'` **不包含** `status` 为 NULL 的行，但人和 LLM 的直觉都认为包含。要哪种由你说了算，框架不替你猜。
- **`{"$relative": "-30d"}`**：相对时间由**框架在编译期**解析成字面量（`2026-07-07T00:00:00`）再绑参，不生成 `DATEADD`/`now()`。文法：`now` / `today` / `yesterday` / `tomorrow` / `±<N><d|w|m|y|h|min>`。**日/周/月/年对齐到当天 00:00**（同一天内多次提问得到同一个数字），时/分从此刻起算。月末位移钳到当月最后一天（`3-31` 减一个月 = `2-28`）。
  > **时区 = 服务器本地时区**，平台可用 `FORGE_QUERY_TIMEZONE` 显式覆盖（防 systemd/容器把进程 TZ 拉成 UTC 后静默差 8 小时）——**这是平台侧配置，模块不设**；「`-30d` 怎么差了一天」先查它。解析出的是 **naive 本地墙钟**值（业务库的 datetime 列绝大多数不带时区，绑 aware 值进去会与列类型错配）。
  > `-30d` 的语义是**字面**的「锚点减 30 天」。「近 30 天」在自然语言里含不含今天，由你（或 LLM）决定该写 `-29d` 还是 `-30d`，**框架不猜**。
  > 这条不是便利功能，是补一处正在漏的红线：让 LLM 自己算「30 天前是哪天」**就是让 LLM 做算术**。
- **`CONTAINS`/`STARTS_WITH`/`ENDS_WITH`**：框架负责转义 `%` `_`（SQL Server 还转 `[`，它把 `[abc]` 当字符类而 PG 不会）。你传业务原文就行。
- **`NOT_CONTAINS`/`NOT_STARTS_WITH`/`NOT_ENDS_WITH`**：编译成 `NOT LIKE`，转义规则与肯定形逐字相同。「排除 6004 开头的料号」写 `{"field": "part_no", "operator": "NOT_STARTS_WITH", "value": "6004"}`——**通配符由框架加**，`value` 里传业务原文（自带的 `%` 仍按字面匹配）。
  > ⚠️ `NOT LIKE` 是三值逻辑：`part_no` 为 NULL 的行**不会**被选中。要把空值一并算作「不匹配」，加 `"include_nulls": true`。
- **边界原则：AST 里只有比较，没有计算。** `qty * price > 1000`、`DATEDIFF(...) > 30` 这类**不进 filter**——小数据交 `ctx.stats` 沙箱，大数据走 `governance-etl` 在 mart 落**派生列**再回到普通比较。真绕不过时用 `raw_where`（见下）。

**两处与 `.query()` 刻意不同的语义**：

1. **行数上限**：不给 `limit` 时施加平台上限 `FORGE_QUERY_MAX_ROWS`（默认 10000），**超限报错**（`RowLimitExceeded`）而非静默截断。被截断的行喂进 `ctx.stats` 就是**错的统计数字**。要更多就显式给 `limit`（仍不得超过上限），或把聚合下推。
   > 这条上限**只在 `.fetch()` 上**：`.query()` / `.raw()` 不施加（见上表）。它也**不能按模块或按数据源调高**——
   > `FORGE_QUERY_MAX_ROWS` 是平台进程级配置，`limit` 显式写成比它大的数同样被拒（fail-closed，上限的意义就是没人能绕过）。
   > 确实需要上万行明细：这条链路改用 `.raw()`，或把量级交给[后台导出任务](02-sdk-reference.md#后台导出任务ctxfilessubmit_export大批量明细)。
2. **`limit`/`offset` 是框架编译的**，方言差异（PG `LIMIT/OFFSET` vs SQL Server `OFFSET..FETCH NEXT`）你不用管。

> **表级无权曾是第三处，2026-08-06 起不再是**：`.fetch()` / `.query()` / `.raw()` **一律抛 `TableDenied`**。此前 `.query()` 是编译成 `WHERE 1 = 0` 再照发，你拿到一个空 DataFrame——那是「静默少报」：你和 LLM 都会以为「数据不存在」而不是「你没权限」，然后把这个错误结论复述给终端用户。
> 唯一例外是 `.row_scope_sql()`：它不执行、只交出一段 WHERE 给向量检索并进更大的 SQL，仍编译成 `1 = 0`。判据一句话——**执行取数的方法抛错，产 SQL 片段的方法 `deny_all`**。

**裸 `raw_where` 仍可用、与 `filter` 以 AND 共存**——强制二选一没人会迁，能把 80% 谓词挪进结构化、剩那条怪的留在裸串，迁移才可能真的发生。代价是它照打 `raw_where` 审计 flag：

```python
QuerySpec.model_validate({
    "source": "sales_db", "from": "fact_sales", "select": ["id"],
    "filter": {"groups": [{"conditions": [{"field": "status", "operator": "EQ", "value": "OPEN"}]}]},
    "raw_where": "DATEDIFF(day, plan_end, actual_end) > 30",   # ← 打 raw_where flag
    "raw_params": {},
})
```

> ⚠️ 参数名保留前缀：`scope_` / `st<N>_` / `t<N>s_` / `_forge_p` 由权限与 spec 编译占用。`raw_params` 用了会**直接报错**（不静默覆盖——被悄悄吃掉的参数会让查出来的行是错的且没人看得出来）。

**出错了怎么改**：错误带 `retryable` 位，区分「换个写法能成」（`ColumnNotPermitted`、`QuerySpecInvalid` 族）与「这条路根本不通」（`TableDenied`）。多轮重试时用 `SpecRepairLog` 累积负面约束，别让 LLM 死磕同一条：

```python
from forge_core.dataquery import SpecRepairLog

log = SpecRepairLog()
for _ in range(3):
    try:
        df = ctx.data.fetch(build_spec(hint=log.as_prompt()))
        break
    except Exception as exc:
        if not log.record(exc):     # 返回 False = 不可重试，别再撞了
            raise
```

`log.as_prompt()` 产出的约束块只说「什么不可用 / 有什么可用」，**绝不说为什么**——不出现 `dataScope`、`mode`、规则值、`defaultEffect`。把权限模型漏进 LLM 上下文，它就会复述给终端用户。

#### 多表 JOIN（`INNER` / `LEFT`）

先在 manifest 声明**哪些表可以互连**，`fetch()` 才允许连——LLM 只能在这张声明图内组 spec，越界即 `JoinNotDeclared`：

```python
from forge_core import DataSourceRef, JoinEdge

data_sources = [DataSourceRef(
    alias="sales_db",
    tables=["SALESDB.dbo.fact_sales", "SALESDB.dbo.dim_customer"],   # 声明了 joins 就必须写它
    joins=[JoinEdge(
        left="SALESDB.dbo.fact_sales",
        right="SALESDB.dbo.dim_customer",
        on=[("customer_id", "id")],       # 复合键写多条；两侧同名可简写成 "customer_id"
        types=["INNER", "LEFT"],          # 省略 = 两者都允许
        description="订单 → 客户主数据",
    )],
)]
```

```python
ctx.data.fetch(QuerySpec.model_validate({
    "source": "sales_db",
    "from": {"table": "SALESDB.dbo.fact_sales", "alias": "s"},   # 多表时每张表必须有 alias
    "joins": [{
        "table": {"table": "SALESDB.dbo.dim_customer", "alias": "c"},
        "type": "LEFT",
        "on": [{"left": "s.customer_id", "right": "c.id"}],
    }],
    "select": ["s.amount", "c.name"],      # 多表时列引用必须限定别名
}))
```

规则与注意事项：

- **边是无向的**，声明一次两个方向都能连；**关联列必须与声明完全一致**（不是子集）——漏写复合键的一半在 SQL 里完全合法，只会**静默**多关联出一堆行。
- **不声明 = 该源不支持 JOIN**（单表 `fetch` 不受影响）。没审过的连接不放行，不是「没声明就随便连」。
- **不做跨 source join**：一个 spec 一个 `source`。跨实例（如 info + erp）仍走双直连 + pandas 关联。
- **不做非等值 join**（`ON a.d BETWEEN b.lo AND b.hi`）。
- **join 里任一张表无权 → `TableDenied`，拒绝整个查询**，不是把该表的列返 NULL（那等于把权限从「不出库」降级成脱敏）。
- **`alias` 只是逻辑键，永不进 SQL 文本**：真实 SQL 里的别名一律**框架自造**——取物理表名的尾段（`SALESDB.dbo.fact_sales` → `[fact_sales]`，撞名时 `_2`、`_3` 递增），算不出合法别名时退回 `_forge_tN`。所以你在审计归档 `queries.json` 里读到的 SQL 是 `[fact_sales].[amount]`，**照物理表名读即可，不必回头翻别名表**。
- **两张表都有 `id`/`name`/`code` 时框架自动消歧**（2026-08-12）：`select: ["o.id", "c.id"]` 拿回的 DataFrame 列名是 `o_id` 与 `c_id`（`<别名>_<列名>`），不必回头给每一项补 `label`。没撞名的列**列名不变**。
  > 最终列名以 `forge_core.dataquery.resolve_result_names(spec.select)` 为准——`df[...]` 请照它取，别照 `select` 里的原始写法猜。写了 `label` 的项一律以 `label` 为准，框架不动它。
  > 仍会报 `QuerySpecInvalid` 的两种：**两处显式 `label` 起成同一个名字**（那是你亲手起的，改哪个由你说了算），以及**单表下重复选了同一列**（没有别名可用，改名只会掩盖「选重了」）。
- **关联键（ON 里的列）与投影列同权**，无豁免——`ON s.dept_id = d.id` 配上可读的 `d`，就是把被禁的 `dept_id` 以「部门名称」的形式明文读出来，跟 `select dept_id` 没区别。
  > 按业务方约定（2026-08-06 确认），**不论白名单还是黑名单模式，关联列一定在允许访问范围内**（唯一例外是「整张关联表都不许访问」，那走 `TableDenied`）。所以这条**正常不该撞上**；真撞上了报的是 `ColumnNotPermitted` 且 `detail.position="join_on"` + 专门的 hint——那是**权限配置漂移**的信号，拿着它去找 INFO 把该列纳入列级授权，不要当成框架 bug。

##### ⚠️ 一条必须知道的非对称性：scope 进 `ON`，业务 filter 进 `WHERE`

```sql
SELECT ... FROM [SALESDB].[dbo].[fact_sales] AS [fact_sales]
  LEFT JOIN [SALESDB].[dbo].[dim_customer] AS [dim_customer]
       ON [fact_sales].[customer_id] = [dim_customer].[id]
      AND ([dim_customer].[dept_id] = :t1s_0)      -- ← 被连接表的**权限** scope 在这里
 WHERE (<你的 filter>) AND ([fact_sales].[dept_id] = :t0s_0)   -- ← FROM 表的 scope 在这里
```

- **框架加的行级 scope**：被连接表的那份编译进它自己的 `ON`。所以 **`LEFT JOIN` 不会退化**——关联表的行即使全被权限滤掉，主表的行照样在，只是关联列为 `NULL`。若把它放进 `WHERE`，你有权看的订单会因为它关联的客户你无权看而**整行消失**，然后助手一本正经地说「你只有 3 个订单」。静默少报比报错危险得多。
- **你写的业务 `filter`**：引用被 `LEFT JOIN` 表的列时**仍然进 `WHERE`**，因而**仍然会把 LEFT 退化成 INNER**（`WHERE c.region = 'HD'` 会滤掉所有 `c` 侧为 NULL 的行）。

这条区分是**刻意的**：scope 是你看不见的、框架偷偷加的，框架有义务不让它改变你查询的形状；而 filter 是你显式要求的过滤，框架不该替你改语义。要「保留无客户的订单、同时按客户地区过滤」，标准 SQL 的答案是把该条件写进 `ON`——但 `on` 只接受列对列的等值关联，所以这种场景请拆成两次查询，或在 `governance-etl` 里落一张宽表。

#### 聚合与分组（`GROUP BY` / `HAVING`）

```python
ctx.data.fetch(QuerySpec.model_validate({
    "source": "sales_db", "from": "fact_sales",
    "select": [
        "region_code",                                             # 分组键
        {"field": "amount", "agg": "SUM"},                         # → 结果列 sum_amount
        {"agg": "COUNT"},                                          # COUNT(*) → count_star
        {"field": "customer_id", "agg": "COUNT", "distinct": True}, # → count_distinct_customer_id
        {"field": "amount", "agg": "AVG", "label": "avg_ticket"},   # 显式列名
    ],
    "filter": {"groups": [{"conditions": [
        {"field": "sale_date", "operator": "GE", "value": {"$relative": "-30d"}}]}]},
    "group_by": ["region_code"],
    "having": {"groups": [{"conditions": [
        {"field": "amount", "agg": "SUM", "operator": "GT", "value": 100000}]}]},
    "order_by": [{"field": "amount", "agg": "SUM", "direction": "DESC"}],
    "limit": 10,
}))
```

聚合函数是闭集：`COUNT` `SUM` `AVG` `MIN` `MAX`（外加 `COUNT(*)` 与 `COUNT(DISTINCT col)`）。

- **`filter` 进 `WHERE`（分组之前），`having` 进 `HAVING`（分组之后）**。按明细过滤写 `filter`，按聚合结果过滤写 `having`；`filter` 里放 `agg` 会被拒（那时聚合值还不存在）。
- **`having` 与 `order_by` 都能带 `agg`**——`ORDER BY SUM(amount) DESC LIMIT 10`（「金额最高的 10 个地区」）是 SQL 侧一句话的事，拉回全部分组再排则可能直接撞行数上限。
- **结果列名由框架定且恒定发 `AS`**：`sum_amount` / `count_distinct_customer_id` / `count_star`，给了 `label` 就用 `label`。不这么做的话 `AVG(x)` 的列名由驱动决定，你的 `df["…"]` 会炸。**结果列名重复即报错**（含多表下两张表都有 `id` 这种），解法是给其中一项 `label`。
- **既非聚合、又不在 `group_by` 里的列 → `GroupByIncomplete`**（`select` / `order_by` / `having` 三处都查）。这是把数据库那句方言相关的报错提前成一个能照着改的结构化错误，`detail` 给 `missing` 与当前 `group_by`。
- **`select` 里出现聚合就进入分组语义**，哪怕没写 `group_by`（整表算一组），此时再混一个裸列同样非法。
- **`distinct=True` 时，`order_by` 的每一项都必须同时出现在 `select` 里** → 否则 `DistinctOrderByInvalid`。`SELECT DISTINCT` 先去重再排序，被去掉的列上没有确定的排序值（SQL Server Msg 145 / PG 同义报错），框架在编译期就拒。**不写 `order_by` 则无需操心**：分页所需的排序由框架补，且补的一定是投影里的表达式。

> **⚠️ 聚合参数与投影列同权**：`AVG(salary_amt)` 与 `SELECT salary_amt` 过同一个列级白名单，无权即 `ColumnNotPermitted`。这比裸 `where` 那个 oracle 严重一个量级——`where` 一次泄露一个 bit，**聚合直接返回明文**：`AVG(salary_amt) GROUP BY employee_id` 把每个人的工资原样给了出去。**分组键足够细时，聚合就是投影。**

**SQL 下推 vs `ctx.stats` 沙箱**（数字红线的分工，与 [07 · `stats-sandbox`](07-capability-profiles.md) 同一口径）：

> 红线禁的是**谁产出数字**，不是**哪里出现算术**。禁的两件事没变：LLM 自己报数、`handle()` 里用 Python/pandas 直算。SQL 引擎与 `ctx.stats` 沙箱**同属确定性执行器**——同一份输入必得同一个数、过程可复现可审计，都不在禁止之列。
> 分工判据：**这个聚合能否用「表里已有的列 + COUNT/SUM/AVG/MIN/MAX」表达完？**
> 能 → **优先**下推 SQL（数据在 DB 侧就收敛，更快，也让更少的无关行离开数据库）；
> 不能（同比环比、分档、加权、跨源）→ `ctx.stats` 沙箱。
> 两条路通向同一条不变量：**LLM 只能引用执行器的产出，永远不许自己报数**——包括「顺手心算一下百分比」。

**查询期 `GROUP BY` ≠ ETL 期预聚合**（上文「原始取数直连 info/erp」一节那条「别把权限维度预聚合掉」是针对**建 mart** 的，别混为一谈）：查询期聚合安全，**因为 `WHERE` 先于 `GROUP BY` 执行**——行级 scope 就编译在 `WHERE` 里，聚合看到的一定是已经过滤完的行。而 mart 是**给所有人共用的物化产物**，那时还没有「当前用户」，跨权限维度聚合掉就再也没有可施加行级过滤的粒度了。

#### `describe()` —— 我能查哪些表、它们怎么连

```python
catalogs = ctx.data.describe()             # 或 describe("sales_db") 只看一个源
prompt = "\n\n".join(c.as_prompt() for c in catalogs)
```

同一张声明图，**一个产物两用**：既是 `fetch()` 的 JOIN 白名单，也是喂给 LLM 的目录。让 LLM 先看目录再组 spec，比让它猜、猜错吃拒绝要省一整轮。

- **按当前用户过滤**：表级无权的表**不出现**在目录里（不是标记成「无权」），两端有任一表不可见的边也随之消失——LLM 于是不会提出注定 `TABLE_DENIED`（不可重试）的方案。
- **可用列只在列级权限是 `ALLOW` 白名单时才有**（那份白名单本身就是权威清单）；其余情况留空并明说「未声明」——**框架绝不猜一份列清单**，猜出来的列 LLM 会照着写，然后每一条都撞 fail-closed。
- **零 DB 往返**：数据全部来自声明（manifest + privileges），不做运行期 `information_schema` 探测。表结构的权威信源仍是 `docs/2_landed/db_description`。
- 目录里的 `alias` 是**框架建议**的 spec 别名（取表名尾段），不是你声明的。

### `.query()` —— 单表/视图参数化查询（简写）

```python
df = ctx.data.query(
    "sales_db",                       # source：field_mappings 的数据源别名
    "fact_sales",                     # 物理表/视图名
    select=["region_code", "amount"], # 请求的物理列（**必填**，禁止全列选取 SELECT *）
    where="sale_date >= :since",      # 业务过滤，参数化占位符 :name
    params={"since": "2026-07-01"},
)   # -> pandas.DataFrame
```

框架自动做的事：

- 按你查询的物理 `table` 从 `dataScope` 选出对应 `TableScope`；表级 `DENY`（含未声明表按 `defaultEffect=DENY`）→ **抛 `TableDenied`，取数前即阻断**（2026-08-06 行为变更，此前是编译成 `WHERE 1 = 0` 照发、返回空 DataFrame）。
- 把该表的 row-scope 编译成 `WHERE`，与你的 `where` 以 `AND` 合并（规则值为字面量，无需用户上下文）。
- 按 column-scope **校验** `select`：请求了无权列 → 抛 `ColumnNotPermitted`（**不是静默裁掉**，2026-08-06 起）。
- **fail-closed**：表名非四段式/歧义 / 规则字段缺映射 / 请求了无权列 → 抛 `PermissionDenied` 子类，拒绝整个查询。

> **请求无权列会报错，不会悄悄少一列**（2026-08-06 行为变更）。此前列级 DENY 会把该列从 `select`
> 里静默裁掉，于是 `select=["a","b"]` 拿回只有 `a` 的 DataFrame 且不报错，下游 `df["b"]` 抛
> `KeyError`——报错现场离根因十万八千里。现在直接 `ColumnNotPermitted`，`detail` 里给出被拒列
> （ALLOW 模式下还给可用列清单），调用方可据此改写重试。

> **`select` 一律必填（方案 B 防越权红线）**：`select=None` / `select=[]` 一律被拒（`PermissionDenied`）——
> 每个取数场景都得清楚自己要哪些字段，**绝不全列选取（`SELECT *`）**。即便当前无列级权限也强制：
> 一旦 INFO 后续下发列级权限，`SELECT *` 会把新禁列一并带出。确需手写多表 SQL 用 `.raw()`（见下）。

> ⚠️ **`where` 是受监管的裸字符串**（2026-08-06 起每次调用打 `raw_where` 审计 flag）。两个已知的洞：
> ① 它**不过列级白名单**——列级权限禁止你 `select` 的列，你照样能 `where="salary_amt > 50000"`
> 再从返回行数二分反推，即「无权数据不出库」在这里退化成了「无权数据不出投影」；
> ② 它能写子查询，绕过 `data_sources` 别名白名单与 `dataScope`。
>
> 这两个洞**只能靠迁移到结构化过滤关掉、不能靠加固关掉**（正则猜 SQL 文本对注释/子查询脆弱，
> 2026-07-28 决策已否决）。所以：`where` 会长期保留、可与结构化过滤并存，但打点会一直在，
> **退役看遥测不看时间表**。审计页有独立的「裸 where」列（蓝色，与越权面的告警色分开——它是
> 迁移欠债不是越权面）。**新代码请直接用 [`.fetch(spec)`](#fetchspec--结构化取数推荐一等形态)。**

### `.raw()` —— 逃生阀（手写多表 SQL，⚠️ 不稳定 API）

> ⚠️ **尽量别用，随时可能被弃用/禁用。** `.raw()` **只施加行级权限、不施加列级裁剪**——手写 SQL 的
> 投影平台无从裁剪，全列/越权列都可能带出，属越权面。每次调用都会：① 打 `WARNING` 日志留痕；
> ② 在查询审计里标记 `raw`（内层若是 `SELECT *` 再加标 `select_star`），被 Admin 审计页**高亮监控**
> （会话/消息级「取数风险」列 + 告警底色）。确实绕不过时才用，并把 SQL 收窄到必需的列。

> ⚠️ **同源多表 join 不再是用它的理由**（2026-08-06 起）：`fetch()` 原生支持 `INNER`/`LEFT` JOIN 且
> 列级权限管到每一个列引用位置——**先看 `.fetch()` 能不能表达，再考虑这里**。
> 剩下真正属于 `.raw()` 的只有两类：**跨 source**（如 info + erp 两个实例，`fetch` 一个 spec 只认一个
> source），以及**声明图与 spec 表达不了的形状**（非等值 join、窗口函数、`UNION` 等）。
> 跨 source 优先仍是「逐源 `.fetch()` 各自取数 + pandas 关联」，那条路两侧的列级权限都在。

上述两类场景下用它，**行级权限仍强制施加**（把你的 SQL 包成子查询、外层注入编译后的 scope WHERE），并登记进查询审计：

```python
df = ctx.data.raw(
    "SELECT a.region_code, b.name FROM sales a JOIN dim_region b ON a.region_code=b.code",
    params={},
    source="sales_db",
    scope_on="region",     # 承载 row-scope 的协议字段；子查询须暴露其映射到的物理列
    table="fact_sales",    # dataScope 按表：选出该表的行级规则注入外层 WHERE
)
```

- 子查询**必须暴露** scope 规则引用的物理列（否则外层注入的 WHERE 失效）。暴露不了就改用 `.fetch()` 逐源预过滤后再在 pandas 里关联。
- **行数上限不施加**：`FORGE_QUERY_MAX_ROWS` 只管 `.fetch()`，这里不注入 `TOP`/`LIMIT`、也不判行数，上万行的明细取得回来（限制换成了 SQL Server 的 2100 参数上限、内存与本轮时延，见上文表格下的说明）。
- **主子表规则在这条路径上同样整段生效**（协议 v1.3 起）：条件引用子表字段、`inherit_parent` 的 `EXISTS` 经外层包装别名 `_forge_scoped` 回指你的 SQL，故子查询还须**暴露 relation 的关联列**（如 `id`），暴露不全 DB 报错。1.2 时代这里只施加「扁平」部分；v1.3 下略去一条 AND rule 里的子表条件只会放行更多行，所以不能再略。
- 双直连 + pandas 跨库关联时，等效过滤**必须发生在数据进入 LLM 上下文/业务逻辑之前**。
- `table` 表级无权 → **抛 `TableDenied`**（2026-08-06 起，与另两个入口统一）。逃生阀更该抛：`table` 只用来选行级规则，你手写的 SQL 实际读了哪几张表平台无从得知，给你一个空结果集只会让你分不出「是我 SQL 写错了还是我没权限」。

### `.row_scope_sql(source, table)` —— 给检索复用行级权限

平台用它把行级权限焊进语义检索路径（见下）。**模块日常不用直接调**——`ctx.retrieval` 内部已经调了；
只有自备索引实现等高级场景才需要自己拿这对 `(where, params)` 传给 `retrieve(...)`。

> 这是**唯一**表级无权仍编译成 `1 = 0`、不抛 `TableDenied` 的方法：它不执行、只交出一段 WHERE
> 给调用方并进更大的检索 SQL，消费方是**召回形态**（空结果本就是正常结果）。判据一句话——
> **执行取数的方法抛错，产 SQL 片段的方法 `deny_all`。**

```python
where, params = ctx.data.row_scope_sql("forge_mart_kb", "kb_chunks")   # 按被检索的物理表选行级规则
```

## 语义检索（`semantic-retrieval`）

**用平台注入的 `ctx.retrieval`**（仅声明了该 profile 的模块拿得到）：

```python
hits = await ctx.retrieval.search(
    request.query,
    source="forge_mart_kb",          # manifest.data_sources 声明的别名（向量库=普通 PG 库，别名同一族）
    table="kb_chunks",         # 向量表物理名；同时用于按表选出行级规则
    top_k=50, top_n=10,        # 召回 50 → 本地 rerank 后返 10
)
for h in hits:
    ...  # h.id / h.text / h.score / h.metadata
```

行级权限由平台经 `row_scope_sql(source, table)` 编译后**随近邻检索一并下推**为 WHERE——
无权向量根本不出库（不是取回后再过滤）。embedding/rerank 客户端与向量库连接由平台按部署配置装配。

红线与注意事项：

- Embedding/Rerank 仅本地服务（Qwen3-Embedding-8B / Qwen3-Reranker-8B），由平台配置，模块不碰 endpoint。
- **禁止自己 new `PgVectorIndex` / `EmbeddingClient`、禁止自己读 env 拿连接串或 endpoint**：
  自造的检索没有权限 WHERE、也不进审计归档——等于把红线绕过去。
- `ctx.retrieval is None` = profile 没声明（查 [07](07-capability-profiles.md)）或平台没配 embedding 服务
  （找平台侧）。**不要自己造一个顶上。**
- **权限透传是前提，但你不用自己扛**：行级规则是在**向量表**上编译的，故向量表必须带上权限承载列
  （`field_mappings[<mart 别名>]` 的物理列）、不得跨权限维度预聚合。**声明 `manifest.vectorize` 即可
  把这件事交给平台**——它据 `field_mappings[source]` 自动生成 DDL 的 scope 列、回填 SQL 的 SELECT 列表，
  你不写向量化代码，也就没有漏 SELECT 的机会（见 [07](07-capability-profiles.md#semantic-retrieval非结构化字段语义检索--跨-g2--需平台侧前置)）。
  自写向量化 job 仍可行，但透传就回到「靠你记得」——不推荐。
  平台启动时经 `information_schema` 扫出 `forge_mart_<code>` 库里的每张向量表（含 pgvector 列的表），
  校验它们带齐 `field_mappings[<mart 别名>]` 的**全部**物理列，**缺列即拒绝启动**
  （`VECTOR_SCOPE_COLUMNS_MISSING`）——漏透传在部署期就挡下，不再等到首次检索时 42703 崩。
  - 要求「全部 values」是因为哪条规则下发由 INFO 运行期决定：既然声明了某协议字段在该别名下受管控，
    向量表就得随时接得住引用它的规则。某列确实无关 → 从 `field_mappings` 删掉，而不是让向量表少一列。
  - 推论：**同一 mart 别名下的向量表权限口径必须一致**。确实无需权限管控的向量库，就别给它填
    `field_mappings`（该别名整体跳过校验）；与受管控向量表混在同一别名下是建模错误。

### ⚠️ 行级 vs 列级：检索路径上两者待遇不同

**行级**：如上，编译成 WHERE 随近邻检索下推，与 `.query()` 同一套产物、同等严格。

**列级（`dataScope.column`）：当前不作用于检索路径。** 同一个 AgentNode、同一张表，走取数会被列级
拒绝（`.fetch()` 管到 spec 的每一个列引用位置、`.query()` 至少管 `select`，且 column scope 非空却没传
`select` 即 fail-closed），走 `.search()` 不会。**这个落差随结构化取数改造还扩大了**——取数侧的列级
覆盖面从「只有 `select`」扩到了含**聚合参数**在内的全部列引用位置，检索侧仍是零。这不是疏忽，是
**协议层语义空缺**：向量表没有源表的列结构，只有一个 `content` 文本块（可能混着受管控字段的文本），
「裁列」无从谈起；而当**受管控字段本身就是被向量化的那个非结构化字段**时更是无解——向量表构建一次、
全员共享，而列级权限按人不同，返回 content 就泄露，只返回 score 则相似度本身仍在泄露信息。

**对模块开发者的要求**：若你的向量化字段受列级管控，**必须在 G2 决策里显式处理**——
不向量化该字段，或按敏感度分表/分区把列级**降维成行级**（向量库里唯一能真正下推的形态）。
通用结论仍待业务方拍板（平台侧待办）；**在此之前别假设列级会自动生效**。

### ⚠️ 召回：HNSW 近似检索 + 权限过滤会静默少召回

安全没问题（无权行绝不返回），但 HNSW 是**近似**索引——WHERE 是在图检索**之后**施加的，
权限窄的用户可能拿到远少于 `top_n` 条、甚至 0 条，**且不报错**。平台已在检索时下发
`hnsw.iterative_scan` 续扫补救（需服务端 pgvector >= 0.8.0）。
**验收时务必用窄权限账号测「捞得全不全」**，管理员账号测不出这个问题。

### 业务条件 + 语义检索：用 `restrict_ids`，别在模块里求交

同一种塌陷还有一个**模块侧**的版本：问题同时带了机型/工厂/时间等条件时，「全表召回 `top_k` → 与
`ctx.data` 取到的候选编号求交」就是后过滤——条件越窄、交集越常为 0，`iterative_scan` 也救不了
（它只作用于 SQL 里的 WHERE）。正确写法是把候选编号交给平台：

```python
ids = ctx.data.fetch(spec)["issue_id"].tolist()          # 取候选的过程照常受权限约束；传 id_column 那一列，不是业务单号
hits = await ctx.retrieval.search(q, source="forge_mart_x", table="issue_vec", restrict_ids=ids)
```

`restrict_ids` 与行级权限编译进同一个 WHERE（AND）——**只收窄、永不放宽**，编号即使算错也捞不出无权行；
限定时平台走精确近邻，候选内召回完整。`[]` 直接返回空；去重后超过 5000 个报
`RetrievalRestrictTooLarge`（不截断）。切块表的 `restrict_column` / `filters` / `group_by` 同理——全部 AND 进
同一个 WHERE、只收窄，且只认 `manifest.vectorize.metadata_columns` 声明过的列（没声明即拒绝，不静默忽略条件）。
写法细节见 [02](02-sdk-reference.md)。

## 知识库检索（`ctx.knowledge`）

**第三条取数路径**（`knowledge-qa` profile）。外部知识库（RAGFlow）里的文档切片同样是数据，
必须与 `.query()` / `.search()` 受同一套红线管辖——否则「结构化查不到的，换成问知识库就能捞出来」。

```python
resp = await ctx.knowledge.retrieve("pdc", question, page_size=15)
chunks = resp["data"]["chunks"]     # 已过权限编译 + 响应回验
```

### 权限形态与前两条**不同**：文档标签，不是 dataScope

知识库文档没有行/列结构，`privileges` 的 row/column scope 在这条路径上**无从施加**。管控落在
**KB 目录白名单**上：平台把 `ctx.agent_node` 的 `privileges.dataScope[type=KB].directory`（中文库名/目录名
的递归白名单）编译成**库内目录路径前缀**（`-` 连接，不含库名），编成 `metadata_condition` 的
`permission_code start with <目录前缀>` 集合，**强制注入**每次请求（协议 §20.6）。RAGFlow 里每篇文档的
`permission_code` = 其库内完整目录路径（业务方 2026-07-18 确证）。

故这条路径上 `field_mappings` / `require_privileges` **不适用**——别按 `.query()` 的形态想当然。

> **库级 fail-closed + 目录级 fail-open（2026-08-07）**：
> ① **库级**——显式授权过的库才在访问范围内，其余**剔除**（多库调用不会因此整体失败），剔到一个不剩
> 才 `PermissionDenied`；② **目录级**——某库的目录白名单为空 = 该库**全部目录**可访问（与其他 agent 的
> 默认拒绝相反，业务方确认这是刻意的）。
> **两条载体**：`privileges.dataScope[type=KB]`（协议库名/目录名，靠 `directory_name` 映射）优先；
> 没有 KB 项时**回落 `sub_agents`**（第一级 = 库、其下逐级 = 目录，英文 agent 编码，靠 `agent_code`
> 映射）——INFO 至今只发后者。**库代码本身不进 `permission_code` 前缀**。
> 历史：2026-07-18 曾把 sub_agents 退役、并给 `privileges` 缺失/`{}` 判「全放开」；因 INFO 从未改造，
> 那等于知识库权限完全不生效（2026-08-07 实测越权），已推翻。

### 你不用做、也做不了的四件事

| 情形 | 结果 |
|---|---|
| 传 `metadata_condition` | `KnowledgeScopeOverrideError`——能被模块覆盖的过滤条件等于没有过滤条件 |
| 别名未在 `manifest.knowledge_bases` 声明 | `PermissionDenied`（防漂移/越库） |
| 被查库不在用户的授权集合内 | 从访问范围**剔除**（留痕 `knowledge_kb_excluded`）；单库调用即等于拒绝，**请求根本不发** |
| 本次请求的库**全部**未授权 | `PermissionDenied` |
| 被查库未配 `agent_code`（旧载体）/ 有 KB 项却未配 `directory_name`（v1.2） | `ConfigError`（无从判断是否授权，fail-closed，不猜） |
| provider 回了越界的 chunk/文档 | 平台丢弃并告警——你拿到的已是过滤后的 |
| 响应的 `data.doc_aggs[]`（doc_id→文档名） | **随 chunks 一起裁**——被丢掉的切片，其文档名不会从这里漏给你 |

**别把「目录级 fail-open」读成「权限没生效」**：某库的目录白名单为空确实不注入过滤，但那是在
**库级已经过闸之后**——能走到那一步说明这个库本来就在用户的授权集合里。反过来，两条载体都拿不到
任何库授权时一律拒绝（2026-08-07 推翻了旧的「privileges 缺失 = 全放开」）。
（历史上曾对「压不出标签」一律 `EmptyKnowledgeScopeError` 本地拒绝，2026-07-18 换源后按 §20.6 修订。）

**为什么还要回验**：部署的 RAGFlow fork 有「`metadata_condition` 被忽略」的上游既知 issue，
「我们发了过滤条件」≠「它过滤了」。

> ⚠️ **但别把「有回验」读成「有保障」**：平台落地的回验只有 `dataset_id`（挡跨库串数据）。
> `meta_fields.permission_code` 那道**本部署上永不触发**——真机确证检索 chunk 不含该字段。
> 也就是说**库内越权（该库里你能看哪些文档）平台验不了，完全依赖 RAGFlow 照做**，这与
> `.query()` / `.search()`（平台编译 WHERE、PG 确定性执行）不是一个强度。这是这条路径当前的
> 已知边界。

**文档列表尤其要知道**：`list_documents` 的过滤**不是回验、是闸本身**——RAGFlow 的文档列表接口
根本没有过滤参数，平台不筛就等于把整个 dataset 的文件名（里面编码着权限标签）全给出去。
拿不到 permission_code 的文档一律丢弃。

> 🔓 **文档预览走 RAGFlow 自己直连 INFO 鉴权、绕过平台**——那条路径的权限由 RAGFlow fork 负责，
> 不在上面四道闸的覆盖范围内。别以为「所有文档访问都过平台」。预览地址用
> `ctx.knowledge.document_url(kb, document_id, ext=...)` 拼（base_url 由平台持有），它只是个
> 不带凭据、也不代表授权的字符串。

> 🔓 **embedding / rerank 的模型执行全在 RAGFlow 侧**：本路径的向量化/重排/跨语言翻译都由 RAGFlow
> 用它**自己配的**模型完成（`rerank_id` 指的是它那边注册的模型名）。平台的
> `FORGE_EMBEDDING_BASE_URL` / `FORGE_RERANKER_BASE_URL` 只服务 `ctx.retrieval`，与这里无关。
> 「模型仅本地服务」这条红线在本路径上由 **RAGFlow 的部署配置**保证，平台钉不住——同 §文档预览，
> 是分工不是漏洞，但别默认「平台管住了模型」。
> ⚠️ **这句说的是「谁跑模型」，不是「你能传什么参数」**：`rerank_id` / `cross_languages` /
> `vector_similarity_weight` / `top_k` 等检索参数一律**原样透传**（口径与完整清单见
> [07 §knowledge-qa](07-capability-profiles.md#knowledge-qa知识库问答)）。这条路径上模块唯一
> 传不了的是 embedding 模型（请求里没这个参数），唯一**被拒绝**的是 `metadata_condition`（权限）。

## 沙箱数字处理

一切统计/算术/计数/排序/对比**必须**经沙箱，不得由 LLM 直接产出数字——这是因 LLM 数字运算天生不可靠（能力限制），**不是**禁止 LLM 接触数据：本地 Qwen 完全可以读取业务数据做解读/总结/初步分析，只是别让它直接算数（数字一律来自沙箱产物）。

```python
from forge_sandbox import run_script

# 让 LLM 生成一段定义了 run(data) 的脚本，或用固定脚本模板
SCRIPT = """
def run(data):
    df = data["sales"]
    return {"total": float(df["amount"].sum()), "rows": int(len(df))}
"""

outcome = run_script(SCRIPT, datasets={"sales": df})   # datasets 值须可 pickle
if outcome.ok:
    total = outcome.result["total"]
else:
    # outcome.error 是 traceback，可回喂 LLM 让它修脚本重试
    yield Event.error("sandbox_failed", outcome.error)
```

- `run(data)` 收到的 `data` = 你传入的 `datasets` 同名字典（`{名字: DataFrame}`）。
- 安全模型：隔离子进程、import/builtins 白名单、无网络、收紧文件 IO、rlimit、超时(默认 60s)强杀。
- 结果 `run()` 的返回值经 JSON 归一（整型/浮点规整），从 `outcome.result` 取；**上限 20 万字符**——
  它是给「聚合好的统计结果」用的，超了报「结果过大，请在脚本内聚合后再返回」。

### 拿回明细帧（数据帧通道）

沙箱算出的东西有时本身就是一张**帧**而不是几个数：下钻数据集、按多维汇总后的中间表，拿回来存工作区、
再喂给下一次沙箱。这种帧的行数随数据量增长，**不要**把它拆成 records 塞进 `result` 再在 `handle()` 里
重建——那迟早撞 20 万字符，dtype 也得自己手工维护。开数据帧通道（平台仓决策 2026-09-21「统计沙箱
数据帧回传通道」）：

```python
SCRIPT = """
def run(data):
    g = data["sn"].groupby(["pn", "client", "ship_date"], as_index=False)["qty"].sum()
    return {"sn_customer": g, "groups": len(g)}      # 顶层 DataFrame 走数据帧通道
"""
outcome = await ctx.stats.run(SCRIPT, {"sn": df}, return_frames=True)
if outcome.ok:
    frame = outcome.frames["sn_customer"]   # DataFrame，dtype 精确还原，RangeIndex
    groups = outcome.result["groups"]       # 其余键照旧在 result
```

- **只摘顶层**：返回 dict 里值是 DataFrame 的键进 `outcome.frames`，其余键进 `outcome.result`（仍 ≤ 20 万字符）。
- **上限按每次调用计**：本次调用全部数据帧编码后 ≤ `FORGE_STATS_MAX_FRAME_MB`（默认 16MB，平台部署配置，
  模块不能放宽）。超了报「数据帧过大」——该在脚本里继续聚合，或只回传要用的列。
- **支持的列类型**：数值/布尔（含 `Int64` 等 nullable）、字符串（`str`/`string`/`object`）、`datetime64`（含时区）；
  `object` 列里整列同为 `Decimal` / `date` / `datetime` 也能精确还原。别的类型（`category`、`timedelta`、
  一列里混着字符串和 `Decimal`……）直接报错，照提示先转换。
- **行索引不回传**：groupby 后记得 `as_index=False` 或 `reset_index()`——带名字的行索引会被拒（那多半是分组键，
  丢了就是丢数据）；过滤后留下的无名索引直接丢弃。
- **红线不变**：帧里的数字同样是沙箱产物。拿回来可以存、搬、再喂沙箱、原样展示，**不得在 `handle()` 里对它再聚合**。
- LLM 生成的统计脚本一般**不开**这个通道：它的产出本该聚合好再回来，20 万字符那句反馈正是让它重试用的。

## fail-closed 自检清单

写完取数逻辑，对照检查：

- [ ] 没有任何地方绕过 `ctx.data` / `ctx.retrieval` 直连数据库 / 手拼连接串 / 自造检索句柄。
- [ ] `manifest.data_sources` 声明了用到的每个别名（含无权限约束的源），且与部署侧 `data_sources.json` 对得上。
- [ ] `field_mappings` 覆盖了权限规则（row/column）可能引用的所有协议字段——**含子表字段引用会落到的子表**（子表列名不同就补表级覆盖）。
- [ ] 权限规则可能对其用集合类操作符（`CONTAINS` 等）的字段，已在 `manifest.collection_fields` 登记物理格式。
- [ ] 取数 `.fetch()`/`.query()`/`.raw()`/`.row_scope_sql()` 都传了物理**表名**（dataScope 按表选规则）；表名与 `dataScope[*].table.name` 四段式尾段一致。
- [ ] 业务过滤优先写成 `.fetch()` 的结构化 `filter`；仍留在裸 `where` / `raw_where` 的谓词，**每一条都确认过它引用的列你有权 `select`**（裸串不过列级白名单，是列级权限的 oracle）。
- [ ] 日期区间用 `{"$relative": "-30d"}` 交框架算，**没有让 LLM 自己算「30 天前是哪天」**（那是数字红线）。
- [ ] 取数的调用处接住了 `TableDenied`（表级无权在 `.fetch()`/`.query()`/`.raw()` **一律抛错**，不是空 DataFrame）与 `RowLimitExceeded`（超限**报错**不是静默截断）。
- [ ] 用到多表 JOIN 的话：`manifest.data_sources[].joins` 声明了每一条边（含**完整**的复合关联列），`tables` 也一并写全了；关联列在列级权限是 `ALLOW` 白名单时确认过它在白名单内。
- [ ] 用了 `LEFT JOIN` 又在 `filter` 里过滤被连接表的列的话，确认过**你要的就是退化成 INNER**（框架只保证自己加的 scope 不改变查询形状，不替你改你写的过滤）。
- [ ] 多轮重试用了 `SpecRepairLog`（或等效的负面约束累积），没有让 LLM 反复撞同一个 `retryable=False` 的错误。
- [ ] 走治理/镜像库时，ETL **透传了全部权限承载列**，且镜像若预聚合**未跨越权限维度**（否则已等效施加行级限制）。
- [ ] 同一协议字段在不同源的物理列差异，已由各自别名下的 `field_mappings` 分别锚定（未跨源复用 key）。
- [ ] 用到列级权限的查询都**显式传了 `select`**。
- [ ] 高敏模块（不接受「INFO 漏发 privileges 即放行」）已置 `manifest.require_privileges=True`。
- [ ] 权限拒绝（`PermissionDenied`）如实转成 `Event.error`，没被吞成空结果。
- [ ] 所有数字口径都由**确定性执行器**产出（SQL 聚合或 `ctx.stats` 沙箱），没有让 LLM 直接算/数/排，
      也没有在 `handle()` 里用 Python/pandas 直算。
- [ ] 能用「表里已有的列 + COUNT/SUM/AVG/MIN/MAX」表达完的聚合**优先下推 SQL**，没有为了算一个总数
      把明细全量拉回进程（那既是内存风险，也让更多无关行离开数据库）。
- [ ] 语义检索走 `ctx.retrieval.search(...)`（权限与审计自动在场），未自己 new `PgVectorIndex`/`EmbeddingClient`；
      向量表已随行落权限承载列，**窄权限账号**实测两条：无权数据检索不出来（安全）+ 有权数据捞得全（召回）。
- [ ] 切块向量表（一块一行）：用到的记录编号 / 字段列已写进 `manifest.vectorize.metadata_columns`；候选限定配了
      `restrict_column="record_id"`（否则按块编号匹配恒 0 条）；去重用 `group_by` 而非在模块里按块编号前缀归并；
      按权限分表后合并按 `h.rerank_score`（`score` 跨表不可比）。
- [ ] 带业务条件（机型/工厂/时间…）的语义检索用 `restrict_ids` 传候选编号，**没有在模块里「全表召回再求交」**；
      编号取自向量化的 `id_column`；接住了 `RetrievalRestrictTooLarge`（超限报错不截断），回落时如实说明结果不保证完整。
- [ ] 向量化走 `manifest.vectorize` 声明（平台生成回填 + 透传），`jobs()` 里没有自写的向量化 job；
      向量表 DDL 由 `forge vectorize ddl` 生成而非手写。
- [ ] ETL job（治理同步等）的 SELECT **带上了权限承载列**并原样落进 mart 表——`ctx.etl` 是系统级句柄、
      **不受 scope 管辖**，透传是它唯一的权限义务。
- [ ] 向量化字段若受**列级**管控，已在 G2 决策显式处置（不向量化 / 按敏感度降维成行级）——
      列级权限当前**不作用于检索路径**，别假设它自动生效。
