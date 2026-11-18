# GitHub Actions → ModelScope

源分支为 LINXIAO-LI2025/bom-pilot 的 feat/gradio-decision-workbench。手动工作流先用 Python 3.12 安装依赖、运行 pytest，并验证 app.py 默认监听 0.0.0.0。随后在独立作业克隆 MONTEC/BOM-Pilot 的默认分支，从选定的 GitHub 提交同步部署文件，正常推送并核对远端提交。

ModelScope 创空间使用 Gradio 6.29.1，requirements.txt 已对齐该版本。空间采用默认 Gradio 入口 app.py，保留 ModelScope README 与 .gitattributes。空间 Python 需满足项目的 Python 3.11+ 要求，GitHub 使用 3.12 验证。部署和测试无需 OpenDev Key。

## 手动运行

1. 在 GitHub 仓库的 Actions 页选择 **Deploy to ModelScope**。
2. 点击 **Run workflow**，选择 **feat/gradio-decision-workbench**，再点击 **Run workflow**。
3. 打开新的运行，查看 **validate** 和 **deploy** 两个作业。成功的部署步骤会显示经远端确认的魔搭提交 SHA。

GitHub 仓库需要 Actions Secret **MODELSCOPE_TOKEN**，其所属账号须对目标空间有 Git 写权限。Git 用户名默认 MONTEC。若令牌属于另一个有写权限的魔搭账号，在 GitHub 的 **Settings → Secrets and variables → Actions → Variables** 配置 **MODELSCOPE_USERNAME**。令牌经作用域限定的 Git credential helper 传递。

首次部署如遇到同名且内容不同的文件会停止。之后通过魔搭仓库中的部署清单检测人工修改。核对差异并解决冲突后可重新运行。远端分支若在工作流运行期间被推进，普通 Git 推送会拒绝非快进更新。同步范围限于 app.py、requirements.txt、pyproject.toml、src/bom_pilot 下的 Python 源码、四个演示数据文件及部署清单。

## 查看魔搭构建日志

打开 [BOM-Pilot 创空间](https://www.modelscope.cn/studios/MONTEC/BOM-Pilot)。先在 **文件** 页检查默认分支 master 的提交 SHA 是否与 GitHub Actions 中验证的 SHA 一致。用具备管理权限的账号打开空间的构建/运行状态，并进入 **日志**（部分界面在 **管理** 或构建失败状态旁显示）。先检查依赖安装、Python 版本和 Gradio 启动，再打开应用页。Git 推送成功表示源码同步完成，创空间的构建状态单独确认。
