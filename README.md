# AstrBot Math Render

一个面向 AstrBot 的数学渲染插件，目标是把“能算”升级成“能清晰交付”。

它不仅能渲染 LaTeX 公式，还能在数学题、证明题、识图题里输出高质量解答图卡；对于几何题，还支持通过场景 JSON 自动绘制三角形、圆、辅助线、角标和点位关系图。

## 适合什么场景

- 聊天平台本身不支持 LaTeX，需要把 `1/2`、`sqrt(x)` 这类表达式转成清晰图片
- 数学题、证明题、推导题希望直接生成“可转发、可截图、可保存”的解答图
- 用户发来题目截图，希望模型在识图后直接出图，而不是只给一段文本
- 几何题需要辅助图，想让 LLM 在解答时自动决定是否顺便画图
- 需要自己调 prompt、调风格、调字号、调 DPI、调几何图配色

## 核心功能

- 强化 LaTeX 数学公式渲染，输出高质量 PNG
- `/lateximg` 同时支持原生 LaTeX 和普通表达式自动转 LaTeX
- `/mathsolveimg` 支持“命令 + 数学题”强制触发解答出图
- LLM 可在普通对话中主动调用工具，把数学答案整理成图片
- 识图场景下可提醒 LLM：如果图里是数学题/几何题，可以直接调用本插件
- 支持 Markdown + MathJax 混排
- 自动修复常见渲染问题：
  - 文本里裸写 `\frac`、`\sqrt`、`\geq` 不显示
  - LLM 把换行写成字面量 `\n`
- 几何题支持 `SymPy.geometry + Matplotlib + 场景 JSON`
- 临时文件统一放在插件专属目录，并支持自动清理
- 支持输出 AstrBot 调试级别日志，方便排错

## 命令

### 1. 公式渲染

```text
/lateximg <LaTeX 公式或普通数学表达式>
```

别名：

- `/latex2img`
- `/exprimg`
- `/expr2img`
- `/公式渲染`
- `/latex渲染`
- `/表达式渲染`
- `/公式转图`

示例：

```text
/lateximg \int_0^1 x^2\,dx = \frac{1}{3}
/lateximg 1/2
/lateximg sqrt(x^2+1)
```

### 2. 解答出图

```text
/mathsolveimg <数学题>
```

别名：

- `/解答渲染`
- `/数学出图`
- `/题目出图`

示例：

```text
/mathsolveimg 求解二次方程 x^2 - 5x + 6 = 0
/mathsolveimg 证明二阶柯西不等式
/mathsolveimg 用几何方法证明基本不等式
```

### 3. 清理临时文件

```text
/mathimgcleanup
```

别名：

- `/渲染清理`
- `/公式清理`

## LLM 主动调用逻辑

插件会通过 `on_llm_request` 给当前会话注入提示，让模型知道自己有这些工具：

- `render_latex_formula`
- `render_math_solution_card`

当模型判断用户在问数学题、要求步骤推导、需要更适合截图/转发的答案时，就可以主动调用出图工具。

识图时还可以额外提醒模型：

- 如果图片里是数学题，优先出数学图卡
- 如果图片里是几何题，必要时附带几何示意图
- 不要默认因为有 Python 就只走“代码式回复”

这些提示现在都做成了配置项，可以自己调 prompt。

## 几何图功能

插件新增了几何场景 JSON 渲染能力，适用于：

- 三角形
- 圆、半圆、弧
- 辅助线
- 角标
- 点位关系图
- 简单解析几何示意图

几何图渲染链路：

1. LLM 在解题时判断“这题是否需要图”
2. 若需要，则在结构化结果里给出 `geometry_scene`
3. 插件用 `SymPy.geometry` 处理几何对象/派生点
4. 用 `Matplotlib` 生成 PNG
5. 最终把几何图嵌进同一张解答卡片

### 支持的几何场景元素

- `points`
- `segments`
- `lines`
- `rays`
- `circles`
- `polygons`
- `angle_marks`
- `annotations`

支持的常用派生点：

- `midpoint`
- `perpendicular_foot`
- `line_intersection`
- `circle_line_intersection`
- `circle_circle_intersection`

### 场景 JSON 示例

```json
{
  "caption": "按题意绘制的几何关系图",
  "points": [
    { "name": "A", "x": 0, "y": 0 },
    { "name": "B", "x": 6, "y": 0 },
    { "name": "C", "x": 2, "y": 3 },
    { "name": "M", "type": "midpoint", "points": ["A", "B"] }
  ],
  "segments": [
    { "from": "A", "to": "B", "style": "primary" },
    { "from": "B", "to": "C", "style": "primary" },
    { "from": "C", "to": "A", "style": "primary" },
    { "from": "C", "to": "M", "style": "auxiliary" }
  ],
  "angle_marks": [
    { "vertex": "A", "from": "B", "to": "C", "label": "α", "style": "highlight" }
  ],
  "annotations": [
    { "text": "CM is median", "at": "M", "offset": [0.1, 0.2] }
  ]
}
```

说明：

- 坐标可以是示意图坐标，不要求严格按比例
- 重点是关系正确、图形清晰
- 如果题目不需要图，LLM 不必强行生成 `geometry_scene`

## Markdown 渲染

插件现在支持把 Markdown 内容直接渲染进图卡，并和 MathJax 混排。

适合：

- 长证明题
- 讲义式排版
- 图文混合讲解
- 标题 / 列表 / 引用 / 表格 / 强调

当你希望 LLM 自由排版，而不是锁死在“题目 / 关键公式 / 解答 / 最终答案”四段式结构时，可以让它把主要内容写进 `markdown_content`，并把 `layout_mode` 设为 `free`。

## 自然预回复

为了避免触发出图后“只看到冷冰冰发图”，插件支持在真正出图前先发送一条自然回复。

支持两种触发场景：

- 手动命令触发前
- LLM 主动调用工具前

默认会尽量走当前 AstrBot 会话的人设；如果失败，再回退到静态文案。

这部分 prompt 也已经全部可配置。

## 临时文件与目录

默认优先保存到：

```text
AstrBot/data/plugins/astrbot_plugin_math_render/temp
```

如果当前环境无法解析 AstrBot 数据目录，则回退到插件目录下的：

```text
.tmp/
```

你可以通过配置控制：

- 保留时长
- 启动时清理
- 每次渲染前清理

## 重要配置项

### 基础开关

- `auto_render_enabled`
- `auto_render_prompt_enabled`
- `image_math_tool_prompt_enabled`
- `debug_logging_enabled`

### 自然预回复

- `send_pre_reply_before_manual_render`
- `send_pre_reply_before_tool_render`
- `pre_reply_use_llm`
- `pre_reply_system_prompt`
- `pre_reply_user_prompt`
- `pre_reply_fallback_text_formula`
- `pre_reply_fallback_text_solution`

### 自由布局 / Markdown

- `llm_render_layout_prompt_enabled`
- `llm_render_layout_prompt`
- `llm_render_layout_mode`
- `formula_tool_supports_markdown_content`
- `normalize_escaped_newlines_enabled`
- `auto_wrap_bare_latex_enabled`

### 几何图

- `geometry_render_enabled`
- `geometry_tool_prompt_enabled`
- `geometry_tool_awareness_prompt`
- `image_geometry_auto_render_prompt_enabled`
- `image_geometry_auto_render_prompt`
- `geometry_solver_prompt_enabled`
- `geometry_solver_prompt`
- `geometry_section_enabled`
- `geometry_section_position`
- `geometry_section_label`
- `geometry_caption_enabled`
- `geometry_section_default_caption`
- `geometry_keywords`

### 几何图样式

- `geometry_figure_width_in`
- `geometry_figure_height_in`
- `geometry_dpi`
- `geometry_padding_ratio`
- `geometry_line_width`
- `geometry_point_size`
- `geometry_label_font_size`
- `geometry_annotation_font_size`
- `geometry_background_color`
- `geometry_transparent_background`
- `geometry_primary_color`
- `geometry_auxiliary_color`
- `geometry_highlight_color`
- `geometry_subtle_color`
- `geometry_fill_color`
- `geometry_fill_alpha`
- `geometry_point_color`
- `geometry_text_color`
- `geometry_circle_color`
- `geometry_angle_color`

### 图卡样式

- `default_style`
- `default_accent_color`
- `render_dpi_scale`
- `title_font_size_px`
- `subtitle_font_size_px`
- `body_font_size_px`
- `body_line_height`
- `formula_font_scale`
- `render_text_color`
- `render_muted_text_color`
- `render_page_background_css`
- `render_card_background_css`
- `content_max_width_px`

## 依赖

```text
playwright>=1.50.0
sympy>=1.13
markdown>=3.6
matplotlib>=3.8
```

说明：

- `playwright`：本地浏览器截图渲染
- `sympy`：表达式转 LaTeX、几何对象辅助计算
- `markdown`：Markdown 转 HTML
- `matplotlib`：几何图绘制

## 兼容性

- AstrBot `>=4.16,<5`
- 已针对 Linux 路径与 root 场景浏览器截图做兼容

## 打包上传

仓库根目录提供了打包脚本：

```text
build_math_render_upload_zip.py
```

运行后会生成：

```text
astrbot_plugin_math_render_upload_时间戳.zip
```

这个 zip 会直接以插件文件作为根，不会多套一层目录，适合 AstrBot WebUI 上传安装。

## 调试建议

如果你遇到下面这些问题，优先打开 `debug_logging_enabled`：

- 没触发工具
- 触发了但没出图
- 识图数学题没走本插件
- 几何题没有附带几何图
- 明明有 LaTeX 却没有正确渲染

日志里可以看到：

- 是否注入了自动渲染提示
- 识图时是否注入了几何提示
- 公式转 LaTeX 走的是本地还是 LLM
- 使用的是本地浏览器还是远端 `html_render`
- 几何场景是否成功解析 / 成功出图
