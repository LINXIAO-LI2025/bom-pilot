# BOM-BOM队 · 报名表填写清单

以下按常见作品提交字段整理。截图目前仅显示赛道选择，具体字段名称请以表单为准。队名和作品名统一使用本页文本。

## 队名

BOM-BOM队

## 作品名称

BOM Pilot｜AI Hardware Decision Agent

## 一句话介绍

面向 AI 硬件团队的 BOM 智能采购决策工作台，让 Agent 根据采购目标选择工具、验证方案，并在约束不满足时调整或报告原因。

## 作品简介 · 精简版

BOM Pilot 是面向 AI 硬件团队的智能采购决策工作台。支持 BOM 导入、成本分析、供应商拆单和库存约束验证。Agent 可根据自然语言目标选择工具、计算并验收方案，失败后最多重规划三次。系统保留工具记录，导出采购建议和待审批清单。现有演示报价与库存均为虚构数据。

## 作品简介 · 完整版

BOM-BOM队开发的 BOM Pilot，面向 AI 硬件研发与采购团队，将 BOM、供应商报价、数量阶梯、MOQ 和库存放在统一约束下分析。系统支持 Excel/CSV 导入、单机与批量成本分析、拆单采购、扰动模拟和方案对比。Agent 可理解自然语言目标，自主选择分析工具，再由独立 Python 验收器复算数量、金额、预算及锁定条件；验收失败时最多重规划三次，并保留实际执行记录。采购建议以独立版本和 Excel 导出，进入人工审批。作品已部署到 ModelScope，86 项自动化测试通过。已验证涨价、缺料和降本三个虚构样本场景，并如实展示仍缺料、未达降本目标的结果。所有演示价格与库存均为虚构快照。

## 团队简介

BOM-BOM队聚焦 AI 硬件产品中的物料成本与采购决策问题，围绕“目标—工具执行—独立验收—方案调整”构建可追溯的决策流程，致力于让硬件团队更清楚地评估采购成本、库存缺口和方案可行性。

## 技术方案或项目亮点

- 自主决策：根据自然语言目标选择工具，依据实际验收结果决定重规划或说明受阻原因。
- 可复算：Python 工具按录入报价核算数量、金额、MOQ 与库存，独立检查预算和禁止修改条件。
- 可追溯：保留真实工具调用与验收日志，支持成本对比和 Excel 交付。
- 可体验：ModelScope 中文 Gradio 工作台提供三种一键演示，样本明确标为虚构。

技术栈为 Python、pandas、openpyxl、Gradio、Plotly、OpenAI 兼容 SDK / OpenDev，以及 GitHub Actions。历史真实 Agent 验证使用 claude-opus-5-5，公开快捷演示通过本地工具运行。本次材料修订未发起模型调用。

## 作品体验链接

https://modelscope.cn/studios/MONTEC/BOM-Pilot

推荐填入“作品链接”“在线演示”或“魔搭创空间链接”栏。

## 代码仓库链接

https://github.com/LINXIAO-LI2025/bom-pilot

如表单要求可复现的正式版本，填写固定提交地址：

https://github.com/LINXIAO-LI2025/bom-pilot/tree/fb952ab98a1cf88ffaf22799ad1c47828e158616

## PPT 链接

https://github.com/LINXIAO-LI2025/bom-pilot/blob/chore/submission-bom-bom/submission/slides/BOM-Pilot-pitch.pptx

浏览器可预览的 PDF 版本：

https://github.com/LINXIAO-LI2025/bom-pilot/blob/chore/submission-bom-bom/submission/slides/BOM-Pilot-pitch.pdf

## 海报链接

https://github.com/LINXIAO-LI2025/bom-pilot/blob/chore/submission-bom-bom/submission/poster/BOM-Pilot-A3.pdf

海报 PNG 预览：

https://github.com/LINXIAO-LI2025/bom-pilot/blob/chore/submission-bom-bom/submission/poster/BOM-Pilot-A3-preview.png

## 其他资料链接

包含作品说明、技术架构、测试范围、场景证据和演讲稿：

https://github.com/LINXIAO-LI2025/bom-pilot/tree/chore/submission-bom-bom/submission

完整资料包：

https://github.com/LINXIAO-LI2025/bom-pilot/blob/chore/submission-bom-bom/submission/BOM-Pilot-submission.zip

## 填写边界

- 海报、PPT 栏若接受链接，可填上述地址。若仅支持上传，请下载对应文件后上传。
- 成员姓名、学校/单位、联系方式、队长及到场安排需填写团队真实信息。
- 截图可见“出海（1–4人）”选项，其他赛道和规则未展示，应按实际报名赛道选择。
- 若要求视频链接，当前材料包没有路演视频，不填成已提供；可填写“暂未提供”或留空（以表单要求为准）。
- 演示数据是虚构快照。降本 8% 案例未达成，缺料案例拆单后仍缺 40 个，不能填为已解决。
