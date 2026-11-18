# BOM Pilot 第三阶段 · Gradio 可视化决策工作台

工作台以中文展示 BOM、成本、决策过程和采购建议。首页自动加载 **20 项虚构 AI BOX 物料及 160 条虚构报价**，在 BOM 管理中可以随时重新加载。示例报价用于验证和演示。

## 启动

已验证 Python 3.12、Gradio 6.32.0 和 Plotly 6.9.0。在仓库根目录执行：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

默认监听本机 7860 端口。开发云环境若需要从自身已有的端口转发进入，通过环境变量 GRADIO_SERVER_NAME 设置监听地址。

| 功能区 | 使用方式 |
| --- | --- |
| BOM 管理 | 上传含 BOM、Quotes 的 XLSX 工作簿，或分别上传 CSV。仅上传物料表时也可以查看物料，缺少报价的物料列入数据质量问题。 |
| 成本分析 | 按批量、币种及报价时点查看单机、整批、折合单机、分类成本图和主要成本物料。 |
| Agent 决策室 | 三个快捷演示调用本地工具。自定义决策在授权发送摘要后启动真实 OpenDev，让模型选择工具并执行独立验收。预算、降本比例和锁定料号支持结构化输入。 |
| 方案对比 | 展示成本、实际可比较时的节省额、库存缺口、约束和待审批项，可下载 Excel。 |

工具记录逐条显示调用来源、轮次、输入和输出。展开任意记录可查完整本地计算证据。缺料时完整成本与节省金额留空，仅单独列出已分配小计。Excel 包含采购建议、成本对比、未满足约束、库存缺口、待审批项及建议 BOM。为保留十进制精度，金额和供应数量字段按文本保存。

模型路径使用已有 JSON Schema 动作。每个供应商查询最多传四条阶梯示例及聚合计数。模型历史保留目标和至多四条近期消息，单个 JSON 请求体最多 12,000 字节，单次任务最多七个请求。每个请求发送 max_tokens=512，累计供应商报告的用量达到 45,000 Token 后停止发出新请求。阈值根据已完成请求的用量判断，当前请求可能越过累计阈值。供应商是否执行单次输出上限由其接口决定。完整报价和工具结果保存在当前会话，结构化未满足约束由本地验收器判定。

## 验证

```bash
.venv/bin/python -m pip install -e '.[ui,test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m pip install 'playwright>=1.50,<2'
.venv/bin/python scripts/smoke_workbench.py --chromium /usr/bin/chromium
```

浏览器冒烟需要应用已启动，检查标签页、绘图、上传校验、三种场景和实际 Excel 下载。可选 --live 会通过界面提交一次真实决策任务并消费 API 用量。本地演示与常规 pytest 不调用模型。

## ModelScope 创空间配置

- 选择 Gradio 创空间，运行时使用 Python 3.11 或更高，建议选择已验证的 Python 3.12。将 app.py 设为入口，并从仓库根目录安装 requirements.txt。提交 src、examples、pyproject.toml 及启动文件。
- 设置 GRADIO_SERVER_NAME=0.0.0.0，GRADIO_SERVER_PORT 使用空间分配的端口，默认 7860。平台代理需支持 Gradio 队列连接。
- 需要在线决策时，在空间的服务端 Secret 配置 OPENDEV_API_KEY，并开放到 api.openai-next.com 的 HTTPS 出站。当前 Codex Cloud HTTP Secret 配置和代理绑定需要在空间重新配置。仅用于公开演示的空间可留空密钥，本地计算、绘图、演示和导出均可使用。
- 当前数据和日志随会话保存，导出是临时下载。应用限制单文件 8 MB、500 行 BOM、10,000 行报价和有限队列。公网上线需在平台侧限制带密钥的运营入口或用量。当前仅在 Codex Cloud 验证，本阶段未发布到 ModelScope。
