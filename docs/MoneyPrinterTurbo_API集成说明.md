# MoneyPrinterTurbo API 集成说明

2026-11-01 最新结果：Pixabay 是唯一在线素材来源，停用 Pexels/Coverr。用户本机配置已生效；已按明确人工审核实际创建任务 045395ae-0ddd-48a1-8aaa-95db07c3970c，得到18.67秒、1080×1920中文配音/字幕MP4。审核后的完整脚本/四词直接传入，无重复LLM调用记录；一次Flash请求共309 tokens。下载及全片解码通过，浏览器实际播放/主观试听待验收，末段画面存在语义偏差。[真实请求和结果报告](第006轮Pixabay真实联调报告_公开版.md)。下方旧轮次保留历史；第13节初查后续结果见第14节，历史“默认Pexels”不再适用。

第 006 轮修订：默认改为在线库存素材，ContentFlow 一次 DeepSeek JSON 请求返回 title/script/video_terms，审核后完整传给 1.3.6 视频 API。Pexels 默认、Pixabay 主动备用，本地 MP4 不再是默认。程序已实现；初始本机三类 Key 缺失，真实在线两主题验收未执行。历史轮次说明保留，最新依据见第 12 节。

最新状态（第 005 轮）：固定 **1.3.6** API 已实际完成素材上传、单次视频任务、状态查询和 MP4 下载，地址 `http://127.0.0.1:8080`。独立环境经批准覆盖 edge-tts 7.3.1，源码和 uv.lock 不变；视频技术检查通过，播放器操作中止、主观试听未完成。最新证据见第 11 节；第 1–9 节保留第 003 轮 main 审查背景，第 10 节保留第 004 轮部署结果。

日期：2026-10-31；阶段：第 003 轮，源码审查及只读检测工具开发。

## 1. 核验依据与限制

核验官方仓库 [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) 的当前 main。直接获取了 Schema、视频 Controller、鉴权、配置、Provider、素材上传、视频预处理、语音、任务、工具函数、状态常量、ASGI 和 pyproject 源码到系统临时目录，只读分析，未执行或修改上游代码。

GitHub commit API 返回 HTTP 403 rate limit，未锁定 commit；逐文件读取 main 也不保证原子版本快照。[源码指纹清单](evidence/mpt_source_manifest.json) 记录 14 个实际获取文件的 URL 和 SHA-256，可辅助比对，但不能代替完整源码归档或 commit 锁定。临时副本不作为持久交付物。LLM 服务和路由基础文件通过浏览工具补充核对，未纳入该哈希清单。

下文区分“源码确认”与“运行通过”。当前默认服务地址只读检测超时；没有服务端 OpenAPI 实测结果、上传结果、生成任务或成片。JSON 示例是依据源码写出的说明，不是实际 API 响应。

## 2. DeepSeek 原生配置

上游配置加载器读取其运行目录的 `config.toml`。`[app]` 下的真实字段为：

| 配置字段 | 本项目意图 |
| --- | --- |
| llm_provider | deepseek |
| deepseek_base_url | https://api.deepseek.com |
| deepseek_model_name | deepseek-flash，显式设置 |
| deepseek_api_key | 由用户通过本地私有方式配置真实值；本文不保存任何凭证 |
| api_key | 可选的 MPT 本地 API 访问凭证，与 DeepSeek 凭证不同 |

Provider 注册表当前默认模型是 `deepseek-v4-pro`，不是 Flash；LLM 服务按 Provider 前缀读取上述字段并解析模型/地址，原生 Provider 使用兼容协议，不需要另购其他 LLM 服务。[Provider 源码](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/models/llm_provider.py)、[LLM 服务源码](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/services/llm.py)

官方模型文档当前列出 `deepseek-flash`。是否对账户开放、余额适用性、思考参数及扣费均未调用验证；本轮不发模型请求。[DeepSeek 官方模型文档](https://api-docs.deepseek.com/quick_start/pricing/)

不能假定设置 `DEEPSEEK_API_KEY` 或放置 `.env` 就被上游自动读取：所查配置/LLM 路径使用 TOML 字段。后续若采用环境变量，需由已验证的配置桥接方式注入。首次部署将顶层 `listen_host` 显式设为 `127.0.0.1`；上游示例默认是 `0.0.0.0`。[配置示例](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/config.example.toml)、[加载器](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/config/config.py)

## 3. 接口与鉴权概览

路由前缀 `/api/v1` 来自 [路由基础文件](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/controllers/v1/base.py)。以下路径以服务根地址为基准。

| 方法 | 路径 | 请求及结果 |
| --- | --- | --- |
| GET | /openapi.json | 获取 OpenAPI 3 描述，本轮检测工具唯一发送的请求 |
| POST | /api/v1/scripts | 中文脚本生成，返回 data.video_script；可能计费，本轮不调用 |
| POST | /api/v1/video_materials | multipart/form-data，必需字段 file；返回 data.file |
| GET | /api/v1/video_materials | 返回 data.files 列表，含 name、size、file |
| POST | /api/v1/videos | JSON TaskVideoRequest；返回 data.task_id，表示已接受任务 |
| GET | /api/v1/tasks/{task_id} | 返回 data 中的状态及产物信息 |
| GET | /api/v1/download/{file_path} | 返回文件内容，不是 JSON；服务端源码路径写作 {file_path:path} |
| GET | /api/v1/stream/{file_path} | 视频预览，支持 Range；OpenAPI 中不含 :path |

上游 `verify_token` 在 `[app].api_key` 为空时放行，非空时要求恰好一个匹配的 `x-api-key` 请求头，不匹配或重复头返回 401；配置类型不对可返回 500。`/api/v1` 的路由依赖及 `/tasks` 静态产物中间件实施检查。当前 ASGI 的 OpenAPI 文档不受同一个任务静态文件中间件保护，所以成功获取 OpenAPI **不能证明业务鉴权通过**。反向代理仍可额外保护 OpenAPI。[鉴权源码](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/controllers/base.py)、[ASGI 源码](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/asgi.py)

业务响应采用 `status`、`message`、`data` 包装；查询状态应看 `data.state`，不能把 HTTP 200 或包装 status=200 当作生成成功。

## 4. 本地素材：上传后如何引用

源码调用链：视频 Controller 接收 `file` → `save_material_upload` 校验并存储 → 返回 UUID 文件名 → 生成阶段 `preprocess_video` 在受管素材目录中解析该文件名。

说明性上传返回（非实测）：

```json
{"status": 200, "message": "success", "data": {"file": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4"}}
```

`data.file` 是服务端存储标识，通常为 UUID hex 加扩展名。素材列表中的 `file` 同样是文件名，不再是客户端路径。上传文件保存在服务端运行根的 `storage/local_videos` 下。[上传服务](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/services/material_upload.py)

后续构造 `video_materials` 时，设置 `provider="local"`，将上传返回的 `data.file` 原样用作 `url`。尽管字段名为 url，此处代表服务端素材目录中的相对引用。预处理器显式在 `local_videos` 目录内解析，拒绝目录逃逸；兼容部分历史绝对路径不代表应由客户端任意传路径。[视频预处理源码](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/services/video.py)

不能用 `D:\用户目录\原始视频.mp4`、Streamlit 临时文件路径或 `/tasks/...` 成片地址替代上传返回标识。ContentFlow 与 MPT 即使在同一电脑，也遵循“上传 → 保存服务端引用 → 提交该引用”的边界。

上游支持多种媒体，上传视频上限为 200 MiB、图片 20 MiB，并执行解码校验；ContentFlow 需求仍限制 MP4、100 MB、最多 3 个。较宽的上游限制不自动放宽项目需求。上传校验本身需要可工作的媒体环境，不是只有合成阶段才需要准备 FFmpeg。

## 5. 视频生成参数及响应

`TaskVideoRequest` 继承 `VideoParams`。Schema 中无默认值的主要必需字段为 `video_subject`；但想按本项目安全生成，不能仅传主题依赖其他默认值。[Pydantic Schema](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/models/schema.py)

| 字段 | Schema/业务含义 | ContentFlow 提交策略 |
| --- | --- | --- |
| video_subject | 必需字符串 | 已确认主题 |
| video_script | 默认空；空值会触发 LLM | 必须传非空审核稿，避免隐式二次文案生成 |
| video_source | 默认 pexels | 显式 local |
| video_materials | MaterialInfo 列表，默认空 | 至少一项，url 为上传返回文件名 |
| video_aspect | 9:16 / 16:9 / 1:1 | 固定 9:16，当前对应 1080×1920 |
| video_count | API 限 1–5，默认 1 | 固定 1 |
| video_clip_duration | API 限 1–15，默认 5 秒 | 使用固定模板值，非整片精确时长 |
| n_threads | API 限 1–16，默认 2 | 先保留 2 |
| voice_name | 默认空，不能据此保证配音 | 显式中文 Edge 音色，需后续验证 |
| subtitle_enabled | 默认 true | true，且服务配置 subtitle_provider=edge |
| font_name | 默认 STHeitiMedium.ttc | 必须确认字体实际存在且支持中文 |
| bgm_type / bgm_volume | 默认 random / 0.2 | 空字符串 / 0，关闭配乐 |

说明性创建请求（本轮未发送）：

```json
{
  "video_subject": "专注学习",
  "video_script": "先确定一个小目标，再专注完成它。",
  "video_language": "zh-CN",
  "video_source": "local",
  "video_materials": [
    {"provider": "local", "url": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4", "duration": 0}
  ],
  "video_aspect": "9:16",
  "video_count": 1,
  "video_clip_duration": 5,
  "voice_name": "zh-CN-XiaoxiaoNeural-Female",
  "subtitle_enabled": true,
  "font_name": "STHeitiMedium.ttc",
  "bgm_type": "",
  "bgm_volume": 0
}
```

示例素材名仅为占位，不能直接运行。MaterialInfo.duration 默认 0，本地预处理会打开实际媒体；音色和字体仅有源码依据，未运行。提交成功包装的稳定数据字段是 `data.task_id`，不是成片 URL；异步队列满可返回 429。默认值和非法值响应需以锁定版本 `/docs` 再确认。

## 6. 状态及成片下载

TaskStatusData 声明 `task_id`、`state`，`progress` 默认 0，可选 `videos`、`combined_videos`、`failed_stage`、`error`，允许额外扩展字段。[状态 Schema](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/models/schema.py)

当前状态常量：-1 失败、1 完成、4 处理中；未知值按“需核对”处理，不能猜成成功。查询不存在的任务返回 404。[常量](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/models/const.py)

Controller 将合法本地产物路径转换为 `/tasks/{task_id}/{file}` 形式，可按 endpoint 配置带服务前缀。使用 `videos` 中返回的地址时要验证可信服务来源。若选择下载接口，则将已经确认的 tasks 目录内相对路径（如 `{task_id}/final-1.mp4`）放到 `/api/v1/download/` 后，逐段 URL 编码；不要把完整 HTTP URL 或用户绝对路径直接拼进去。[视频 Controller](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/controllers/v1/video.py)

启用 API 鉴权时，静态成片和下载请求均需相应头。浏览器 video 标签不能直接附加该头，后续适配可由 ContentFlow 后端带头获取文件，再向界面提供本地字节。此项尚未实现或实测。

## 7. 配音、字幕、FFmpeg 与部署依赖

语音服务的 Edge 路径名称为 Azure TTS V1，内部使用 `edge_tts.Communicate`、WordBoundary 和 SubMaker；不是需 Azure Key 的 V2 路径。音色解析移除 `-Female` / `-Male` 展示后缀；Edge 流请求有超时与最多三次尝试，需要互联网。[voice.py](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/services/voice.py)

`subtitle_provider=edge` 依赖 Edge 时间戳；不将它视为离线配音。Edge 失败时不自动接入新付费 TTS，不假定自动 Whisper 回退。

实际 FFmpeg 解析优先考虑已配置的 IMAGEIO_FFMPEG_EXE、系统 PATH 和 imageio-ffmpeg 提供的二进制，再通过 `-version` 探测。配置加载器把有效的 app.ffmpeg_path 映射给媒体库。源码明确提示锁定的 imageio-ffmpeg 0.6.0 不保证运行时自动补下载；应准备可用二进制并通过实际探测。[utils.py](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/app/utils/utils.py)

上游 pyproject 声明 Python >=3.11，包含 MoviePy 2.2.1、edge-tts 7.3.1、FastAPI、Streamlit、imageio-ffmpeg 0.6.0、faster-whisper 1.1.0 等；使用 Edge 不代表安装时没有 Whisper 依赖。uv 的 Pillow override 也应随选定版本验证，不能直接假定 pip/uv 安装结果等价。[依赖清单](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/pyproject.toml)

当前主机只有 Python 3.13.7 的已知检查结果，没有安装整个依赖链。本轮不进行音色列表请求、TTS 请求、模型调用或真实视频生成。

## 8. 检测工具使用

项目根目录执行：

```powershell
python -B scripts/check_mpt_api.py
python -B scripts/check_mpt_api.py --base-url http://127.0.0.1:8080 --timeout 5
python -B -m unittest discover -s tests -v
```

仅使用标准库。服务地址可带反向代理前缀，但不要填写 `/docs` 或 `/api/v1`；工具自行追加 `/openapi.json`。禁止地址携带用户名、密码、查询参数或片段；不读取环境变量、配置凭证或 HTTP 代理配置；不提供鉴权输入选项。不跟随重定向，不关闭 TLS 校验，不打印响应正文、服务器错误细节或用户 URL。直接请求网络，不适用于必须依赖环境代理的网络。

获取描述后，检查脚本、上传、素材列表、视频生成、任务查询、下载及预览的路径和方法是否声明。**接口存在检查不校验所有 Schema 参数，不证明业务接口有权限或运行成功。** 若 OpenAPI 被代理鉴权保护，仅报告受限；本轮不会为了通过检查而读取 token。

| 退出码 | 含义 |
| --- | --- |
| 0 | OpenAPI 3 可解析且必要路径/方法均存在 |
| 2 | CLI 参数或地址/超时配置错误 |
| 3 | 连接被拒绝，可能是服务未启动、端口或防火墙问题 |
| 4 | DNS、TLS、其他网络或 HTTP 传输异常 |
| 5 | 连接/读取超时 |
| 6 | OpenAPI HTTP 错误、鉴权受限、重定向或非 200 |
| 7 | 无效、非支持的描述结构或超过 4 MiB |
| 8 | 缺少必要接口或 HTTP 方法 |
| 9 | 系统/沙箱网络权限阻止访问 |

检查服务是否启动无法单靠客户端错误绝对断定：拒绝连接与超时分开报告，超时不归因为“未启动”。真实运行详见 [环境检查报告](开发环境检查报告.md)。

## 9. 后续必须验证

1. 锁定上游 commit/release，独立环境准备并验证 FFmpeg 和中文字体；不修改全局 Python。
2. 启动本机 API，重新运行只读工具，保存真实 OpenAPI 并比较源码中的素材和状态字段。
3. 在后续获准联调阶段验证文件上传返回标识及素材列表，再测试该标识创建任务；本轮未上传。
4. 另一个明确授权阶段验证 Edge 与固定脚本短视频；本轮禁止生成视频及任何计费调用。
5. 对已授权的 DeepSeek 验证限制请求量、核对实际模型及用量，不因工具检查通过而自动调用模型。

## 10. 第 004 轮固定部署与真实 API 核对

### 10.1 版本和证据边界

本机固定提交为 [`436b0e9cc830ef7639e33388917e389cf30d3307`](https://github.com/harry0703/MoneyPrinterTurbo/commit/436b0e9cc830ef7639e33388917e389cf30d3307)，不是对“当前最新 main”的承诺。原始 [pyproject](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/pyproject.toml) 与真实 OpenAPI 的版本均为 1.3.6。本轮通过 GitHub 连接器获取 API 运行所需 53 个文件，并逐个验证 Git blob SHA；没有上游 Git 工作树，也没有修改源码。[文件清单](evidence/round004_source_manifest.json)

源码未包含上游 WebUI、测试和大型歌曲/字体资源，因此称为 API 运行子集；详细部署限制、安装和重启方式见 [环境报告第 6 节](开发环境检查报告.md#6-第-004-轮git-初始化与独立部署)。真实服务地址仅本机可达：

- [OpenAPI JSON](http://127.0.0.1:8080/openapi.json)：实际 GET 成功，已保存 [快照](evidence/round004_openapi.json)。
- [Swagger 文档](http://127.0.0.1:8080/docs)：实际 HTTP 200；未在浏览器验证其外部 CDN 脚本加载效果。
- [本轮检测输出](evidence/round004_api_check.txt)：7 项必要操作全部通过、退出码 0。
- [实际 HTTP / 操作摘要](evidence/round004_api_summary.json)：包括空列表和不存在任务/文件的错误状态。

### 10.2 真实 OpenAPI 与固定源码对照

| 接口 | 本轮核验结果 | 未验证行为 |
| --- | --- | --- |
| POST /api/v1/scripts | OpenAPI 存在，脚本返回模型含 `data.video_script` | 没有调用模型 |
| POST /api/v1/video_materials | 必需 multipart `file`；响应 `VideoMaterialUploadData.file` 为必需字符串 | 没有上传或执行媒体校验 |
| GET /api/v1/video_materials | 实测 200，`data.files=[]`；列表项模型为 `name,size,file` | 未验证上传后列表 |
| POST /api/v1/videos | JSON `TaskVideoRequest`；Schema required 只有 `video_subject`；响应 `data.task_id` | 未提交任务，未获得 task_id |
| GET /api/v1/tasks/{task_id} | 描述存在；不存在 ID 实测 404 | 未验证活动及成功任务 |
| GET /api/v1/download/{file_path} | 描述存在；不存在文件实测 404 | 未下载真实 MP4 |
| GET /api/v1/stream/{file_path} | 描述存在；源码支持文件流/Range | 未播放真实 MP4 |

另外 GET `/api/v1/tasks` 实测 HTTP 200，`data.tasks=[]`、`total=0`。本轮所有 HTTP 请求均为 GET。

以下核心字段经真实 Schema 与固定 [schema.py](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/app/models/schema.py) 对照：

- `TaskVideoRequest.video_subject` 必需；`video_script` 默认空，后续必须传审核稿，避免隐式模型调用。
- `video_source` 默认 **pexels**，`bgm_type` 默认 **random**，不能依赖默认值规避外部服务。后续请求显式 `video_source="local"`、`bgm_type=""`、`bgm_file=""`。
- `video_materials` 为 `MaterialInfo` 数组；每项显式 `provider="local"`、`url=<上传返回的 data.file>`，不要用 ContentFlow 或用户原始素材路径。
- `video_aspect` 默认 `9:16`，`video_count` 默认 1 且至少为 1；项目仍限制一次一个任务和一个成片。
- `voice_name` 默认空，后续显式设置中文 Edge 音色；`subtitle_enabled` 默认 true。
- `font_name` 默认 `STHeitiMedium.ttc`，当前运行子集没有该文件；后续显式使用已验证的 `C:/Windows/Fonts/msyhbd.ttc`，或在生成前另行准备字体资源。
- `TaskStatusData` 稳定字段：`task_id,state,progress,videos,combined_videos,failed_stage,error`，并允许扩展字段。固定常量依然为 processing=4、complete=1、failed=-1；本轮只核对声明与源码，没有成功任务状态实测。

固定 [上传 Controller](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/app/controllers/v1/video.py) 仍返回 `data.file=stored_filename`；[上传服务](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/app/services/material_upload.py) 使用 UUID 存储名；[视频预处理](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/app/services/video.py) 在 `storage/local_videos` 内解析。**真实上传响应与该标识提交生成的闭环仍待下一轮验证**。

### 10.3 当前配置及免费链依赖

新建上游本地 `config.toml` 未包含任何凭证；只设置本机监听、原生 DeepSeek、显式 `deepseek-flash`、Edge 字幕、禁用 Redis 和单任务并发。固定 Provider 默认仍为 `deepseek-v4-pro`，但本轮已实际调用 Provider 解析函数，确认显式模型值解析结果为 `deepseek-flash`。没有连接 DeepSeek，不证明账户授权、模型可用或余额足够。[部署摘要](evidence/round004_deployment.json)

当前 `app.api_key` 未配置，只绑定 `127.0.0.1`。空素材/任务列表成功属于该本机免鉴权状态的验证，未测试配置 token 后的正确/错误鉴权。固定 [鉴权源码](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/app/controllers/base.py) 与 [ASGI](https://github.com/harry0703/MoneyPrinterTurbo/blob/436b0e9cc830ef7639e33388917e389cf30d3307/app/asgi.py) 仍按 `x-api-key` 保护业务与静态产物；不得将 OpenAPI 通过等同于鉴权通过。

与第 003 轮 main 清单不同，此提交锁定的 Edge TTS 为 **7.2.7**，Pillow 为 **11.3.0**，未使用旧文提及的 main Pillow override。uv 0.13.6 在独立 `.venv`、Python 3.13.7 下按原始锁文件安装 116 个包；`uv pip check` 通过。实际 FFmpeg 为 imageio-ffmpeg 包内 7.1，本机和上游定位函数均验证可执行，无须安装全局 FFmpeg。[运行证据](evidence/round004_runtime.json)

Edge TTS 包已安装，**服务联网、语音、WordBoundary 和字幕效果未测试**。固定任务服务在 Edge 时间戳缺失时可能跳过字幕，不能把这种结果视为课程字幕要求通过，也不应自动改用收费 TTS 或 Whisper 模型下载。系统微软雅黑中文覆盖已用上游函数验证，完整烧录和视觉效果尚待真实样片。

### 10.4 下一轮具体顺序

1. 检查现有 API 实例，先验证 Edge 免费路径和中文字体；失败时记录网络及错误，不切换到新增付费服务。
2. 上传一份有使用权的本地 MP4，保存真实 `data.file`，核对素材列表并在生成 JSON 中引用该服务端标识。
3. 使用固定 5–10 秒中文稿、显式 local、无配乐、中文 Edge 音色和系统字体创建一个任务，轮询真实状态；核查有声、中文字幕、画幅、播放与下载。
4. 样片通过后，再按阶段授权以极小请求量核验已有余额的 Flash；不得回退 Pro、充值或接入其他付费渠道。
5. 最后进入 ContentFlow 最小适配层和界面；本轮未编写业务界面或修改现有检测工具。

## 11. 第 005 轮真实上传、任务和下载验证

固定 1.3.6 下的完整请求与结果见 [第 005 轮验证报告](第005轮端到端验证报告_公开版.md)，该轮只使用固定脚本，没有调用脚本或关键词 LLM 接口。

- POST `/api/v1/video_materials`：本机生成的授权测试 MP4，multipart `file`，HTTP 200，返回 `data.file="ab75156215764effb90a6fd01426bad4.mp4"`；GET 列表确认保存，存储字节哈希一致。
- POST `/api/v1/videos`：提交前按本机 Pydantic 与真实 OpenAPI 验证 38 个显式字段；local 素材引用上述服务端标识，固定非空中文稿、中文 Edge 音色、字幕开启、无配乐、无在线搜索、自动发布关闭。HTTP 200 返回 `data.task_id="243f9893-0914-4b26-8057-dcff096c97d2"`。只提交一次。
- GET `/api/v1/tasks/{task_id}`：实际观察 processing=4 及 complete=1，最终 progress=100，失败字段为空；`data.videos` 返回 `/tasks/<task_id>/final-1.mp4` 相对 URI，本轮没有假定一定是绝对 URL。
- GET `/api/v1/download/<task_id>/final-1.mp4`：HTTP 200、video/mp4，下载 2,489,359 字节；与服务端文件 SHA-256 一致。
- GET `/api/v1/stream/<task_id>/final-1.mp4` 携带 `Range: bytes=0-1023`：HTTP 206，Content-Range 和文件前缀一致。尚未完成浏览器/播放器实时播放验收。

本轮实测上传标识 → 创建任务 → 成片映射已经闭环；不能使用客户端原始素材路径替代 `data.file`。[请求 JSON](evidence/round005_video_request.json)、[上传响应](evidence/round005_upload_result.json)、[任务及下载](evidence/round005_submission.json)、[状态历史](evidence/round005_task_history.json)、[成片检查](evidence/round005_output_validation.json)

原锁定 edge-tts 7.2.7 当前免费联网路径返回 WebSocket 403；其同步迭代异常被表现为上游 30 秒超时。用户明确批准后，仅将独立 `.venv` 的该包升级 7.3.1，再重启 API，原生配音和字幕成功。不能把这次结果说成原始锁文件的 7.2.7 已通过。MoneyPrinterTurbo 源码/commit、uv.lock 均保持原样，版本例外及精确回退命令已记录：[依赖覆盖](evidence/round005_dependency_override.json)。

实际成片为 7.20 秒、1080×1920、30 fps、H.264/AAC，中文字幕已在解码帧中目视确认。Edge 字幕实际为 3 段，最后一段结束于约 6.588 秒；音轨 7.18 秒。没有使用自定义音频注入或 Whisper。用户按 Esc 停止 Computer Use 后，主观试听和完整实际播放保持未完成；解码成功和自动识别不替代这项验收。

## 12. 第 006 轮：在线素材与内容生成适配

再次核对实际部署 config.toml（仅密钥存在性）、schema.py、task.py、material.py、video.py 和实时 OpenAPI；固定 1.3.6、53 个源码 blob 未变，没有使用 main 参数替换。在线请求通过当前实际 Pydantic 校验：[参数契约](evidence/round006_payload_contract.json)，该文件用于校验，没有提交生成任务。

生产请求：video_subject 为审核标题，非空 video_script，4 个有序英文 video_terms，video_source=pexels（或主动选 pixabay），9:16、match_materials_to_script=true、video_concat_mode=sequential、字幕开启。沿用第五轮中文 Edge 音色、系统微软雅黑和无配乐配置。没有提交客户端素材路径，不在在线源失败时改 local。

task.py 的 generate_script 仅空脚本时请求 LLM；generate_terms 仅空关键词时请求 LLM。match=true 会跳过可选 TwelveLabs 关键词语义排序。故 ContentFlow 已生成并审核的两个字段完整传入，不再调用上游 scripts/terms 接口。ContentFlow 使用现有 DeepSeek 官方渠道单次结构化生成，显式 Flash、thinking disabled、max_tokens=1200、json_object；无自动重试/Pro 回退。[官方请求参数](https://api-docs.deepseek.com/api/create-chat-completion/)

1.3.6 素材下载按关键词分组轮询，原生竖屏 Pexels 筛选精确 1080×1920 rendition 及最小时长，不等同于精确逐句剪辑；有网站搜索结果也可能无可用视频。无结果、权限错误形状和网络异常可能均转为空列表。应用只给出素材阶段及可能原因，不能臆断具体错误；可结合上游脱敏日志和独立 probe 排查。

scripts/check_online_materials.py 在 MPT 环境真实调用其 download_videos；缺 Key 时发请求前停止，Pexels/备用均实际阻塞。[Pexels 证据](evidence/round006_material_probe.json)、[Pixabay 证据](evidence/round006_pixabay_probe.json)。scripts/test_mpt_material_contract.py 直接调用固定原始搜索函数但 mock HTTP，4 项通过，明确不是网络验证。

Config API 不存在于当前适配范围；网页本机密码表单只更新上游 TOML 指定 Key 字段，不改源码，素材 Key 保存后需要重启后端。ContentFlow 指定环境 DeepSeek Key 可以直接用于官方请求，MPT 不假定加载 .env。不要把模型 Key 和 x-api-key 混用。

MPT 状态、下载接口复用原行为；新适配器校验版本、路径、大小和 MP4 解码，并以 SQLite 管理审核与单次提交。读取 task script.json 中 material_sources 时只展示白名单供应商公开页面/作者/关键词，去掉查询与凭证，不传播签名下载 URL。Pexels/Pixabay 原始素材页用于来源追踪和相关性检查。

当前真实在线生成仍未验证，两个主题均待本机 Key 和人工确认。第五轮旧产物下载适配回归单独记录，不作为本轮生成证据：[只读回归](evidence/round006_download_regression.json)。用户已在第 006 轮反馈第五轮样片人工验收；历史工具边界仍保留。

## 13. 第 006 轮续：Pixabay 专项（2026-11-01）

### 配置和当前阻塞

准确文件：D:\Projects\MoneyPrinterTurbo\config.toml；字段是 [app].pixabay_api_keys，可为字符串或字符串数组，建议由本机网页密码框保存为数组。模型复用同一文件 [app].deepseek_api_key，显式 deepseek-flash；不新建凭证副本、不读取或回显值。素材配置变更后需重启 MPT，确认没有活动任务再操作。最新检查两类 Key 均缺失，不能将“用户已取得”写成“服务已接入”。

### 固定 1.3.6 真实实现

- material.search_videos_pixabay 调用 HTTPS Pixabay /api/videos/，参数 q、video_type=all、per_page=50、key；timeout=(30,60)，TLS 校验及代理使用实际配置。
- 返回 hits，每项含 duration、videos 各 rendition。筛选 duration≥minimum_duration、竖屏方向匹配且 width≥1080；不要求精确 1080×1920。横屏结果不能当作可用竖屏素材。
- 上游分别处理网络验证拦截、429、其他 HTTP≥400、非 JSON 和缺少 hits 等问题，最终部分失败仍为 []。不能仅据 [] 判断“关键词无结果”。
- _search_videos_with_cache 按 provider/term/最小时长/画幅缓存 24 小时并校验方向。新探测器和视频任务使用相同入口及 5 秒最小片长，提交前检索能供任务复用，避免重复请求。
- save_video 以剥离查询后的 URL 哈希命名缓存 MP4，复用已有文件，并用 VideoFileClip 检查时长/fps。单素材验证额外读取首帧及记录格式/尺寸/大小/哈希，不记录下载 URL 查询串。

scripts/probe_pixabay.py 在原 MPT Python 中调用这些函数，仅观察原 requests.get 的响应状态/计数；原请求不变，磁盘源码不变。不会记录请求 URL、header、body 或原始异常，只保留安全类别。可区分缺 Key、Key 无效、请求拒绝、网络失败/验证拦截、429、非 JSON、返回结构异常、原始无结果与竖屏筛空；不自动换源。

首次实际执行入口为 waterfall / download-one，结果 [missing_key](evidence/round006_pixabay_initial_validation.json)，真实 HTTP 次数 0，未下载。不能把此记录视为真实搜索/许可素材下载成功。配置后仍需成功搜索、单条下载/解码与人工审核脚本后的完整 API 任务。

### 应用请求与界面

29 个生产请求字段经实时 OpenAPI 及实际 TaskVideoRequest.model_validate 通过：[Pixabay 参数契约](evidence/round006_pixabay_contract.json)。source=pixabay、已审核非空脚本与四词、match=true、sequential、9:16、中文 Edge、字幕开启、系统字体、无配乐；不会重复请求上游生成关键词。源码53项再次通过，版本/锁文件未变。

网页只提供 Pixabay，历史其他来源草稿须重新审核；侧栏可独立查询一个英文测试词，草稿页显示每词/去重候选数。提交自动检查素材，无可用结果或网络/权限错误不创建任务。候选数量不等于实际使用数量；未查询明确显示“尚未查询”。成功/有效空结果缓存24小时，失败冷却30秒；没有自动重试批量下载。

现有脚本/关键词、SQLite、防重、状态、下载与播放器继续使用；本轮至少一次真实闭环是必须项，第二主题为建议。当前已过43项应用自动化和11项固定上游模拟测试，均不能代替真实 API 验收。

## 14. 首条 Pixabay 实际任务（2026-11-01）

用户本机保存凭证后完成真实搜索/单段下载，并明确回复“确认这份稿件和关键词，生成视频”。调用 ContentFlow 工作流确认当前审核指纹，再执行唯一一次 POST /api/v1/videos；实际29字段请求见 [请求快照](evidence/round006_real_video_request.json)，未经授权未改稿/换词或重提任务。

核心值为 video_source=pixabay、video_aspect=9:16、match_materials_to_script=true、video_concat_mode=sequential；video_script和四个video_terms与审核内容完全一致。沿用 Xiaoxiao Edge中文配音、速度1.0、edge字幕、系统中文字体、无背景音乐。MPT task script.json参数核对通过，日志只计数未回显，未发现“llm provider:”调用记录；本轮Flash实际请求1次、309 tokens，不再请求上游生成关键词。

上游 task_id=045395ae-0ddd-48a1-8aaa-95db07c3970c；ContentFlow job_id=98c1b665-7571-4f16-9bf7-072fd9eb3519。实际状态进度5→20→40→50→75→100，最终成功并自动下载，历史及状态见 [真实任务](evidence/round006_real_video.json)。GET下载与上游文件SHA-256相同；GET /api/v1/stream/045395ae-0ddd-48a1-8aaa-95db07c3970c/final-1.mp4 的Range请求返回206，前1024字节一致。

成片18.67秒、1080×1920、H.264/AAC，中文烧录字幕可见且音轨非静音。实际4个素材来源保存在生产任务及 [联调报告](第006轮Pixabay真实联调报告_公开版.md)，公开素材页不含Key/签名参数。顺序匹配只控制选材/拼接策略，不能保证逐句精准画面；末段夕阳步道匹配有偏差。浏览器实际播放、主观试听、第二主题仍未验收，不将真实数据AppTest渲染等同于这些项。
