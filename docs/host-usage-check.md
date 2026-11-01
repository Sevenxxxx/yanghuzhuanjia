# P0 资产与当前宿主检查

检查日期：2026-10-20。只记录实际执行，不将设想当作完成。

## 环境与入口

- Python 3.12.10、Git 2.55.0.windows.2、Node v26.11.1 可用。业务代码只用标准库，未安装新依赖。
- 原工具 doctor 全部通过：PyMuPDF、Office 文档依赖、COM、Tesseract 和中文包可用。书架713项，不等于全部逐本核验或覆盖所有规范。
- 当前 Codex 实际读项目 SKILL.md 和 operations.md，调用 road.py 完成创建、多轮、查询、回源、渲染、审阅、保存、恢复及导出。
- 自动技能目录热刷新未独立观察，显式执行已验证。当前不需要 dsh 或新增模型接口。
- 初始演示未写入具体模型，保留 unknown。随后为回答思考强度问题，只读会话日志确认开发轮次为 GPT-6.1 Sol／Medium；未改模型、全局配置或界面设置，内部完整提示词与调用预算仍不可控。
- 已初始化本项目本地 Git main 分支，未提交、推送或连接远程；忽略缓存、请求与输出，不将咨询数据放进仓库。

## 规范适配审计

原项目：C:\Users\Seven\Desktop\guifanchaxun。复用 tools/guifan-chaxun/config.json、scripts/spec.py 和现有源／索引。

允许入口：list（读取书架）、toc、clause、grep --json、read。index、ocr、remove、set-page、cleanup 等维护不可从本接口调用。上游 img 会写原库，因此改在自己的仓库外目录用已安装 PyMuPDF 渲染。

实际查到 JTG 5120—2021、JTG 5150—2020 等。桥涵规范第14页已 read、渲染并实际核对3.3.2，只用于条件化的巡查异常记录与上报，不支持病因、安全或施工结论；未另行认证最新有效性。

部分路面规范为 OCR，旧置信度可能未绑定。适配保留 OCR／表格／乱码提示；源与索引指纹不一致时不升级引用。

联调对上游 SKILL.md、config.json、spec.py、bookshelf.json 前后 SHA-256 对比不变。只证明所列文件，不夸大为整个源库逐文件审计。

## 资料边界

无模型 API、抓取或发布代码。默认记录目录在 LOCALAPPDATA/RoadMaintenanceExpert/项目摘要；doctor 显示实际值。原文与图片不进仓库，测试隔离。

案例库为空，知识与规则待专业审阅；没有真实工程评价、用户反馈或专家签发。
