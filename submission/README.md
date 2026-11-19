# BOM-BOM队 · BOM Pilot 比赛交付包

**面向 AI 硬件团队的采购决策工作台。** 所有演示物料、报价、库存和供应商均为虚构。

| 交付 | 文件 |
| --- | --- |
| 表单文案与提交链接 | [可直接复制的填写清单](form-fields.md) |
| 正式版本记录 | [源提交、魔搭提交与 Actions 证据](release.md) |
| 功能与架构 | [作品说明、功能范围、测试及限制](project-brief.md) |
| 三场景结果 | [可复算结果与执行顺序](evidence/scenarios.md)，[公开实例验证摘要](evidence/public-check.json) |
| 五页路演增强版（建议使用） | [PowerPoint](slides/BOM-Pilot-pitch-v2.pptx)，[PDF](slides/BOM-Pilot-pitch-v2.pdf)，[4分30秒讲稿](slides/pitch-notes-v2.md) |
| 原五页路演 | [PowerPoint](slides/BOM-Pilot-pitch.pptx)，[PDF](slides/BOM-Pilot-pitch.pdf)，[三分钟口播](slides/pitch-notes.md) |
| A3 竖版海报 | [A3 高清 PNG](poster/BOM-Pilot-A3.png)，[印刷 PDF](poster/BOM-Pilot-A3.pdf)，[PNG 预览](poster/BOM-Pilot-A3-preview.png)，[海报内容](poster/poster-content.md) |
| Excel 交付样例 | [缺料场景工作台下载](evidence/shortage-release.xlsx) |

路演建议从成本构成切到缺料案。先展示单供应商验收失败，再展示拆单与仍缺 40 个的独立验收。随后打开历史 OpenDev 日志，核对模型曾实际选择拆单并重算。最后展示涨价对照和降本未达目标案例。演示只使用快照数据。

## 截图索引

前五张在 Gradio 6.32.0 下从正式源提交实际运行并截取。它们与公开快捷演示使用同一套数据和计算流程。第六张是此前真实 OpenDev 验证任务的存档截图。公开版在线 OpenDev 本次未调用。

1. [成本分析](screenshots/01-cost-release.png)
2. [涨价后的采购方案对比](screenshots/02-price-release.png)
3. [缺料场景工具调用、重规划与两次验收](screenshots/03-shortage-tools-release.png)
4. [缺料验收、采购缺口和部分小计](screenshots/04-shortage-validation-release.png)
5. [降本 8% 未通过预算验收](screenshots/05-budget-release.png)
6. [历史真实 OpenDev 工具调用](screenshots/06-opendev-historical.png)

PPTX 含演讲备注。画面可从同目录 pitch.html 修改后重新导出，印刷海报可从 poster.html 修改。现场入口使用 [ModelScope 公开创空间](https://modelscope.cn/studios/MONTEC/BOM-Pilot)。

路演增强版增加了输入—工具—交付架构、真实 Agent 一次重规划的详细证据，以及三个场景的成本比较基准。共五页，目标讲解4分30秒，预留30秒缓冲。PPTX页面由高清图像组成并附演讲备注，版面可通过 pitch-v2.html 修改。
