# BOM Pilot 第二阶段

第二阶段在第一阶段的 Excel/CSV 引擎之上提供采购求解、验收和 OpenDev 决策。演示产品、供应商、价格和库存均为虚构快照。

| 模块 | 职责 |
| --- | --- |
| `procurement.py` | 按料号计算采购组合，独立重算并验收给定方案 |
| `decision_tools.py` | 创建模拟快照，暴露六项工具，生成建议 BOM 和变更清单 |
| `agent.py` | 校验模型动作、回传工具结果，最多三次重规划 |
| `opendev.py` | 使用 OpenAI Python SDK 接入 OpenDev，与环境代理配合认证 |
| `agent_cli.py` | 执行 A/B/C 或自定义目标，导出 JSON 日志 |
| `scripts/review_agent_demo.py` | 查看实际工具顺序，并独立复算保存的验收结果 |

## 运行

```bash
python -m pip install -e '.[agent,test]'
python -m pytest -q
mkdir -p outputs
bom-pilot-agent --scenario A --output outputs/agent-a.json
bom-pilot-agent --scenario B --output outputs/agent-b.json
bom-pilot-agent --scenario C --output outputs/agent-c.json
python scripts/review_agent_demo.py outputs/agent-a.json outputs/agent-b.json outputs/agent-c.json
```

Agent 命令会访问 OpenDev 并产生用量。将 HTTP Secret `OPENDEV_API_KEY` 绑定为环境占位变量，目标域名为 `api.openai-next.com`。缺少绑定时 CLI 报告 `opendev_secret_unavailable`。日志文件使用独占创建。pytest 使用离线模型传输夹具和 SDK 模拟传输，所有采购、模拟、验证和报告逻辑实际执行。

默认模型为 `claude-opus-5-5`，地址为 `https://api.openai-next.com/v1`。OpenDev 实测首轮能返回原生工具调用，但回传 `role=tool` 后可能返回 HTTP 400。此时控制器将已执行动作和真实结果转成文本消息，继续使用本地严格 JSON Schema 校验动作。可用 `--mode json_schema` 直接选择该模式。SDK 自动重试关闭，单次运行最多 12 个模型回合，协议回退最多增加一次请求。

自定义运行使用 `--context context.json --workbook imported.xlsx`。Agent 会按需将数据摘要及供应商查询结果发送至 OpenDev。只有 Python 接口接受经第一阶段导入函数读取的 CSV，Agent CLI 使用带 BOM 和 Quotes 两张表的 Excel。

```json
{
  "goal": "生产 10 台，尽量降低采购成本，且保持 AI-004 的供应商及分配数量",
  "batch_size": 10,
  "as_of": "2026-11-18",
  "currency": "CNY",
  "budget": "31000",
  "locked_parts": ["AI-004"],
  "disruptions": [
    {"kind": "price_increase_pct", "part_number": "AI-001", "supplier": "虚构供应商-A", "value": "20"}
  ]
}
```

`budget`、`reduction_pct`、`locked_parts` 和 `disruptions` 可选。预算与降幅同时有值时使用较严格的上限。降幅基于同批量、未受扰动的单供应商方案。验收器使用结构化的禁止修改条件，`locked_parts` 固定原方案中指定料号的供应商和数量。模型发现缺少可验证约束时可停止并请求澄清。所有方案使用已录入的料号与报价。建议 BOM 独立输出，本期无替代料兼容性数据，候选列表为空。

## 计算与验收

- 对每个供应商使用指定日期当时最新的报价快照。单一料号可拆单，每个供应商的订单数量必须落在一个有效的阶梯区间，并满足 MOQ、库存、币种和单位。使用整数数量网格做精确搜索，EA/SET 为 1，M/KG 为 0.001。
- 完整方案最小化各条报价金额四舍五入至分后之和。无法足量时先最大化采购量，再最小化部分成本。超出搜索上限返回 `search_limit`，该结果只能说明缺口尚未确认。每项最多搜索 50,000 个单位刻度，每次供应商合并最多 2,000,000 个状态转移。
- 验收器从 BOM 和报价快照重新核对需求、阶梯、库存、锁定分配、订单金额及总额。降本目标预算保留精确比例，例如 8% 的目标预算为 CNY 27,436.424，采购金额仍按分币结算。
- `price_increase_pct` 和 `stock_cap` 作用于指定物料、供应商的当前快照副本。`pending_review` 表示通过独立验收后待人工审批，`blocked` 表示验收失败或执行未完成。
- 当前使用精确需求、单币种及静态快照。采购超量、组合折扣、共享库存、交期、实时供应商查询、替代料和交易执行属于后续工作。

## 虚构场景的真实执行

使用 `claude-opus-5-5`，表中用量来自完成场景的运行。HTTP 错误请求没有返回用量。

| 场景 | 请求 | 输入 / 输出 Token | 独立验收 |
| --- | ---: | ---: | --- |
| A | 7 | 90,331 / 2,028 | 受影响物料换至 B 供应商，保留 AI-004 锁定分配。原成本 29,822.20，涨价后沿用原分配为 33,902.20，建议方案 30,434.20。相对原价 +2.05%，相对沿用原分配节省 3,468.00 |
| B | 7（一次 HTTP 400 后切换协议） | 41,701 / 1,424 | 一次重规划。风扇缺口从 120 个降至 40 个。已分配小计 268,099.20，完整总额为空 |
| C | 5 | 33,171 / 2,201 | 可行最低成本 29,822.20，变化率 0%，比 8% 目标预算高 2,385.776 |

本次环境日志在 `outputs/agent-{a,b,c}-final.json`。日志结构包括 `context`、`model_turn`、`tool_call`、`provider_error` 和 `finished`。工具记录含轮次、调用 ID、动作、参数、结果和执行来源。`model` 表示由模型选择，`controller` 表示应用补做了独立验收或报告。SDK 请求头和密钥不进入日志。

## 第三阶段 Gradio 接入

上传页使用现有导入和校验函数，展示数据错误和虚构标识。表单收集自然语言目标以及结构化批量、预算、禁止修改项和模拟事件，每次运行创建独立会话。用 `DecisionRun.log` 展示工具顺序、轮次和用量，用 `validation` 展示缺口、预算及锁定验收，用 `report` 下载建议 BOM 和报告。部署 ModelScope 时在服务端绑定 Secret，并从服务端调用 OpenDev。
