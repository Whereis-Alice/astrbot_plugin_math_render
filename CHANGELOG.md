# Changelog

本文件记录 `astrbot_plugin_math_render` 的重要更新。

版本号与 `metadata.yaml` 保持一致，后续发版可继续在顶部追加。

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
