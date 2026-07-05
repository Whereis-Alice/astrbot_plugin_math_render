# AstrBot Math Render

面向 AstrBot 的数学出图插件。它把公式、解题过程、几何辅助图和函数图像整理成清晰的图片卡片，适合 QQ/OneBot 这类不方便直接展示 LaTeX 的聊天场景。

## 能做什么

- 渲染单个 LaTeX 公式或普通数学表达式。
- 把数学题解答整理成可转发、可保存的图片卡片。
- 几何题自动生成示意图，并嵌入同一张解题图卡。
- 函数、曲线、隐式方程、极坐标、参数曲线、三维曲面和向量场绘图；三维参数曲线会按参数 `t` 渐变上色。
- 识图数学题时提醒 LLM 优先调用出图工具。
- 出图失败时保留文字答案，并在日志里记录原因，方便排查。

## 常用命令

### 公式转图

```text
/lateximg <LaTeX 公式或普通表达式>
```

示例：

```text
/lateximg \int_0^1 x^2\,dx = \frac{1}{3}
/lateximg sqrt(x^2+1)
```

别名：

- `/latex2img`
- `/exprimg`
- `/expr2img`
- `/公式渲染`
- `/latex渲染`
- `/表达式渲染`
- `/公式转图`

### 解题图卡

```text
/mathsolveimg <数学题>
```

示例：

```text
/mathsolveimg 求解方程 x^2 - 5x + 6 = 0
/mathsolveimg 用几何方法证明基本不等式
```

别名：

- `/解答渲染`
- `/数学出图`
- `/题目出图`

### 函数绘图

常用变量写法：二维函数使用 `x` / `y`，极坐标使用 `theta`，参数曲线使用 `t`，球坐标曲面使用 `theta` 和 `phi`，三维隐式曲面使用 `x`、`y`、`z`。表达式支持 `sin`、`cos`、`tan`、`sqrt`、`exp`、`log`、`abs`、`pi` 等常见函数和常量。

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/plot <表达式>` | 一元函数、多函数对比、二维隐式曲线 | `/plot sin(x), cos(x)` |
| `/plot3d <z=f(x,y)>` | 单个三维曲面 | `/plot3d sin(sqrt(x^2+y^2))` |
| `/plot3dm <表达式1>, <表达式2>` | 多个三维曲面叠加对比 | `/plot3dm x^2+y^2, sqrt(x^2+y^2)` |
| `/implicit3d <F(x,y,z)=0>` | 三维隐式曲面切片图 | `/implicit3d x^2+y^2+z^2=1` |
| `/spherical <r=f(theta,phi)>` | 球坐标曲面 | `/spherical 1+0.3*sin(4*theta)*cos(3*phi)` |
| `/polar <r=f(theta)>` | 极坐标曲线 | `/polar sin(3*theta)` |
| `/parametric <x(t)>, <y(t)>` | 二维参数曲线 | `/parametric cos(t), sin(t)` |
| `/parametric3d <x(t)>, <y(t)>, <z(t)>` | 三维参数曲线，按 `t` 渐变上色 | `/parametric3d sin(2*t), cos(3*t), t/4` |
| `/vector2d <Fx(x,y)>, <Fy(x,y)>` | 二维向量场 | `/vector2d -y, x` |
| `/vector3d <向量定义>` | 三维空间向量 | `/vector3d 1,2,3:red:v1 ; 0,0,0->3,4,1:blue:v2` |
| `/plotstatus` | 查看绘图缓存和默认设置 | `/plotstatus` |

三维向量定义格式：

```text
x,y,z:颜色:标签
x1,y1,z1->x2,y2,z2:颜色:标签
```

颜色可以写 `red`、`blue`、`green`、`orange`、`purple`，也可以写 `#RRGGBB`。

### 清理临时文件

```text
/mathimgcleanup
```

## LLM 主动调用

插件会向当前会话注入能力提示，让模型知道可以使用这些工具：

- `render_latex_formula`
- `render_math_solution_card`
- `plot_function`
- `plot_multiple`
- `plot_implicit`
- `plot_polar`
- `plot_parametric`
- `plot_3d_function`
- `plot_3d_multiple`
- `plot_3d_spherical`
- `plot_implicit_3d`
- `plot_3d_parametric`
- `plot_vector_field_2d`
- `plot_vector_3d`

推荐效果是：用户正常问数学题时，bot 直接调用 `render_math_solution_card`，把文字解答、公式、几何图或函数图像合并成一张图卡，而不是先发一堆散图。

工具选择规则：

- `plot_3d_function`：只画一个 `z=f(x,y)` 曲面。
- `plot_3d_multiple`：比较多个 `z=f(x,y)` 曲面。
- `plot_3d_spherical`：画 `r=f(theta,phi)` 这类球坐标曲面。
- `plot_implicit_3d`：画 `F(x,y,z)=0` 这类三维隐式曲面，例如球面、双曲面。
- `plot_3d_parametric`：画 `x=...`、`y=...`、`z=...` 三个关于 `t` 的参数方程。
- `plot_vector_3d`：画有限个空间向量，不是向量场。

## 几何图能力

几何图通过 `geometry_scene_json` 描述，插件会自动绘制点、线段、圆、辅助线、角标和注释。

支持元素：

- `points`
- `segments`
- `lines`
- `rays`
- `circles`
- `polygons`
- `angle_marks`
- `annotations`

支持常用派生点：

- `midpoint`
- `perpendicular_foot`
- `line_intersection`
- `circle_line_intersection`
- `circle_circle_intersection`

简单示例：

```json
{
  "caption": "三角形中线示意图",
  "points": [
    { "name": "A", "x": 0, "y": 0 },
    { "name": "B", "x": 6, "y": 0 },
    { "name": "C", "x": 2, "y": 3 },
    { "name": "M", "type": "midpoint", "points": ["A", "B"] }
  ],
  "segments": [
    { "from": "A", "to": "B" },
    { "from": "B", "to": "C" },
    { "from": "C", "to": "A" },
    { "from": "C", "to": "M", "style": "auxiliary" }
  ],
  "annotations": [
    { "text": "M 为 AB 中点", "at": "M", "offset": [0.1, 0.2] }
  ]
}
```

兼容说明：

- `points` 推荐数组写法，也兼容 `"points": {"A": [0, 0]}` 这种紧凑写法。
- `angle_marks[].size` 会自动兼容为 `radius`。
- `annotations[].position` / `pos` 会自动兼容为坐标标注。
- 空几何场景会被跳过；疑似被错误 `viewport` 裁空时会自动重试。

## 解题图卡内嵌绘图

当题目需要函数图像或曲线辅助理解时，推荐让 LLM 一次性调用 `render_math_solution_card`，并传入 `plot_spec_json`。

示例：

```json
{
  "question": "求 y=x^2-4x+3 的顶点、零点，并画出图像",
  "answer": "配方得 $y=(x-2)^2-1$，顶点为 $(2,-1)$，零点为 $x=1,3$。",
  "key_formula": "y=(x-2)^2-1",
  "plot_spec_json": "{\"kind\":\"function\",\"expression\":\"x^2-4*x+3\",\"x_range\":\"-1,5\",\"title\":\"y=x^2-4x+3\"}",
  "plot_caption": "抛物线开口向上，顶点在 (2,-1)。",
  "plot_position": "after_key_formula"
}
```

`plot_spec_json.kind` 支持：

- `function`
- `multiple`
- `implicit`
- `polar`
- `parametric`
- `surface`
- `multiple_surfaces`
- `spherical`
- `implicit3d`
- `parametric3d`
- `vector_field_2d`
- `vector3d`

常用 `plot_spec_json` 示例：

```text
{"kind":"multiple_surfaces","expressions":["x^2+y^2","sqrt(x^2+y^2)"],"x_range":"-3,3","y_range":"-3,3"}
{"kind":"spherical","expression":"1+0.3*sin(4*theta)*cos(3*phi)","theta_range":"0,pi","phi_range":"0,2*pi"}
{"kind":"implicit3d","expression":"x^2+y^2+z^2=1","x_range":"-1.5,1.5","y_range":"-1.5,1.5","z_range":"-1.5,1.5"}
{"kind":"vector3d","vectors":"1,2,3:red:v1; 0,0,0->3,4,1:blue:v2"}
```

## 配置模块

`_conf_schema.json` 已按模块整理，WebUI 中会比旧版更容易扫：

- `基础开关`：总开关、关键词、调试日志。
- `LLM 提示与识图策略`：自动工具提示、识图提示、自由布局、公式修复。
- `自然预回复`：出图前先回一句“正在处理”的文案与策略。
- `渲染引擎与临时文件`：浏览器后端、缓存、清理、超时、视口、MathJax。
- `图片发送`：发送组件类型，以及发送前压缩参数。
- `图卡样式`：主题、颜色、字号、圆角、间距。
- `几何图功能`：几何图开关、位置、提示词、空图跳过。
- `几何图样式`：几何图尺寸、DPI、字体、线条和颜色。
- `函数绘图`：绘图工具提示、默认范围、采样密度、三维视角和图卡嵌入。

旧版扁平配置 key 会作为隐藏兼容项保留，升级后不会因为分组而直接丢掉旧自定义值。

## 图片发送排障

如果日志显示已经生成 PNG，但聊天里没看到图片，优先打开：

```text
debug_logging_enabled = true
```

重点看日志：

- `render_to_png ... target=...`：说明图卡是否真的生成。
- `image send inspect ... bytes=... width=... height=...`：说明发送前图片大小。
- `image send payload prepared transport=file ...`：说明当前走本地文件图片组件。
- `image send payload prepared transport=base64 ...`：说明当前走 base64 图片组件。
- `image direct send complete method=context ...`：说明 LLM 工具场景已通过 AstrBot 主动发送链路把图片发出。
- `math_render tool image context/event send failed ...`：说明直接发送失败，日志会带异常和图片路径；工具结果会提示模型改用 `send_message_to_user` 发送该路径。
- 图片直发成功后，工具会返回一条简短状态，让 bot 继续补一句自然收尾；如果只看到图片没有收尾回复，请确认版本至少为 `v0.4.6`。

默认发送方式是：

```text
send_image_transport = file
```

这和 `send_message_to_user` 里传 `path` 的图片发送方式一致。只有在平台明确支持 base64 图片组件时，才建议改成 `base64`。

## 临时文件

默认保存到：

```text
AstrBot/data/plugins/astrbot_plugin_math_render/temp
```

如果无法解析 AstrBot 数据目录，会回退到插件目录下的：

```text
.tmp/
```

相关配置在 `渲染引擎与临时文件` 模块里。

## 依赖

```text
playwright>=1.50.0
sympy>=1.13
markdown>=3.6
matplotlib>=3.8
numpy>=1.24
```

说明：

- `playwright`：本地浏览器截图。
- `sympy`：表达式转 LaTeX、几何派生点计算。
- `markdown`：Markdown 转 HTML。
- `matplotlib`：几何图和函数图像绘制。
- `numpy`：函数采样、曲面网格和向量场计算。

## 参考项目

函数绘图能力的模式覆盖和交互设计参考了 [D1ff1culTT/astrbot_plugin_math_plotter](https://github.com/D1ff1culTT/astrbot_plugin_math_plotter)，包括多曲面、球坐标曲面、三维隐式曲面和三维向量等专项绘图方向。本插件在此基础上将绘图能力整合进解题图卡、LLM 工具调用和配置模块，便于在数学讲解中把文字、公式和图像放进同一张卡片。

## 兼容性

- AstrBot：`>=4.16,<5`
- 已针对 Linux root 场景关闭浏览器沙箱做兼容。
- 几何文字如果在 Linux 显示为方框，建议安装 `Noto Sans CJK SC` 或 `WenQuanYi Zen Hei`，并配置 `geometry_font_family`。

## 打包上传

仓库提供打包脚本：

```text
build_math_render_upload_zip.py
```

生成的 zip 会以插件文件作为根目录，适合直接在 AstrBot WebUI 上传安装。

## 调试建议

遇到这些问题时，先打开 `debug_logging_enabled`：

- bot 没触发工具。
- 工具触发了但没出图。
- 几何题没有附带几何图。
- 绘图失败但解题卡仍然发出。
- 图片路径存在，但聊天里看不到图。

日志通常能看到：提示是否注入、几何场景是否解析、绘图是否成功、渲染后端、输出路径、图片大小和发送组件类型。
