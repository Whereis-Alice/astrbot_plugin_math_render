# Changelog

## [v0.4.7] - 2026-07-05

### Fixed

- 修复 `free` 布局同时插入几何图或函数图时，LLM 容易在 `markdown_content` 末尾留下“几何示意图：”“如下图所示：”等空占位，导致图卡看起来像正文没写完的问题。现在渲染前会清理尾部空占位，并强化默认提示，要求正文包含完整证明或解题步骤。

## [v0.4.6] - 2026-07-05

### Fixed

- 修复 `v0.4.5` 中 LLM 工具成功直发图片后返回 `None`，导致 Agent Loop 直接结束、bot 不再追加自然收尾回复的问题。现在直发图片成功后会返回简短工具结果，让模型继续给一句简短确认。

## [v0.4.5] - 2026-07-05

### Fixed

- 修复 LLM 工具场景下图片结果被 tool loop 当作工具返回消费、但没有稳定发送到聊天窗口的问题：工具出图成功后会优先通过 `Context.send_message` 直接发送图片，失败时再尝试 `event.send`。
- 如果两条直接发送链路都失败，工具返回会明确带上生成图片路径和 `send_message_to_user` 调用提示，同时日志记录具体失败原因，方便继续排查。

## [v0.4.4] - 2026-07-05

### Changed

- 重组 `_conf_schema.json`：配置项按基础开关、LLM 提示、预回复、渲染引擎、图片发送、图卡样式、几何图、几何样式、函数绘图拆成模块；旧版扁平 key 作为隐藏兼容项保留，避免升级后丢失旧配置。
- 将函数绘图相关配置项的英文标题、说明和默认提示翻译为中文，并把图片发送压缩参数标注为高级项。
- 重写 README，按使用方式、几何图、内嵌绘图、配置模块和排障流程重新组织内容。

## [v0.4.3] - 2026-07-05

### Fixed

- 修复部分 aiocqhttp/OneBot 环境下 base64 图片组件不落地发送的问题：插件发送渲染结果时默认改回 AstrBot 本地文件图片组件（`file_image` / `Image.fromFileSystem` 同一路径），保留发送前压缩检查；如确需 base64，可将 `send_image_transport` 配置为 `base64`。

## [v0.4.2] - 2026-07-05

### Fixed

- 修复 LLM 把 `geometry_scene_json.points` 写成对象映射（如 `{"A": [-5, 0]}`）时几何图被跳过的问题；现在会自动归一化为点数组，并兼容 `angle_marks[].size` 与 `annotations[].position` 等常见写法。

## [v0.4.1] - 2026-07-05

### Fixed

- 修复部分 OneBot/QQ 环境下解题图卡渲染成功但图片消息不可见的问题：发送前会检查图片大小和分辨率，必要时压缩，并统一使用 base64 图片组件发送；同时补充发送前图片大小、分辨率和压缩结果的调试日志。

## [v0.4.0] - 2026-07-05

### Added

- 新增解题图卡内嵌绘图链路：`render_math_solution_card` 支持 `plot_spec_json`、`plot_caption`、`plot_position`，`/mathsolveimg` 也会在题目需要函数图像或曲线时尝试生成 `plot_spec` 并把绘图融合进同一张解题卡；绘图失败会写入异常日志并继续输出解题卡。

- 集成函数绘图能力，新增本地 Matplotlib 绘图服务，支持一元函数、多函数对比、隐式方程、极坐标、二维参数曲线、三维曲面、三维参数曲线和二维向量场。
- 新增手动命令：`/plot`、`/plot3d`、`/polar`、`/parametric`、`/vector2d`、`/parametric3d`、`/plotstatus`。
- 新增 LLM 绘图工具：`plot_function`、`plot_multiple`、`plot_implicit`、`plot_polar`、`plot_parametric`、`plot_3d_function`、`plot_3d_parametric`、`plot_vector_field_2d`。
- 新增绘图相关配置项，可调整 DPI、默认范围、采样密度、线宽、网格透明度、3D 视角、配色和字体。

### Changed

- 绘图输出统一使用 Math Render 的临时目录和缓存策略，避免额外维护独立 `plots` 目录。

## [v0.3.10] - 2026-05-18

### Fixed

- 修复几何标注里 `annotations[].at` 写成字符串坐标（如 `"(25, 35)"`、`"(-15, -8)"`）时，被误当作点名引用、导致整条标注跳过的问题。
- 这类字符串坐标现在会自动识别为内联坐标；像 `C`、`O` 这种点名重定位标注也会重新合并回点标签偏移，不再丢字。

## [v0.3.9] - 2026-05-18

### Changed

- 优化几何点标注的落位与层级，`C`、`O` 这类点名会离拥挤的底边文字更远一些，描边也更轻，减少遮挡感。
- 新增 `render_wait_until` 配置项；本地浏览器截图现在会在 `networkidle` 超时时自动回退到 `load` / `domcontentloaded`，预览和长内容渲染更稳。

### Fixed

- 去掉几何标注原先那层半透明白色圆角背景，改成更自然的描边文字。
- 修复本地浏览器在 `page.set_content(...)` 阶段没有正确吃到 `render_timeout_ms`、容易卡在 Playwright 默认 30 秒超时的问题。

本文件记录 `astrbot_plugin_math_render` 的重要更新。

版本号与 `metadata.yaml` 保持一致，后续发版可继续在顶部追加。

## [v0.3.8] - 2026-05-18

### Changed

- 几何 scene 提示进一步明确：有限边如 `AD`、`BD`、`OD` 应放进 `segments`，无限直线才使用 `lines.through`；半圆则应显式使用 `semicircle_*` 或 `semicircle + orientation`。

### Fixed

- 修复部分 LLM 把有限线段错误塞进 `lines` 集合时，被当成无效直线并在日志里报 `line through must contain exactly two point names` 的问题。
- 这类误放进 `lines` 的 `from/to` 图元现在会自动转入 `segments`，避免 `AD`、`BD`、`OD` 一类关键边直接丢失。

## [v0.3.7] - 2026-05-18

### Changed

- 几何场景兼容层进一步放宽，新增对 `angle_marks.start/end`、`circles[].semicircleDirection`、`labelPosition`、`showLabel`、`showPoint`、`labelPos` 等常见 LLM 变体字段的识别。
- 自动渲染提示与手动求解提示都补充了 canonical schema reminder，继续鼓励 LLM 优先使用稳定字段名：`name`、`from`/`to`、`orientation`、`offset`。

### Fixed

- 修复 `angle_marks` 使用 `start/end` 时触发 `angle from point reference is empty`，导致几何图整块跳过的问题。
- 修复部分半圆场景使用 `semicircleDirection` 时方向信息未正确归一化的问题。
- 修复点标签和线段标签采用 `labelPosition` 时无法正确落位的兼容性问题。
- 渲染阶段现在会尽量跳过坏掉的单个图元并继续出图，避免某个角标、圆或注释字段异常时把整张几何图一起带崩。

## [v0.3.6] - 2026-05-18

### Added

- 新增半圆几何关系重建：当 scene 明显表达“AB 为直径、D 在半圆上、C 为垂足”但坐标画得不准时，会自动按几何关系把关键点投回合理位置。

### Changed

- 半圆关系修正现在会优先根据直径端点与圆心关系重建半径，而不是盲信上游传来的不一致 `radius` 数值。
- 对仅用于半径辅助线的无标签辅助点，会在关系重建后自动隐藏，减少图中多余的辅助点圆点。

### Fixed

- 修复某些“语义正确但坐标不严格”的几何 scene 虽然能出图、但半圆与顶点位置明显不对应的问题。
- 修复这类场景下 `D` 点、顶端辅助点与半圆弧线脱节，导致图形视觉上不可信的问题。

## [v0.3.5] - 2026-05-18

### Changed

- 几何点位兼容层新增对 `highlight: true` 的识别，可自动映射为高亮点样式。
- 显式写成 `label: ""` 的点现在会默认隐藏标签，不再回退成点名文本。
- 对带有 `orientation: up/down/top/bottom` 的半圆场景，新增轻量屏幕坐标兼容：当 LLM 按“屏幕 Y 轴向下”习惯给点位时，会自动翻转到渲染器坐标系。

### Fixed

- 修复 `circles[].center` 直接写成坐标对象时，渲染阶段报 `circle center references unknown point` 导致几何图失败的问题。
- 修复 `semicircle: true` 配合 `orientation: up/down` 一类写法时，半圆方向无法正确识别的问题。

## [v0.3.4] - 2026-05-18

### Changed

- 几何场景兼容层新增对“数组式紧凑 scene JSON”的支持，可直接解析 `["A", 0, 0]`、`["A", "B"]`、`["O", 5]`、`["a", 2, -0.5]` 这类短写法。
- 对紧凑圆写法增加轻量半圆推断：当几何关系明显是在画直径对应的半圆时，会优先推断为上/下/左/右半圆，而不是默认整圆。
- 坐标式几何标注如果本质上是在给已有点位重新摆放标签，会自动合并为点标签覆写，减少数组式 scene 里的重复字母。

### Fixed

- 修复数组式 `points/segments/circles/annotations` 在渲染阶段触发 `each point must be an object` 导致几何图完全失败的问题。
- 修复部分旧 prompt 或自由输出使用紧凑数组格式时，几何图被直接跳过的兼容性问题。
- 修复几何标注里的 `√ab`、`≥`、`≤` 等常见 Unicode 数学符号在部分环境下显示不稳定的问题。

## [v0.3.3] - 2026-05-18

### Changed

- 几何圆弧兼容层新增对 `circles[].style = "semicircle"` 这一常见 LLM 输出写法的识别，默认按上半圆渲染。
- `annotations` 新增兼容 `label + point` 结构，支持点名定位和 `[x, y]` 坐标定位两种写法。
- 当 `annotations` 用于给已有点位重新摆放标签时，会自动合并为点标签覆写，避免同一字母重复显示两次。

### Fixed

- 修复几何题中“应为半圆却显示成整圆”的问题。
- 修复部分几何场景里文字标注使用 `label` 字段时无法显示的问题。

## [v0.3.2] - 2026-05-18

### Added

- 新增 `geometry_font_family` 配置项，用于为几何图文字指定字体回退链，方便兼容 Windows 和 Linux 环境。

### Changed

- 几何场景解析新增对更宽松 JSON 结构的兼容，支持 `point.id`、`angle_marks.arms`、`angle_marks.mark`、`style: dashed/thick` 以及 `semicircle_upper` 一类半圆类型。
- 线段标注支持 `label_pos`，可让边长或公式标签按比例落在更合适的位置。
- 半圆改为按真实弧线渲染，并参与正确的边界计算，避免把半圆当整圆处理。

### Fixed

- 修复 LLM 输出新几何 JSON 变体时，`render_math_solution_card` 触发 `name is required` 导致几何图渲染失败的问题。
- 优化字体回退逻辑，仅在当前系统已安装字体中选择候选项，减少 Matplotlib 的 `findfont` 警告。

## [v0.3.1] - 2026-05-18

### Added

- 新增对旧式 `GeometryScene/setup/measurements/rightAngle/labels` 几何 DSL 的兼容，可自动翻译为当前 scene 渲染结构。
- 几何提示词加入 scene schema reminder，帮助 LLM 更稳定地输出插件可识别的场景 JSON。

### Changed

- 旧几何 DSL 中的点、线、半圆、垂线、交点、测量标注、直角标记、结论文字等元素会在内部统一转换为当前渲染链路。

### Fixed

- 提升历史 prompt、旧示例和旧格式几何题的兼容性，减少“结构能看懂但无法绘图”的情况。

## [v0.3.0] - 2026-05-18

### Added

- 新增空几何场景自动跳过逻辑，避免在无可绘制内容时塞出一张大白图。
- 新增几何图位置控制，允许按 `geometry_position` 把几何图放到内容前后、公式后、答案后或整卡片末尾。
- 新增 viewport 失效兜底策略，疑似被裁空时会去掉 viewport 自动重试一次。

### Changed

- 几何图嵌入解答卡片的布局能力增强，LLM 或手动工具调用都可以更灵活地安排图文顺序。

### Fixed

- 修复部分几何图因错误 viewport 或空场景而出现“渲染成功但实际空白”的问题。

## [v0.2.0] - 2026-05-18

### Added

- 插件首次导入仓库，提供 LaTeX 公式渲染、数学解答出图、Markdown 数学卡片与基础几何示意图能力。
- 支持手动命令触发公式渲染、解答出图、文本转公式渲染和 LLM 工具调用渲染。
- 提供临时文件目录管理、自动清理、调试日志输出和多项渲染样式配置能力。
