# 本地工具请求

在项目根目录执行：python -X utf8 scripts/road.py <仓库外的请求.json>。也支持传 - 从 stdin 读取 JSON；--doctor 可直接自检。无独立模型请求、无联网调用。默认记录位置由 --doctor 显示；--store 可指向新的仓库外本地目录。自定义本机配置可用 --config，格式见根目录 config.example.json。

所有请求分派前均运行既定的 24 小时过期清理，包含 doctor、resume 和 delivery-check；“只读检查”指不改写有效咨询内容，不表示整个命令无清理副作用。隔离开发检查使用新的仓库外 --store。默认存储与项目绝对路径有关，搬目录后先核对位置；不要自动迁移或清空旧库。

每个请求是单个 JSON 对象；响应含 ok、result。错误返回退出码 2。优先通过 stdin 输入 JSON，不把原话拼接为 shell 命令，不在外部零散保存请求文件。以下省略值只是格式说明，不能原样作为真实咨询或专业审核记录。

## 临时状态与按需保存

start 一律创建 retention=temporary，默认不进入 sessions 历史列表。内部 ID 供工具接续，不要求用户记住。最后一次写入后24小时过期，每次调用会清理过期临时状态及不被其他会话使用的证据副本；不会后台自动唤醒。明确结束未保存咨询时：

    {"op":"finish","session_id":"内部 ID","base_revision":3}

仅用户明确要求长期保存时：

    {"op":"save","session_id":"内部 ID","base_revision":3,"user_requested":true,"basis":"用户要求：保存这次咨询"}

成功后 retention=saved，不再自动过期，返回可供用户恢复的编号。保存不改变资料访问许可。finish 对已保存咨询只结束交流，不删除档案。cleanup 可显式清理已过期临时状态；不是删除长期档案的接口。

answer 只是更新工作状态，不等同于 save。export 必须附 user_requested=true，仅在真实用户要求导出时调用；导出文件保留，而临时会话仍按原期限清理。backup 只复制主动保存的咨询及其关联证据／导出，忽略其他临时会话与零散文件。旧版缺少 retention 的记录按长期档案处理，不静默过期。

## 建立与多轮恢复

start 请求：

    {"op":"start","title":"本次问题","domain":"pavement","text":"用户本轮原话","privacy":{"level":"synthetic","external_model_allowed":true,"authorization_basis":"明确为合成测试"},"host":{"client":"Codex","model":"实际可识别值或 unknown","effort":"实际设置或 unknown"}}

domain 为 pavement／slope／bridge／general。真实公开或脱敏输入用 level=public，记录真实授权依据；默认 restricted 且不允许外部模型读取。代码不发网络请求，权限关口限制它向宿主返回的内容，不控制宿主其他通用工具。

start 和 turn 可附：

- facts：field、value、basis、kind、state、source_ref、supersedes。field 见下；用户陈述 basis 必须定位到本轮原话。kind 为 user_report／photo_observation／report_record／system_hypothesis。照片和报告须实际来源定位，不自动核实内容。state 为 known／unknown／unavailable／unsafe／contradictory。
- observations：key、state、time、kind、basis、supersedes。key 为 sudden_collapse／progression／active_fall／bridge_deformation／traffic_affected。state 为 present／absent／unknown／contradictory；time 为 current／historical／hypothetical／unknown。
- 有明确纠正时，加 user_correction=true、correction_reason 并列出被纠正 ID。原记录不删除。未纠正的旧紧急触发继续保留，不因后续一句“现在没有扩大”消除突发塌陷等其他征兆。

事实 field：facility、road_class、location、discovery_time、progression、traffic、rain、drainage、component、dimensions、history、other。system_hypothesis 不能用来证明另一假设。

turn：

    {"op":"turn","session_id":"实际 ID","base_revision":1,"text":"用户新原话","facts":[{"field":"progression","value":"不知道是否继续扩大","basis":"不知道是否继续扩大","kind":"user_report","state":"unknown"}]}

show／resume：{"op":"resume","session_id":"实际 ID"}。获准记录返回 resume_summary：上次意见及 stale、新增原话、纠正过的事实、前后两份已保存意见差异、信息缺口、待答／未答问题、上次核查建议与交接。核查完成情况不自动推断。受限记录不返回该摘要。sessions 按更新时间倒序列 ID 和修订，仅获准记录显示标题。routine=true 仅用于创建常规咨询；只有相关风险信息明确否认且无触发／矛盾时才可能输出普通咨询，仍非安全评估。

show 可加 revision 只读查看历史；resume 始终恢复最新，不用旧状态覆盖后续信息。receipt 操作带 session_id、receipt_id 可恢复本咨询工具记录；渲染图使用返回的 resolved_path，它按当前存储目录解析，备份迁移后不要使用旧绝对 path。

用户真实明确授权或撤销后，可用 permission、session_id、base_revision、action=grant／revoke、basis 记录。grant 还需 human_confirmation="用户明确允许当前模型读取此咨询及历史资料"；不得由 Agent 自行推定或填写虚构依据。撤销会阻止历史快照向模型返回原文，已发送内容不能由软件撤回。该操作只记录权限，不主动联网。

## 弹窗问题的保存与恢复

先保存待答问题（fields 取 briefing.next_questions 中合适字段，通常只取一个）：

    {"op":"question-ask","session_id":"实际 ID","base_revision":1,"fields":["traffic"]}

返回 session_revision、questions（id／field／question／purpose／可选 options）。display_status=host_must_prompt 表示尚待宿主实际显示；程序本身不开弹窗。当前存在待答问题、已问或已提供的字段不能重复创建。无选项的题使用自由填写。

真实答复通过 turn 保存：

    {"op":"turn","session_id":"实际 ID","base_revision":2,"text":"不清楚","question_responses":[{"question_id":"实际问题 ID","text":"不清楚","state":"unknown","submitted":true}]}

question_responses 每轮最多3项，text 必须可定位到本轮原话。自动保存对应 user_report 事实，不能同时在 facts 传同一字段。题干与未选选项不拼入原话。自由补充原样保存，事实状态按实际含义填写；混合回答由 Agent 核对，程序不承担语义审核。明确纠正已答内容时用普通 turn＋facts.supersedes／observations.supersedes，保留旧回答，不重放旧问题提交。

用户明确关闭／跳过后：

    {"op":"question-close","session_id":"实际 ID","base_revision":2,"question_ids":["实际问题 ID"],"reason":"用户明确跳过"}

此操作只记 unanswered，不增加用户轮次或事实。中断恢复仍能看到 pending／unanswered，迟到回答可关联原 ID；不要擅自把 pending 当作用户已跳过。宿主是否真的弹窗及收到真人输入不能由本地 JSON 字段证明。

## 规范检索与回源

以下请求可附 session_id、base_revision 关联咨询，返回 session_revision。**每一次工具关联都增加修订号**。

- spec-list：query 为规范名、标准号片段；返回准确 book_id。
- spec-toc：book_id。
- spec-clause：book_id、clause（条文号）。未命中可能仅给邻近条文，不能当作实际命中。
- spec-search：query 是单个字面关键词、可选 book_id、limit（1～100，默认20）。用多次查询覆盖同义词，截断／不可用仍为 search_incomplete；即便单次 complete 也不证明本问题已查全。
- spec-read：book_id、page（一次一页）。返回原文、源文件指纹、版本和 needs_visual。原文回源不自动证明适用性。
- spec-render：read_receipt_id（成功回源记录 ID）。图片写本项目外部受控存储；返回 receipt.id 供后续核验。

源规范不作维护。原文件和索引不匹配时不能把旧证据升级。读到被替代版本需说明；历史适用以问题条件为准，软件不自动选择更严要求。

evidence-review：

    {"op":"evidence-review","session_id":"实际 ID","base_revision":4,"read_receipt_id":"实际回源 ID","quote":"实际原文摘录","applicability":"conditional","applicability_note":"本场景满足什么、还缺什么","verification_scope":"实际核查的主条文／说明／图表／引用链范围","reviewer":"实际查看者"}

applicability 还可为 applicable／not_applicable／unknown。需看图时加 visual_receipt_id、viewed=true、visual_note（具体核对内容）。这是真实操作声明，不是程序可独立证明的专业审查。返回 eligible=false 时，不能在正式 claims 中引用；保留缺口或继续核对。不要编造 eligible=true 或把 header 当有意义依据。

## 保存 Agent 分析

    {"op":"answer","session_id":"实际 ID","base_revision":5,"answer":{"summary":"当前重点与必要风险提示","hypotheses":[{"label":"条件化候选原因","support_fact_ids":["实际事实 ID"],"against_fact_ids":[],"uncertainties":["待区分内容"]}],"next_checks":[{"action":"具体资料准备或核查方向","purpose":"解决什么疑问","different_results":"不同结果怎样改变判断"}],"claims":[{"text":"该原文支持的判断","review_ids":["实际 review ID"]}],"options":[{"approach":"参考方向","conditions":"成立前提","limitations":"限制"}],"handoff":["带什么资料、解决什么问题"],"questions":[{"field":"drainage","question":"一个关键问题","purpose":"区分目的"}],"limitations":["实际缺口与未验证事项"],"case_refs":[]}}

hypotheses、claims、options、questions、case_refs 可为空；没有候选就明确尚不能形成，不必凑数量。summary、next_checks（每项 action 和 purpose）、limitations 必填。questions 每轮最多3个；已答／已问或明确不可获得的字段不重复问，必要的新区分内容在交接中说明。

新弹窗流程使用 question-ask 记录问题，answer.questions 留空，避免重复登记。路面沉陷咨询设置 analysis_profile="pavement-subsidence-v1"；此模板要求每个 hypothesis 带 reasoning 和 discriminator，每个 next_check 带 different_results。这些内容会进入 Markdown 导出；旧记录仍可读取，无需迁移或补写历史字段。

case_refs 每项：query_receipt_id、case_id、similarities、differences、borrow_scope。引用须来自本咨询的真实 case-search，且当前案例未变化或撤回。

export：{"op":"export","session_id":"实际 ID","user_requested":true}；仅在用户明确要求时生成本地 Markdown 和 JSON，不自动发布或上传。导出不自动长期保存会话。普通完整咨询须通过最新意见有效性检查，但 consultation.json 仍含完整会话及原话／历史，Markdown／Word 可能含续办摘要与前次意见；文件按原资料权限使用，不是自动脱敏结果。报告的程序校验不保证模型正文没有事实／工程错误。

其他分析模板：pavement-distress-v1（pavement）、slope-instability-v1（slope）、bridge-culvert-v1（bridge）。均要求 hypothesis.reasoning／discriminator、next_check.different_results；并要求 analysis_context 的领域字段，详见 [分领域分析](domain-analysis.md)。字段允许明确记录未知，不允许虚构补齐。

answer.deliverables 可含 field_advice／inspection_brief／department_reply，各字段为非空文本数组，结构见 [按需交付](deliverables.md)。export 增加 kind 选择上述一种，默认 consultation 保持旧接口。专项导出拒绝无对应内容、没有意见或已过时的意见；失败不创建导出目录。不附带全部原话和历史；完整咨询导出仍包含完整记录，须按实际资料权限使用。

## 照片、比较与Word

delivery-check：session_id，可选kind（默认consultation）、format（默认markdown）、include_photos（默认false）。只读检查最新意见，返回errors／warnings／manual_checks、exportable、scope、session_revision、content_sha256；不写咨询、不导出文件。当前会话无模型读取许可时拒绝返回检查内容。完整工作流见 [交付前检查](delivery-check.md)。

export自动重查，errors阻止当前交付；可传expected_check_sha256绑定先前检查的范围和内容，变化时拒绝。警告仅为文字线索，仍须宿主核对。用户明确追溯时history_only=true仅支持完整Markdown／JSON，文件名及正文标注历史用途；不会自动将当前交付降级为历史。Word在临时文件中核对实际嵌入照片字节与所需图注后才发布，不代替渲染看图。

- photo-add：session_id、base_revision、path（用户附件的本机绝对路径）、user_provided=true、authorization_basis、可选label／location／capture_time／direction。返回photo及新修订；照片副本在本次sessions目录。元信息默认不清楚，程序不推断。
- photo-show：session_id、photo_id，核验归属与副本指纹后返回path，宿主须实际看图。
- photo-observe：session_id、base_revision、photo_id、viewed=true、viewer、observations。每项field、state(known/unknown)、value、region、limitation；time默认unknown，current/historical需time_basis。生成照片观察事实，不增加用户turn；照片变更使旧意见过时，规范审阅需重新确认。
- 需要在turn引用已有照片事实时source_ref为photo:照片ID:观察ID；field／value／state须与实际记录对应，不能借来源定位改写观察。老记录不迁移，新记录不接受随意文件路径冒充图片依据。
- answer.comparison 结构详见 [照片与方向比较](photos-and-comparison.md)。比较共用当前事实、风险和规范依据，进入完整及专项导出。
- export 加format=docx生成Word，仍需user_requested=true；kind支持原四种类型。include_photos=true仅在用户要求附图时填写。Word只生成所选文件，不自动另附含全历史JSON；format默认markdown仍保留原Markdown/JSON接口。
- Word依赖本机已配置文档运行环境；默认使用Codex捆绑Python，可在仓库外本机配置设置document_python绝对路径。不自动安装、付费、上传。运行环境缺失明确报错，不生成占位文件。
- Word返回visual_review=pending_actual_render_and_view，宿主随后渲染并逐页核对。导出成功不等于已看图或专业审核；临时照片副本清理后，已明确导出的嵌图Word仍完整保留。

## 案例工具与人工入口

case-search：domain、tags（只用观察／条件词）、可选 excluded_events。可关联咨询；无合格案例返回 no_qualified_cases，索引损坏返回 index_unavailable，不混同。

case-import：case 对象。原始字段见 docs/case-policy.md。仅接收有明确外发许可的公开脱敏资料，导入一律 pending_review；合成资料拒绝进入真实库。

case-publish 需要人类审核后提供 case_id、reviews、allowed_claims、human_confirmation。只供已完成的人工专业审核录入，不授权 Agent 冒充审核人员。

case-withdraw：case_id、reason；保留旧修订并停止新引用。case-rebuild 可重建派生索引；查询还会核对当前文件，防止旧索引继续引用已变更内容。

## 备份与恢复

backup：destination 指向不存在的仓库外本地目录。先确认没有其他进程写入；仅备份已保存咨询及关联证据、照片和导出，不包含临时咨询，也不备份原规范库。恢复先复制备份到新的受控目录，用 --store <恢复目录> 执行核验及恢复；保留原损坏记录，不直接覆盖。只有明确需要导出文件时才调用 export。

备份完成含文件校验清单。先在恢复目录执行 {"op":"backup-verify"}，再 resume／receipt／export 检查。恢复后修改数据会使旧快照校验不再通过，应重新备份；清单不验证咨询语义或来源真伪。

修订 JSON 有 SHA-256 完整性校验和独立版本文件。最新损坏不会静默回退；可人工读取较早修订核对，不能把不完整恢复说成完整。残留锁不自动删除，先确认对应 PID 无活跃写入，再人工处理锁文件。
