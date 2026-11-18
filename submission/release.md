# 正式版本记录

核对日期：2026-11-18（Asia/Shanghai）。

| 对象 | 已确认版本 |
| --- | --- |
| GitHub 正式源分支 | [feat/gradio-decision-workbench](https://github.com/LINXIAO-LI2025/bom-pilot/tree/feat/gradio-decision-workbench) |
| GitHub 源提交 | [fb952ab98a1cf88ffaf22799ad1c47828e158616](https://github.com/LINXIAO-LI2025/bom-pilot/commit/fb952ab98a1cf88ffaf22799ad1c47828e158616) |
| ModelScope 默认分支 | master |
| ModelScope 部署提交 | 01770d514cbf3c87ad32ec5e6d13c8cb9a1e11ff |
| 同步证据 | [GitHub Actions #44278885063](https://github.com/LINXIAO-LI2025/bom-pilot/actions/runs/44278885063) 的验证及部署作业均成功 |
| 公开入口 | [MONTEC/BOM-Pilot](https://modelscope.cn/studios/MONTEC/BOM-Pilot) |

只读克隆 ModelScope 仓库后，根据部署清单核对了 **22 个受管文件**。每个文件与上述 GitHub 提交逐字节一致，并且 SHA-256 与清单匹配。公开空间状态显示 Running。按官方空间页面提供的嵌入入口访问实际应用，可打开 Gradio 配置并运行工作台。

本阶段将材料放在独立 submission 目录。正式应用及正式源分支仍指向上述提交。材料无需随部署文件同步。

公开实例实际返回 Gradio **6.32.0** 的配置。这里以运行实例的返回值为准。魔搭空间页面的 SDK 声明显示 6.29.1。三个公开快捷场景均实际执行至完成，输出的验收状态和金额已核对。截图由相同正式提交在 Gradio 6.32.0 环境中复现，文件名带 release。历史真实模型截图单独标为 historical。

本轮补充参赛队名 BOM-BOM队。比赛材料保存在独立资料分支 chore/submission-bom-bom，正式应用源分支继续使用上述已验证版本。
