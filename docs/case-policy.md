# 案例文件与人工审核

真实可引用库为空。无案例为 no_qualified_cases；索引损坏为 index_unavailable；版本或部分文件异常为 search_incomplete。候选库（incoming）与可引用库（verified）分开：候选案例未经审核，只能作背景线索，不得写入 case_refs。

## 导入

case-import 接收 case 对象：

- case_id、event_id、title、domain、tags；
- source.url 或 source.internal_id、source.external_model_allowed=true；
- security_level=public_deidentified；
- 发布审阅需要 source_grade、cause_status、treatment_status、follow_up_status。

domain 为 pavement／slope／bridge／general。合成类型、is_synthetic=true 或合成状态禁止进入真实库；测试仅在 tests 和隔离临时目录。原始附件和受限关联表在仓库外。

首次导入一律 pending_review，清空携带的审核和引用声明，不按网页自称权威发布。重复编号不覆盖，不为数量降低门槛。公开资料只做结构化摘要和来源链接，不整篇复制；未取得全文时在 source.access_note 和 review_status 中说明。

## 候选库的查看、检索与拒绝

- case-list 列 incoming／verified／rejected 的案例元数据、摘要、全文可用性和计数；不返回受限内容。
- case-show 按 case_id（可选 area）返回单个案例，供人工核对；verified 仍按发布门槛复核。
- case-source 为 0.1.7 兼容接口，只读旧的 `data/cases/sources/`；新案例原文统一放 `data/library/`（type=case_source），用 library-* 读取。
- case-search 默认 scope=verified；scope=candidate 查候选库并标记 evidence_status=unverified_candidate；scope=all 同时返回两类。

## 案例原文与本地资料库

- 公开论文／报告的原文统一放 `data/library/<library_id>/`，`type=case_source`；由 library-source／toc／read／search／render 按页读取和检索。
- `data/library/` 整体 gitignore，仅本地研究与审核使用；不提交 Git、不再分发。公开可访问不等于可自由转载，版权和许可由使用者核对。
- 受付费墙、登录或权限限制的全文不得绕过访问控制获取；没有全文时不使用摘要冒充全文。
- library-read／library-search 只做按页读取和字面定位；不解析图表、扫描件或 OCR，不证明原文支持当前工程判断。
- 原文不是审核结论；案例仍须经过 source_facts、professional_evidence、rights_privacy 三项人工审核才能发布为 verified。
- 候选结果只作背景线索，必须显示“未经人工审核”提示；不得写入 answer.case_refs，不得作为工程结论。
- case-reject 只处理 incoming，记录原因、保留旧版本，移入 rejected；已发布案例用 case-withdraw。

## 人工发布

仅在真实取得审核后录入 case-publish：case_id、reviews、allowed_claims 和 human_confirmation，确认文字为“已取得相应专业人员和资料权限审核”。

reviews 至少含 source_facts、professional_evidence、rights_privacy 三个 scope，每项记录 reviewer、actor_kind=human、reviewed_at、decision=approved、basis。来源 S1/S2，病因、处治和后效分别记载，可引用范围具体。

程序检查声明完整，不能独立验证身份或结论。Agent 不可冒充人类审核；缺相应人员／证据则保留候选。原因未明、失败案例可按获准范围使用，不能写成确认病因或成功效果。

## 查询与撤回

索引从审核 JSON 派生，重建不提升级别。按现象／条件、领域和同义词查询，重新核对文件指纹、权限、审核与状态；可排除 event_id 以隔离评价事件。候选库不进入派生索引，查询时逐文件读取并重新校验。

answer.case_refs 必须来自本咨询实际查询，案例当前未变化／撤回，并说明相同、不同及借鉴范围。程序不代替语义相似和适用判断；候选案例会在引用校验时被拒绝。

case-withdraw 留旧版本并停止新引用；历史咨询不覆盖，导出提示当前状态。旧索引不会让已变更内容继续当作已核验案例。

复杂修订暂不做自动编辑器：留存旧版本、撤回旧项，再用新编号和替代说明重新导入审核。个人版不提供多人编辑和自动采集。
