<div align="center">
  <img src="./assets/app_icon.png" width="88" alt="地平线行者每日助手图标">
  <h1>地平线行者每日助手</h1>
  <p>把每天重复点的日常交给助手。选好任务、点一次开始，从收贡品跑到领积分宝箱。</p>
  <p>
    <img src="https://img.shields.io/badge/平台-Windows-blue" alt="Windows">
    <img src="https://img.shields.io/badge/客户端-Steam-171A21" alt="Steam">
    <img src="https://img.shields.io/badge/首发版本-v1.0.0-2EA44F" alt="v1.0.0">
  </p>
  <p>
    <a href="https://github.com/moxinbaige/ok-horizon-walker/releases/latest">📥 GitHub 下载</a> ·
    <a href="https://pan.baidu.com/s/19hvCqjPxX2SMypBDnicbWQ?pwd=1111">☁️ 百度网盘</a> ·
    <a href="#快速上手">🚀 快速上手</a> ·
    <a href="#问题反馈">🛠️ 问题反馈</a> ·
    <a href="https://cnb.cool/moxinbaige/ok-horizon-walker/-/blob/main/SPONSOR.md">💖 支持开发</a>
  </p>
</div>

## 免责声明

> **本项目是《地平线行者》的第三方自动化脚本，仅供学习与交流使用。** 脚本通过截图识别和模拟操作与游戏交互。
>
> 使用前，请了解并遵守游戏及平台的相关规则。使用本脚本产生的风险和后果由使用者自行承担。使用本脚本即视为已阅读、理解并同意本声明。

## 能帮你做什么

| 任务 | 助手怎么跑 |
| --- | --- |
| 🪙 贡品、资源和商店 | 收贡品与累计资源，领取商店的免费光辉币。 |
| ✨ 金币愿望 | 挑选奖励为光辉币的愿望，最多做三次。 |
| ⚔️ 危险区域 IV 讨伐 | 从 14 个目标中选一项。当天首轮先打，剩余次数再扫荡。 |
| 🛡️ 复原作战和邮件 | 处理复原奖励，沿用原队伍重新任命，并领取邮件奖励。 |
| 🎁 每日积分 | 积分达到 100 后，领取五档积分宝箱。 |
| 🎉 活动每日 | 开启后处理已适配活动的签到和领奖。带战斗的活动可按设置扫荡，每游戏日上限可选 0–4 次。 |

**首页每日签到请手动领取。** 活动签到由「活动每日」单独处理。没有可扫荡的战斗时，活动积分可能拿不满。

## 快速上手

1. **下载并解压。** 从 [GitHub Releases](https://github.com/moxinbaige/ok-horizon-walker/releases/latest) 或 [百度网盘（备用，提取码 `1111`）](https://pan.baidu.com/s/19hvCqjPxX2SMypBDnicbWQ?pwd=1111) 下载 Windows 便携 ZIP。完整解压后双击 `HorizonDaily.exe`，确认 Windows 管理员提示。
2. **设置本轮任务。** 打开 Steam 版游戏并停在首页。在助手的「任务 → 每日任务」选择要执行的步骤和讨伐目标。
3. **开始运行。** 到「运行概览」点「开始每日任务」。需要中途停止时按 **F9**。

使用简体中文游戏界面和 **16:9** 画面，推荐 **1920×1080**。游戏窗口可以被其他窗口遮挡，请保持展开。助手点击时可能短暂移动鼠标。

## 更新版本

启动时会检查 GitHub 的最新正式版，也可以在「关于」页手动检查。发现新版后点「前往下载」，再把新 ZIP 解压到单独的文件夹。想保留任务设置和运行记录，可在关闭两个版本后将旧版的 `configs` 文件夹复制到新版。

## 问题反馈

遇到卡住或领漏的情况，先看「运行概览」里最后停在哪一步。当最近一轮有错误记录时，可生成本地反馈包，并预览、选择要附上的截图。分享前请检查截图中的昵称和账号信息。

反馈时附上**助手版本、游戏分辨率、出错步骤和提示**，更容易复现。详见 [反馈包说明](./docs/feedback.md)。

## 从源码运行

在 Windows 上安装 Python 3.12，在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start-HorizonDaily.cmd
```

如果游戏以管理员身份运行，请在管理员终端执行启动命令。

## 致谢与支持

助手基于 [ok-script](https://github.com/ok-oldking/ok-script) 开发。

项目可以免费下载和使用，欢迎在 [GitHub](https://github.com/moxinbaige/ok-horizon-walker) 点个 Star，或通过 [CNB 赞赏页](https://cnb.cool/moxinbaige/ok-horizon-walker/-/blob/main/SPONSOR.md) 自愿支持。
