# 第三方来源与复用声明

ContentFlow是课程工作流应用，视频搜索、下载、配音、字幕和合成引擎复用MoneyPrinterTurbo，不能把上游能力描述为本项目从零实现。

| 项目 | 来源/固定版本 | 使用边界 |
| --- | --- | --- |
| MoneyPrinterTurbo | [官方仓库](https://github.com/harry0703/MoneyPrinterTurbo)，commit 436b0e9cc830ef7639e33388917e389cf30d3307，API1.3.6 | 外部独立进程，REST任务与素材服务；本仓库不携带其源码、虚拟环境、媒体或私有config |
| edge-tts | [官方项目](https://github.com/rany2/edge-tts)，7.3.1独立覆盖 | 原MPT锁为7.2.7；经用户批准覆盖，锁文件未改；仅免费联网路径实测，无长期可用保证 |
| Streamlit / toml | requirements.lock.txt所列版本 | ContentFlow网页及本机TOML写入；具体包许可随依赖安装保留 |
| MoviePy / FFmpeg | MPT锁定MoviePy2.2.1；旧机捆绑FFmpeg7.1 | 媒体处理在上游环境；FFmpeg许可取决于实际构建，分发二进制需另行核对，本仓库不分发 |
| DeepSeek | 现有账户，显式deepseek-flash | ContentFlow单次结构化生成，不重试计费/不切换Pro；服务条款独立适用 |
| Pixabay | [API说明](https://pixabay.com/api/docs/)、[内容许可摘要](https://pixabay.com/service/license-summary/) | 搜索缓存、素材许可和来源追踪；免费获取不代表所有用途无限制，素材与人物等权利需分别核查 |

MoneyPrinterTurbo为MIT许可，Copyright (c) 2024 Harry。完整原文保留在 [third_party/MoneyPrinterTurbo-LICENSE.txt](third_party/MoneyPrinterTurbo-LICENSE.txt)，从本机固定上游LICENSE逐字复制，未修改。后续若复制/分发上游源码，须继续保留原许可和版权；本文件不替代各依赖自身许可证。

Windows字体使用本机已有授权字体，未上传字体文件。网页/视频截图用于展示真实项目成果，保留Pixabay素材来源，不能当作独立素材包再销售/分发。当前在线样片使用来源为Pixabay视频172759、323176、267095、202753；作者和关键词详见 [真实联调报告](docs/第006轮Pixabay真实联调报告_公开版.md)。

本轮未为ContentFlow自身选择新的开源授权许可证；技术上准备公开不等于已经完成许可选择。GitHub发布前需由作者确认ContentFlow自身代码的授权方式，本轮不擅自套用上游MIT为整个项目授权。
