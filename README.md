# BOM Pilot · AI Hardware Decision Agent

第二阶段已加入拆单优化、独立验收及 OpenDev 决策。使用方法和演示验收见 [第二阶段文档](PHASE2.md)。以下是仍可独立运行的第一阶段数据引擎。

## 第一阶段：可复算的 BOM 数据引擎

面向 AI 硬件的本地 Python 库与命令行工具，使用 pandas、openpyxl、pytest。**不调用大模型、不读取 API Key、不连接供应商平台、没有网页 UI，也未部署到 ModelScope。** 第一阶段的数据引擎和 CLI 均可独立运行。

**examples/ 下的产品、料号、供应商、价格、库存均为虚构数据（FICTIONAL），仅供软件测试，不可用于实际采购。** 标识保存在 CSV 每行、Excel NOTICE 工作表以及计算结果的 `data_notices` 中。

## 快速运行

Python 3.11+；本次在 Python 3.12.14 下验证。当前 `.venv` 已安装，可直接使用：

```bash
cd /workspace/bom-pilot
.venv/bin/python -m pytest -q
.venv/bin/bom-pilot --workbook examples/ai_box_demo.xlsx \
  --batch 100 --as-of 2026-11-18 --compare-from 2026-10-01 \
  --output outputs/my-report.json
```

输出路径父目录需已存在；CLI 使用独占创建，已有文件会报错，绝不覆盖。去掉 `--output` 则打印 JSON。报告同时包含独立计算的 `single_unit`、`batch`，以及可选 `price_changes`。

重建依赖环境（选择一个尚不存在的虚拟环境目录，不要覆盖用户环境）：

```bash
python -m venv .venv-new
.venv-new/bin/python -m pip install -r requirements-tested.txt
.venv-new/bin/python -m pip install --no-deps -e .
.venv-new/bin/python -m pytest -q
```

`pyproject.toml` 给出兼容范围，`requirements-tested.txt` 记录本次实际验证的完整第三方版本（含测试工具）。常规开发也可 `pip install -e '.[test]'`。

CSV 方式：

```bash
.venv/bin/bom-pilot --bom examples/ai_box_bom.csv \
  --quotes examples/supplier_quotes.csv --batch 10 --as-of 2026-11-18
```

库接口不依赖 CLI、UI、LLM 或进程环境：

```python
from bom_pilot import load_workbook, normalize_bom, normalize_quotes, calculate, compare_prices
b, q = load_workbook("examples/ai_box_demo.xlsx")
bom, quotes = normalize_bom(b), normalize_quotes(q)
result = calculate(bom, quotes, batch_size=100, as_of="2026-11-18", currency="CNY")
changes = compare_prices(bom, quotes, "2026-10-01", "2026-11-18", batch_size=1)
# result 是 JSON 可序列化字典，所有十进制数字输出为字符串。
```

## 项目目录

```text
src/bom_pilot/
  io.py          CSV / Excel 导入，拒绝公式单元格
  normalize.py   字段别名、单位、数值和数据质量校验
  models.py      诊断结构、Decimal 精度及 JSON 边界
  engine.py      数量选价、库存约束、成本构成、历史重估
  cli.py         命令行及独占创建 JSON 文件
examples/
  ai_box_bom.csv               20 项 AI BOX 虚构物料
  supplier_quotes.csv         160 行：20 物料 × 2 供应商 × 2 日期 × 2 阶梯
  ai_box_demo.xlsx            同样的数据，BOM / Quotes / NOTICE 三个工作表
  supplier_quotes_invalid.csv 另加一条故意缺价的虚构报价（共161行）
scripts/generate_demo.py       样例生成器，已有目标文件时拒绝覆盖
tests/test_engine.py           成本、校验、I/O、CLI 和回归测试
outputs/demo-report.json       本次实际生成的完整审计结果（本地生成物）
requirements-tested.txt        本次验证依赖版本
```

## 输入字段

CSV 为 UTF-8 / UTF-8 BOM 编码；Excel 仅支持 `.xlsx`，工作表名分别是 `BOM`、`Quotes`。第一行为表头。缺失必需列、重复/别名冲突的列名、空文件及公式直接抛出错误；值错误则保留行级诊断，排除无效行。额外列可存在，除 `data_notice` 外不参与计算。

BOM 每行一项物料，**不允许重复料号**：

| 标准字段 | 中文表头别名 | 含义 |
|---|---|---|
| part_number | 料号 | 字符串、非空；NFKC 规范化、去首尾空格、转大写 |
| description | 物料名称 | 非空名称 |
| category | 类别 | 非空成本分类 |
| quantity_per_unit | 单机用量 | 单机消耗数量，严格大于零 |
| unit | 单位 | EA、M、KG、SET；接受 pcs/pc/个/件、米、千克、套等别名 |
| data_notice | 无 | 可选来源/虚构标识，传递到结果 |

报价每行是一条数量阶梯：

| 标准字段 | 中文表头别名 | 含义 |
|---|---|---|
| quote_id | 报价编号 | 规范化后全表唯一，非空 |
| part_number | 料号 | 与 BOM 同规则 |
| supplier | 供应商 | 非空供应商标识；NFKC、去空格、转大写 |
| quote_date | 报价日期 | 严格 YYYY-MM-DD；不接受 Excel 日期公式或日期时间格式 |
| currency | 币种 | 三字母代码；必须与计算币种完全匹配，不换汇 |
| unit | 单位 | 必须与 BOM 标准单位匹配，不换算米/毫米等比例 |
| unit_price | 单价 | 非负十进制；空值是缺价，显式 0 是有效零价 |
| min_qty | 阶梯起量 | 含边界的最低数量，可为0 |
| max_qty | 阶梯上限 | 可选，空值/缺列表示无上限；含边界 |
| moq | 最小起订量 | 可选列，缺列默认1；提供时须严格大于0 |
| stock_qty | 库存 | 该供应商该物料的快照库存，不是每阶梯独立库存 |
| data_notice | 无 | 可选来源/虚构标识 |

数值接受普通十进制，至多6位小数，范围0至1e9（用量与MOQ不含0）；不接受千分符、科学计数法、负数、NaN、Inf 或隐式货币符号。批量台数必须为1至1e9的整数。料号前导零在 CSV 文本中保留；Excel 料号必须按文本存储，不能恢复已被 Excel 当数值丢掉的零。请将日期列存为 ISO 文本。

## 计算及审计规则

1. 指定时点 `as_of`，对每个供应商取该物料最新的有效日期快照；未来报价不参与。一个供应商/物料/日期只有一个快照，其阶梯库存、MOQ、单位及币种必须一致，区间不允许重叠。一个阶梯无效会排除整个快照。
2. `required_qty = quantity_per_unit × batch_size`。当前精确采购需求，不拼单、不超买、不拆分供应商、不合并库存，不允许使用不满足MOQ的低价。
3. 在币种、单位、MOQ、阶梯、库存均匹配的报价中，选择四舍五入后的行成本最低者。并列按单价、供应商和报价编号排序；不把过期旧快照当作现行的便宜替代。
4. `line_cost = ROUND_HALF_UP(required_qty × unit_price, 0.01)`；以 Decimal 计算，每行先保留两位再汇总，不用二进制浮点核算。`total_cost = Σ line_cost`。批量的 `equivalent_unit_cost = total_cost ÷ batch_size`，可能是长小数，不等于单独采购一台的报价成本。
5. `composition` 按类别汇总已定价行金额与已定价小计占比。分母为0时占比为null。部分数据的占比只说明已定价部分，不能当成完整 BOM 构成。
6. 每行保留需求数量、供应商、报价编号/日期、单位价、MOQ/区间/库存、行成本和输入行号；`candidate_audit` 保留最新候选报价及拒绝原因，支持独立复算。
7. 重复料号全部排除，不静默去重或累加；缺价不按0计算；不满足库存的合格阶梯标为 `shortage`，没有匹配阶梯/MOQ/币种/单位则 `no_eligible_quote`，没有时点内有效报价则 `missing_quote`。
8. **只要任意输入有错误，或任意物料无可采购报价，`complete=false`，`total_cost` 与 `equivalent_unit_cost` 为null。** `priced_subtotal` 只作部分/暂估小计。诊断包含表名、原始行号、字段、错误码与原因。无效报价导致旧快照暂估仍可能出现，但会被标为输入无效，不能据此下单；修正输入后再计算。
9. `compare_prices` 固定同一BOM及采购台数，在两个时点重估，输出逐料成本差、百分比和供应商/报价变化。基准价为0或某一侧缺价时百分比为null；一侧不完整时总成本差为null。该变化包括供应商切换、库存、MOQ影响，不是纯市场价格指数。输入数据错误在所有时点均保守阻止完整总额。

金额按输入币种最小计算精度0.01处理；只包含给定单价，税费/运费含义由上游数据统一约定，本阶段没有额外税费模型。不会混合币种，也不做货币代码官方注册表校验。库存是计划约束，不产生锁库或采购订单。

## 已验证的演示结果

以 2026-11-18 为时点：

- 1台：完整20项，**CNY 2,982.40**。
- 10台：完整批量采购成本 **CNY 29,822.20**，折合单台 CNY 2,982.22（螺丝进入数量折扣阶梯）。完整结果见 `outputs/batch10-report.json`。
- 100台：AI-008 风扇需要200个，每家虚构供应商仅80个库存；单供应商策略下缺120个。只返回19项已定价小计 **CNY 265,176.00**，整批总额为null。
- `supplier_quotes_invalid.csv` 中故意缺失报价单价。即使其他供应商能覆盖该物料，仍标记输入错误、阻止完整总额。
- CSV/Excel结果一致，公式拒绝、零价、前导零、阶梯边界、MOQ、库存、历史报价、无效数据、行金额复算、类别对账、JSON导出及拒绝覆盖均有自动化测试。

实际测试结果及本次完整JSON见工作区输出。重新生成样例时使用新的空目录；生成器不会覆盖现有样例。

## 功能边界与扩展方向

第一阶段提供确定性的**数据工具层**。仅支持单层BOM和静态供应商快照；没有多级展开、替代料、跨供应商拆单、MOQ超买、折扣组合优化、损耗/良率、税运费、汇率、交期、预测或实时库存。第一阶段入口仅运行数据工具。

下一阶段建议先为需求、工具输入/输出建立版本化JSON Schema，增加缺料/交期/报价过期的采购风险工具，以及可解释的拆单/MOQ优化；明确税运费和库存口径后再接入Agent。将 `calculate` / `compare_prices` 包装为只读工具，LLM负责解释及编排、引擎继续负责所有数值计算。最后添加轻量 Gradio 上传与审计表格页，并为ModelScope添加依赖、启动文件和平台Secret绑定；所有真实调用需独立验证和调用预算。本阶段没有保存或更改云环境发布配置。
