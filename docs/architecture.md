# 当前个人版架构

Codex／dsh 负责理解和分析，项目工具负责状态、约束与证据。个人版没有独立模型服务；P3 本机单实例（`scripts/p3/`）只把同一套工具接到本机 Web，取舍与限制见 [ADR 0002](decisions/0002-p3-local-web.md)。

```mermaid
flowchart TB
    U["用户的获准描述"] --> C["现有 Codex + 项目 Skill"]
    C --> R["road.py JSON 请求入口"]
    R --> S["会话与逐轮风险检查"]
    R --> E["规范查询、回源与审阅记录"]
    R --> K["案例检索与分项审核"]
    D["草稿问诊知识卡"] --> C
    E --> L["原 guifanchaxun：只读查询"]
    E --> V["受控目录原页渲染 + 实际查看声明"]
    K --> J["经审核案例 JSON + 派生索引"]
    S --> F["仓库外修订记录与工具证据"]
    E --> F
    K --> F
    F --> C
    C --> A["分析、核查目的、条件化方向与交接"]
    A --> R
    R --> O["JSON / Markdown / 按需 Word"]
    O --> U
```

## 目录入口

- `scripts/road.py`：JSON 请求入口；`scripts/check_*.py`：开发检查，命令与影响见 [交接验证表](交接.md#验证与交付)。
- `scripts/p3/`：P3 入口。`road_expert.patch.yml` 是专家职责与工具面的唯一来源；`local_web.py` 起停 dsh 自带界面；`chat/`（`app.py` + `page.html`）是纯聊天前端，页面经 HTTP/SSE 接到按访问者隔离的 `dsh --profile road-sdk` 运行时；`proxy/` 是模型代理；`server/` 是 Windows 部署脚本；数据在仓库外。
- `src/roadexpert/`：下列业务模块；`tests/`：对应回归，`tests/fixtures/synthetic/`：合成情境。
- `.agents/skills/road-diagnosis/`：唯一咨询技能及 `references/` 操作参考。
- `data/knowledge/`：草稿知识卡；`data/cases/`：真实案例与派生索引，允许空库；`data/library/`：教材、论文、案例原文，本地 PDF 与分页文本，目录整体 gitignore。
- `config.example.json`：本机配置示例；真实咨询、证据、请求正文和导出存储在仓库外。

## 模块与边界

- storage.py：临时工作状态与按需保存档案，通过 retention 区分；24小时未写入的临时状态在后续调用清理，明确结束时即时清理；修订快照、指纹、版本检查、写锁和受控路径仍用于当次连续问诊。
- risk.py：五类无数值关注线索、否定／未知／历史／假设初筛；规则为草稿，宿主补结构化抽取。
- specs.py：固定操作与字面查询，不调用维护命令；原页在项目外部存储渲染。
- cases.py：JSON 单源、分项人工审核、撤回与查询时索引复核；候选库可列表、查看、背景检索和拒绝，候选不进索引、不得写入 case_refs；本地全文来源按页读取／检索，副本在仓库外使用语义的 sources 目录并 gitignore。
- library.py：本地资料库；PDF 入库后生成分页文本、目录、SHA-256，支持按类型／主题列表、字面检索、按页读取和渲染；不做 OCR、索引维护、自动摘要，不替代规范回源或案例审核。
- service.py：多轮、问题决策影响、证据关联、适用性声明、答案绑定；save 是显式长期归档，export 是显式导出，backup 只含主动保存的档案。默认不展示编号或保存流程。
- advice.py：分领域分析字段与三种交付格式的契约；不推断病因。专项导出只取最新且未过时的对应交付内容，共用来源、风险、规范核验与判断边界；原完整咨询导出继续可用。
- photos.py：用户获准附件的受控副本、元信息及实际查看声明；图片观察生成带定位的事实，照片变化使旧意见和规范适用性需重新核对。副本在咨询sessions目录，复用临时清理和主动保存备份，不保存或改写用户原图。
- comparison.py：有条件的方向比较与当前已知事实引用，不自动排序、评分或批准施工。比较进入聊天及按需文件。
- word_export.py／word_document.py：用户明确请求后通过本机文档Python生成可编辑Word，可选择附图；不附全历史JSON、不自动归档。文件生成采用临时文件完成后替换；宿主另作渲染及逐页核对，无网络与模型API。
- delivery_check.py：只读检查最新意见及所选交付范围；明确完整性错误、文字来源疑点与宿主语义核对分别输出。export锁定当前咨询并重查，可绑定检查内容指纹；历史导出需显式选择且标注非当前交付。Word临时文件中的嵌图字节及图注匹配要求后才替换目标文件，排版另验。不联网、不调用模型、不自动改写意见或作工程批准。

程序检查摘录定位、来源指纹、记录归属和字段状态，不能独立证明看图、专业审核身份或语义适用性。宿主的其他通用工具并不受此 CLI 全面约束。

`App.dispatch` 在每次操作前清理过期临时状态，包含 doctor 和 delivery-check；检查逻辑只读不代表整个调用无生命周期副作用。默认存储按项目绝对路径生成标识，迁移目录时需核对存储位置，不自动搬移。

普通完整咨询导出需通过最新意见有效性检查，但 JSON 仍保存全会话，Markdown／Word 可能包含续办与前次意见。专项导出按用途裁取；history_only 是历史用途标记，不承担脱敏功能。备份只含已保存咨询及关联资料。

依赖和配置见 [当前交接](交接.md#本机运行与换机注意)：照片使用 Pillow，原页渲染使用 PyMuPDF，Word 由独立文档 Python 及 python-docx／Pillow 生成。早期“标准库 CLI”描述不能理解为所有现有功能均无需外部依赖。

P3 现在是「一个地址 + 按访问者隔离运行时」（[ADR 0003](decisions/0003-chat-frontend.md)、[ADR 0005](decisions/0005-server-deployment.md)）：

```
浏览器 ──HTTP/HTTPS──> Caddy（对外入口，TLS 与反代）
                          └──> 聊天服务（127.0.0.1:8095，唯一进程）
                                 ├── 访问者 A 的运行时（独立 DSH_HOME 与咨询目录）
                                 ├── 访问者 B 的运行时
                                 └── dsh ──> 模型代理（127.0.0.1:8096，持有真 key）──> api.deepseek.com
```

- 服务端用 `rc_vid` cookie 认访问者，每人一个 `dsh --profile road-sdk` 子进程，停止只重启自己那个；
- 共享口令（`deploy.json` 的 `password`）挡陌生人；真 key 只在代理进程里，agent 读不到；
- 部署目标是 Windows Server 2022：计划任务托管三个服务，Caddy 负责证书与反代；
- 未做：账号体系、按人数据隔离、聊天页文件下载。迁移复用知识、规则、案例与记录，模型／入口变化后重跑测试及专业评价。
