from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

from .config_utils import get_config_value
from .conversion import (
    LATEXIFY_SYSTEM_PROMPT,
    LatexConversionResult,
    build_latexify_prompt,
    is_likely_latex,
    locally_convert_expression_to_latex,
    normalize_latex_output,
)
from .rendering import DEFAULT_STYLE, MathRenderService, PLUGIN_NAME, SolutionCardContent
from .plotting import MathPlotService, PlotResult
from .solving import SOLVER_SYSTEM_PROMPT, build_solver_prompt, parse_solver_response


FORMULA_COMMANDS = (
    "lateximg",
    "latex2img",
    "exprimg",
    "expr2img",
    "公式渲染",
    "latex渲染",
    "表达式渲染",
    "公式转图",
)
SOLVE_COMMANDS = ("mathsolveimg", "解答渲染", "数学出图", "题目出图")
CLEANUP_COMMANDS = ("mathimgcleanup", "渲染清理", "公式清理")
PLOT_COMMANDS = ("plot", "mathplot", "functionplot", "函数绘图", "绘图")
PLOT3D_COMMANDS = ("plot3d", "surfaceplot", "三维绘图", "曲面绘图")
PLOT3D_MULTIPLE_COMMANDS = ("plot3dm", "plot3dmultiple", "多曲面绘图", "三维多曲面")
SPHERICAL3D_COMMANDS = ("spherical", "spherical3d", "球坐标绘图", "球坐标曲面")
IMPLICIT3D_COMMANDS = ("implicit3d", "implicit3D", "三维隐式", "隐式曲面")
POLAR_COMMANDS = ("polar", "polarplot", "极坐标绘图")
PARAMETRIC_COMMANDS = ("parametric", "paramplot", "参数绘图")
VECTOR_FIELD_COMMANDS = ("vector2d", "vectorfield", "向量场")
VECTOR3D_COMMANDS = ("vector3d", "三维向量", "空间向量")
PARAMETRIC3D_COMMANDS = ("parametric3d", "param3d", "三维参数曲线")

MATH_SIGNAL_PATTERNS = (
    r"\\(?:frac|sqrt|sum|int|lim|begin|alpha|beta|gamma|theta|pi)\b",
    r"\$\$.*\$\$",
    r"\$[^$]+\$",
    r"[A-Za-z0-9\)\]]\s*=\s*[A-Za-z0-9\(\[]",
    r"\d+\s*[\+\-\*/×÷]\s*\d+",
    r"[A-Za-z]\^[A-Za-z0-9]",
)

DEFAULT_MATH_KEYWORDS = (
    "数学",
    "公式",
    "方程",
    "函数",
    "导数",
    "积分",
    "极限",
    "矩阵",
    "向量",
    "概率",
    "统计",
    "证明",
    "几何",
    "代数",
    "solve",
    "equation",
    "derivative",
    "integral",
    "matrix",
    "proof",
    "latex",
)

IMAGE_MATH_INTENT_KEYWORDS = (
    "这题",
    "这道题",
    "这个题",
    "题目",
    "题干",
    "截图里的题",
    "图里的题",
    "图中这题",
    "帮我做",
    "帮我解",
    "帮我讲",
    "怎么做",
    "怎么解",
    "如何解",
    "求解",
    "解答",
    "讲解",
    "思路",
    "过程",
    "答案",
    "证明",
    "求证",
    "算一下",
    "会做吗",
    "solve this",
    "how to solve",
    "show steps",
    "math problem",
)

DEFAULT_GEOMETRY_KEYWORDS = (
    "几何",
    "平面几何",
    "解析几何",
    "三角形",
    "四边形",
    "圆",
    "半圆",
    "弧",
    "切线",
    "弦",
    "半径",
    "直径",
    "垂直",
    "平行",
    "中点",
    "角平分线",
    "相似",
    "全等",
    "坐标系",
    "geometry",
    "triangle",
    "circle",
    "angle",
    "polygon",
    "perpendicular",
    "parallel",
)

DEFAULT_PLOT_KEYWORDS = (
    "画图",
    "绘图",
    "图像",
    "函数图像",
    "函数作图",
    "曲线",
    "曲面",
    "多曲面",
    "隐式曲面",
    "球坐标",
    "极坐标",
    "参数方程",
    "参数曲线",
    "向量场",
    "三维向量",
    "plot",
    "graph",
    "curve",
    "surface",
    "spherical",
    "implicit3d",
    "polar",
    "parametric",
    "vector field",
    "vector3d",
    "function graph",
    "function plot",
)

PLOT_TOOL_AWARENESS_PROMPT = """When the user asks to draw or compare math functions, curves, implicit equations, polar curves, parametric curves, 3D surfaces, spherical surfaces, implicit 3D surfaces, or vector diagrams, you can call the plotting tools from this plugin.

Available plotting tools:
- `plot_function`: draw one-variable functions y=f(x).
- `plot_multiple`: compare multiple one-variable functions in one coordinate system.
- `plot_implicit`: draw implicit equations F(x,y)=0.
- `plot_polar`: draw polar curves r=f(theta).
- `plot_parametric`: draw 2D parametric curves x=f(t), y=g(t).
- `plot_3d_function`: draw 3D surfaces z=f(x,y). Use this only when there is one z expression in x and y.
- `plot_3d_multiple`: compare multiple 3D surfaces z=f(x,y) in one 3D coordinate system.
- `plot_3d_spherical`: draw spherical-coordinate surfaces r=f(theta,phi), where theta is polar angle and phi is azimuth.
- `plot_implicit_3d`: draw implicit 3D surfaces F(x,y,z)=0, such as spheres and hyperboloids.
- `plot_3d_parametric`: draw 3D parametric curves x=f(t), y=g(t), z=h(t). Use this for three equations like x=sin(2t), y=cos(3t), z=t/4.
- `plot_vector_field_2d`: draw 2D vector fields F=(Fx(x,y), Fy(x,y)).
- `plot_vector_3d`: draw finite 3D vectors such as "1,2,3:red:v1; 0,0,0->3,4,1:blue:v2".

Tool selection rule: if a screenshot or prompt shows three equations `x=...`, `y=...`, and `z=...` using parameter `t`, it is a 3D parametric curve, even if the user casually says "3D surface" or "三维曲面". Do not replace the user's formulas with an unrelated surface such as z=cos(x)cos(y).
If the user asks for r=f(theta,phi), spherical coordinates, radiation lobes, or 球坐标曲面, use `plot_3d_spherical`. If the formula contains x, y, and z in one equation such as x^2+y^2+z^2=1, use `plot_implicit_3d`. If the user asks to compare several z=f(x,y) surfaces, use `plot_3d_multiple`.

Use formula or solution-card rendering for normal formula display or step-by-step answers. Use plotting tools when the user explicitly wants a graph, curve, surface, or vector diagram."""

PLOT_IN_SOLUTION_CARD_PROMPT = """`render_math_solution_card` can embed a generated plot inside the same solution card.

When the user asks a math question whose explanation benefits from a graph, do not send a separate plot first. Prefer one call to `render_math_solution_card` and pass `plot_spec_json` as a JSON string.

Supported `plot_spec_json` examples:
- Function: {"kind":"function","expression":"x^2-4*x+3","x_range":"-2,6","title":"Parabola"}
- Multiple functions: {"kind":"multiple","expressions":["sin(x)","cos(x)"],"x_range":"-10,10"}
- Implicit curve: {"kind":"implicit","expression":"x^2+y^2=1","x_range":"-2,2","y_range":"-2,2"}
- Polar: {"kind":"polar","expression":"sin(3*theta)","theta_range":"0,2*pi"}
- Parametric: {"kind":"parametric","x_expression":"cos(t)","y_expression":"sin(t)","t_range":"0,2*pi"}
- Surface: {"kind":"surface","expression":"sin(sqrt(x^2+y^2))","x_range":"-6,6","y_range":"-6,6"}
- Multiple 3D surfaces: {"kind":"multiple_surfaces","expressions":["x^2+y^2","sqrt(x^2+y^2)"],"x_range":"-3,3","y_range":"-3,3"}
- Spherical surface: {"kind":"spherical","expression":"1+0.35*sin(4*theta)*cos(3*phi)","theta_range":"0,pi","phi_range":"0,2*pi"}
- Implicit 3D surface: {"kind":"implicit3d","expression":"x^2+y^2+z^2=1","x_range":"-1.5,1.5","y_range":"-1.5,1.5","z_range":"-1.5,1.5"}
- 3D parametric: {"kind":"parametric3d","x_expression":"cos(t)","y_expression":"sin(t)","z_expression":"t/5","t_range":"0,4*pi"}
- Vector field: {"kind":"vector_field_2d","x_expression":"-y","y_expression":"x","x_range":"-5,5","y_range":"-5,5"}
- 3D vectors: {"kind":"vector3d","vectors":"1,2,3:red:v1; 0,0,0->3,4,1:blue:v2"}

If the source has `x=...`, `y=...`, and `z=...` as functions of `t`, use kind `parametric3d`; do not use kind `surface`.
If the source is a single equation involving x, y, and z, use kind `implicit3d`. If the source is r=f(theta,phi), use kind `spherical`.

Also pass `plot_caption` when a short caption helps. Use `plot_position` only when needed; valid values match geometry positions such as `after_key_formula`, `before_answer`, and `after_answer`."""

AUTO_RENDER_PROMPT = """你拥有两个可用的数学渲染工具：
1. `render_math_solution_card`：把完整数学解答渲染成高质量图片并直接发送给用户。
2. `render_latex_formula`：把单条 LaTeX 公式或普通数学表达式渲染成高质量图片并直接发送给用户。

当用户的问题明显是数学题、推导题、公式题，或者答案里有较多公式时，你可以主动调用渲染工具。
优先在这些场景使用：
- 多步推导、证明、矩阵、向量、微积分、概率统计、方程求解
- 用户明确想要更清晰、适合转发、适合截图的答案

使用规则：
- 可以自由选择图片风格，`style_hint` 可用 paper、notebook、blackboard、aurora，也可以结合语义自行挑选。
- 如果已经发送了图片，后续文字尽量简短，不要再把整段答案完整重复一遍。
- 如果用户明确要求只要纯文本，不要调用渲染工具。"""

IMAGE_MATH_TOOL_AWARENESS_PROMPT = """当前对话包含用户上传的图片。
如果你识别到图片里是数学题、公式、手写推导、试卷、课本例题，或其他明显的数学内容，请记住你可以调用以下工具：
- `render_math_solution_card`：把完整解答整理成高质量数学图卡并直接发送给用户。
- `render_latex_formula`：把单个公式或普通数学表达式整理成清晰图片并直接发送给用户。
如果图片内容不是数学相关，就忽略这条提醒，按正常识图对话处理。"""

IMAGE_MATH_AUTO_RENDER_PROMPT = """当前用户很可能上传了数学题图片或截图，并希望你直接讲解或解答。
处理这类请求时：
- 先理解图片中的题目内容，再组织答案。
- 如果属于数学题讲解、步骤推导、证明、求解、公式整理，优先使用 `render_math_solution_card` 输出高质量解答图。
- 如果只是单个公式或表达式需要更清晰展示，优先使用 `render_latex_formula`。
- 不要因为可以使用 Python 或代码工具就默认走代码式回复；除非用户明确要求代码、纯计算验证，或渲染工具明显不适合，否则优先使用数学渲染工具交付结果。
- 如确实需要借助其他工具辅助计算，也应尽量把最终结果整理为清晰的数学图卡发给用户。"""

PRE_REPLY_SYSTEM_PROMPT = """你是 AstrBot 的回复助手。请根据当前人设风格，用自然、简短、像正常聊天一样的一句话告诉用户：请求已经开始处理。
要求：
1. 只输出一句自然回复，不要解释流程。
2. 不要使用 Markdown、列表、代码块。
3. 不要提到“系统提示词”“工具调用”“插件配置”等内部术语。
4. 语气贴近当前人设，但内容要明确表达“已经开始整理并准备发图”。"""

DEFAULT_FREE_LAYOUT_MARKDOWN_PROMPT = """当你希望把整张图卡排得更自然、更像讲义或笔记，而不是固定分成“题目 / 关键公式 / 解答 / 最终答案”几个区块时，请这样做：
- 把 `layout_mode` 设为 `free`
- 把主要内容写入 `markdown_content`
- `markdown_content` 允许使用 Markdown 标题、列表、强调、引用、表格，也允许混合 `$...$` 和 `$$...$$` 数学公式
- 如果同时传入 `geometry_scene_json` 或 `plot_spec_json`，图会由插件单独插入；不要在 `markdown_content` 末尾留下“几何示意图：”“函数图像：”“如下图所示：”这类空占位，正文必须包含完整证明或解题步骤
- 适合证明题、讲解题、长推导、图文混合说明、希望更自由排版的场景
- 如果只是标准问答、短解题、结构清晰的题目，也可以继续使用 `structured` 布局"""


GEOMETRY_TOOL_AWARENESS_PROMPT = """当题目涉及几何、解析几何、三角形、圆、角度关系、辅助线或图形证明时，请记住：
- `render_math_solution_card` 除了普通数学解答，还支持 `geometry_scene_json`
- `geometry_scene_json` 应该是一个 JSON 字符串，用来描述几何示意图
- 你可以在同一张解答图里同时给出文字解答和几何关系图
- 几何图的坐标可以是“示意图坐标”，重点是关系清晰，不要求严格按真实比例
- 适合画：三角形、圆、半圆、辅助线、角标、点位关系图、简单坐标几何示意图"""

IMAGE_GEOMETRY_AUTO_RENDER_PROMPT = """如果用户上传的是几何题图片、手写辅助图、试卷里的几何证明题，或任何明显需要画图辅助理解的数学图片，请优先考虑：
- 先理解图中题意，再组织解答
- 若几何示意图能明显帮助用户理解，请调用 `render_math_solution_card`
- 在该工具里补充 `geometry_scene_json`，把关键点、线段、圆、辅助线、角标和关系图一起画出来
- 图形可以是清晰的示意图，不必追求严格比例，但关系必须正确
- 除非用户明确只要纯文本，否则不要只是冷冰冰给代码或算式，尽量把最终结果整理成图卡交付"""


GEOMETRY_SCHEMA_REMINDER_PROMPT = """When you provide `geometry_scene_json` or `geometry_scene`, return a plain JSON object using supported keys such as `points`, `segments`, `lines`, `rays`, `circles`, `polygons`, `angle_marks`, and `annotations`.
Do not invent a custom DSL like `{ "type": "GeometryScene", "setup": [...] }`.
Prefer the canonical field names: point `name`, segment/angle `from` + `to`, circle `orientation`, and numeric `offset` for label placement.
Prefer `points` as an array, but compact point maps like `"points": {"A": [0, 0], "B": {"x": 1, "y": 0}}` are also accepted.
Use `segments` for finite edges like `AD`, `BD`, or `OD`; use `lines` only for infinite straight lines defined by `through: ["A", "B"]`.
If the figure is a semicircle, express it explicitly with `type: "semicircle_upper"` / `semicircle_lower` / `semicircle_left` / `semicircle_right`, or with `semicircle: true` plus `orientation`.
If you need a semicircle or an auxiliary construction, express it with normal points, segments, labels, and other supported geometry fields."""


class MathRenderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or AstrBotConfig()
        self.renderer = MathRenderService(self, self.config, plugin_name=PLUGIN_NAME)
        self.plotter = MathPlotService(self.config, self.renderer.temp_dir, debug=self._debug)

    async def initialize(self) -> None:
        await self.renderer.prepare()
        logger.info("math_render plugin initialized. temp_dir=%s", self.renderer.temp_dir)
        self._debug("initialized with temp_dir=%s", self.renderer.temp_dir)

    @filter.on_llm_request()
    async def inject_auto_render_prompt(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self._bool("auto_render_enabled", True):
            return
        if not self._bool("auto_render_prompt_enabled", True):
            return

        prompt_text = "\n".join(part for part in [req.prompt or "", event.message_str or ""] if part)
        has_image = self._request_has_image(event, req)
        image_tool_prompt_enabled = self._bool("image_math_tool_prompt_enabled", True)
        geometry_tool_prompt_enabled = self._bool("geometry_tool_prompt_enabled", True)
        plot_tool_prompt_enabled = self._bool("plot_tool_prompt_enabled", True)
        is_math_text = self._looks_like_math(prompt_text)
        is_geometry_text = self._looks_like_geometry(prompt_text)
        is_plot_text = self._looks_like_plot(prompt_text)
        is_image_math_request = has_image and self._looks_like_math_image_request(prompt_text)
        if (
            not is_math_text
            and not is_geometry_text
            and not is_plot_text
            and not is_image_math_request
            and not (has_image and image_tool_prompt_enabled)
        ):
            return

        existing = req.system_prompt.strip()
        prompt_parts = [existing]
        if is_math_text or is_image_math_request:
            prompt_parts.append(AUTO_RENDER_PROMPT)
        if plot_tool_prompt_enabled and is_plot_text:
            prompt_parts.append(self._text("plot_tool_awareness_prompt", PLOT_TOOL_AWARENESS_PROMPT))
        if self._bool("plot_in_solution_card_enabled", True) and (
            is_math_text or is_plot_text or is_image_math_request
        ):
            prompt_parts.append(self._text("plot_solution_card_prompt", PLOT_IN_SOLUTION_CARD_PROMPT))
        if has_image and image_tool_prompt_enabled:
            prompt_parts.append(self._text("image_math_tool_awareness_prompt", IMAGE_MATH_TOOL_AWARENESS_PROMPT))
        if is_image_math_request:
            prompt_parts.append(self._text("image_math_auto_render_prompt", IMAGE_MATH_AUTO_RENDER_PROMPT))
        if geometry_tool_prompt_enabled and (is_geometry_text or has_image):
            prompt_parts.append(self._text("geometry_tool_awareness_prompt", GEOMETRY_TOOL_AWARENESS_PROMPT))
            prompt_parts.append(GEOMETRY_SCHEMA_REMINDER_PROMPT)
        if geometry_tool_prompt_enabled and has_image and self._bool("image_geometry_auto_render_prompt_enabled", True):
            prompt_parts.append(self._text("image_geometry_auto_render_prompt", IMAGE_GEOMETRY_AUTO_RENDER_PROMPT))
        if self._bool("llm_render_layout_prompt_enabled", True):
            prompt_parts.append(self._text("llm_render_layout_prompt", DEFAULT_FREE_LAYOUT_MARKDOWN_PROMPT))
        req.system_prompt = "\n\n".join(part for part in prompt_parts if part).strip()
        self._debug(
            "auto render prompt injected has_image=%s image_tool_prompt_enabled=%s geometry_tool_prompt_enabled=%s plot_tool_prompt_enabled=%s is_math_text=%s is_geometry_text=%s is_plot_text=%s is_image_math_request=%s message=%r",
            has_image,
            image_tool_prompt_enabled,
            geometry_tool_prompt_enabled,
            plot_tool_prompt_enabled,
            is_math_text,
            is_geometry_text,
            is_plot_text,
            is_image_math_request,
            event.message_str,
        )

    @filter.command(
        "lateximg",
        alias=["latex2img", "exprimg", "expr2img", "公式渲染", "latex渲染", "表达式渲染", "公式转图"],
    )
    async def lateximg(self, event: AstrMessageEvent):
        formula = self._extract_payload(event.message_str, FORMULA_COMMANDS)
        if not formula:
            yield event.plain_result(
                "用法: /lateximg <LaTeX 公式或普通数学表达式>\n"
                "示例1: /lateximg \\int_0^1 x^2\\,dx = \\frac{1}{3}\n"
                "示例2: /lateximg 1/2"
            )
            return

        try:
            await self._maybe_send_pre_reply(event, scene="formula", trigger="manual", original_text=formula)
            converted = await self._prepare_formula_for_render(event, formula)
            note = f"由 AstrBot Math Render 生成 · 转换方式: {converted.method}"
            image_path = await self.renderer.render_formula_card(
                formula=converted.latex,
                title="数学公式渲染",
                note=note,
                style_hint=self._text("default_style", DEFAULT_STYLE),
                accent_color=self._text("default_accent_color", ""),
            )
        except Exception as exc:
            logger.exception("lateximg render failed")
            yield event.plain_result(f"公式渲染失败: {exc}")
            return

        yield self._image_result_for_send(event, image_path)

    @filter.command("mathsolveimg", alias=["解答渲染", "数学出图", "题目出图"])
    async def mathsolveimg(self, event: AstrMessageEvent):
        question = self._extract_payload(event.message_str, SOLVE_COMMANDS)
        if not question:
            yield event.plain_result(
                "用法: /mathsolveimg <数学问题>\n"
                "示例: /mathsolveimg 求解二次方程 x^2 - 5x + 6 = 0"
            )
            return

        try:
            await self._maybe_send_pre_reply(event, scene="solution", trigger="manual", original_text=question)
            content = await self._solve_question(event, question)
            content = await self._materialize_plot_for_card(content)
            image_path = await self.renderer.render_solution_card(content)
        except Exception as exc:
            logger.exception("mathsolveimg render failed")
            yield event.plain_result(f"解答出图失败: {exc}")
            return

        yield self._image_result_for_send(event, image_path)

    @filter.command("plot", alias=["mathplot", "functionplot"])
    async def plot(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PLOT_COMMANDS)
        if not payload:
            yield event.plain_result(
                "用法: /plot <表达式>\n"
                "示例: /plot sin(x)\n"
                "示例: /plot sin(x), cos(x)\n"
                "示例: /plot x^2 + y^2 = 1"
            )
            return
        try:
            parts = self.plotter.split_expressions(payload)
            if len(parts) >= 2:
                result = self.plotter.plot_multiple(payload)
            elif self._looks_like_implicit_plot(payload):
                result = self.plotter.plot_implicit(payload)
            else:
                result = self.plotter.plot_function(payload)
        except Exception as exc:
            logger.exception("plot command failed")
            yield event.plain_result(f"绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("plot3d", alias=["surfaceplot"])
    async def plot3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PLOT3D_COMMANDS)
        if not payload:
            yield event.plain_result("用法: /plot3d <z=f(x,y)>，例如: /plot3d sin(sqrt(x^2+y^2))")
            return
        try:
            result = self.plotter.plot_surface(payload)
        except Exception as exc:
            logger.exception("plot3d command failed")
            yield event.plain_result(f"三维绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("plot3dm", alias=["plot3dmultiple", "多曲面绘图", "三维多曲面"])
    async def plot3dm(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PLOT3D_MULTIPLE_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) < 2:
            yield event.plain_result("用法: /plot3dm <表达式1>, <表达式2>，例如: /plot3dm x^2+y^2, sqrt(x^2+y^2)")
            return
        try:
            result = self.plotter.plot_multiple_surfaces(payload)
        except Exception as exc:
            logger.exception("plot3dm command failed")
            yield event.plain_result(f"多曲面绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("spherical", alias=["spherical3d", "球坐标绘图", "球坐标曲面"])
    async def spherical3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, SPHERICAL3D_COMMANDS)
        if not payload:
            yield event.plain_result("用法: /spherical <r=f(theta,phi)>，例如: /spherical 1+0.3*sin(4*theta)*cos(3*phi)")
            return
        try:
            result = self.plotter.plot_spherical_3d(payload)
        except Exception as exc:
            logger.exception("spherical command failed")
            yield event.plain_result(f"球坐标曲面绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("implicit3d", alias=["implicit3D", "三维隐式", "隐式曲面"])
    async def implicit3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, IMPLICIT3D_COMMANDS)
        if not payload:
            yield event.plain_result("用法: /implicit3d <F(x,y,z)=0>，例如: /implicit3d x^2+y^2+z^2=1")
            return
        try:
            result = self.plotter.plot_implicit_3d(payload)
        except Exception as exc:
            logger.exception("implicit3d command failed")
            yield event.plain_result(f"隐式三维曲面绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("polar", alias=["polarplot"])
    async def polar(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, POLAR_COMMANDS)
        if not payload:
            yield event.plain_result("用法: /polar <r=f(theta)>，例如: /polar sin(3*theta)")
            return
        try:
            result = self.plotter.plot_polar(payload)
        except Exception as exc:
            logger.exception("polar command failed")
            yield event.plain_result(f"极坐标绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("parametric", alias=["paramplot"])
    async def parametric(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PARAMETRIC_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) != 2:
            yield event.plain_result("用法: /parametric <x(t)>, <y(t)>，例如: /parametric cos(t), sin(t)")
            return
        try:
            result = self.plotter.plot_parametric(parts[0], parts[1])
        except Exception as exc:
            logger.exception("parametric command failed")
            yield event.plain_result(f"参数曲线绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("vector2d", alias=["vectorfield"])
    async def vector2d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, VECTOR_FIELD_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) != 2:
            yield event.plain_result("用法: /vector2d <Fx(x,y)>, <Fy(x,y)>，例如: /vector2d -y, x")
            return
        try:
            result = self.plotter.plot_vector_field_2d(parts[0], parts[1])
        except Exception as exc:
            logger.exception("vector2d command failed")
            yield event.plain_result(f"向量场绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("vector3d", alias=["三维向量", "空间向量"])
    async def vector3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, VECTOR3D_COMMANDS)
        if not payload:
            yield event.plain_result(
                "用法: /vector3d <向量定义>[; <向量定义>]\n"
                "示例: /vector3d 1,2,3:red:v1 ; 0,0,0->3,4,1:blue:v2"
            )
            return
        try:
            result = self.plotter.plot_vectors_3d(payload)
        except Exception as exc:
            logger.exception("vector3d command failed")
            yield event.plain_result(f"三维向量绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("parametric3d", alias=["param3d"])
    async def parametric3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PARAMETRIC3D_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) != 3:
            yield event.plain_result(
                "用法: /parametric3d <x(t)>, <y(t)>, <z(t)>，例如: /parametric3d cos(t), sin(t), t/5"
            )
            return
        try:
            result = self.plotter.plot_parametric_3d(parts[0], parts[1], parts[2])
        except Exception as exc:
            logger.exception("parametric3d command failed")
            yield event.plain_result(f"三维参数曲线绘图失败: {exc}")
            return
        yield self._image_result_for_send(event, result.path)

    @filter.command("plotstatus")
    async def plotstatus(self, event: AstrMessageEvent):
        yield event.plain_result(self.plotter.status_text())

    @filter.command("mathimgcleanup", alias=["渲染清理", "公式清理"])
    async def mathimgcleanup(self, event: AstrMessageEvent):
        removed = await self.renderer.cleanup_temp_files(purge_all=True)
        self._debug("manual cleanup removed=%s", removed)
        yield event.plain_result(f"已清理 {removed} 个渲染临时文件。")

    @filter.llm_tool(name="render_latex_formula")
    async def render_latex_formula_tool(
        self,
        event: AstrMessageEvent,
        latex: str,
        title: str = "",
        note: str = "",
        style_hint: str = "",
        accent_color: str = "",
    ):
        """Render a math formula into a high-quality image and send it to the user.

        Args:
            latex(string): Raw LaTeX formula content, or a plain math expression such as 1/2. Do not wrap it in code fences.
            title(string): Optional short title shown on the card.
            note(string): Optional short note or context shown below the formula.
            style_hint(string): Optional style hint such as paper, notebook, blackboard, aurora, elegant, exam, or vivid.
            accent_color(string): Optional accent color in hex form such as #2563EB.
        """
        await self._maybe_send_pre_reply(event, scene="formula", trigger="tool", original_text=latex)
        converted = await self._prepare_formula_for_render(event, latex)
        final_note = note.strip()
        if not final_note:
            final_note = f"由 AstrBot Math Render 生成 · 转换方式: {converted.method}"
        image_path = await self.renderer.render_formula_card(
            formula=converted.latex,
            title=title.strip() or "数学公式渲染",
            note=final_note,
            style_hint=style_hint or self._text("default_style", DEFAULT_STYLE),
            accent_color=accent_color or self._text("default_accent_color", ""),
        )
        self._debug("llm tool render_latex_formula sent image=%s", image_path)
        fallback = await self._send_image_from_tool(event, image_path)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result()

    @filter.llm_tool(name="render_math_solution_card")
    async def render_math_solution_card_tool(
        self,
        event: AstrMessageEvent,
        question: str = "",
        answer: str = "",
        key_formula: str = "",
        title: str = "",
        style_hint: str = "",
        accent_color: str = "",
        layout_mode: str = "",
        markdown_content: str = "",
        geometry_scene_json: str = "",
        geometry_caption: str = "",
        geometry_position: str = "",
        plot_spec_json: str = "",
        plot_caption: str = "",
        plot_position: str = "",
    ):
        """Render a math answer into a high-quality image card and send it to the user.

        Args:
            question(string): Optional original math problem or prompt. Recommended for structured cards.
            answer(string): Optional answer body, supporting normal text plus inline LaTeX like $x^2$. When using free layout, this can be omitted if markdown_content already contains the full answer.
            key_formula(string): Optional main formula to highlight. Do not include surrounding $$.
            title(string): Optional short card title.
            style_hint(string): Optional style hint such as paper, notebook, blackboard, aurora, minimal, or classroom.
            accent_color(string): Optional accent color in hex form such as #16A34A.
            layout_mode(string): Optional layout mode. Use `structured` for fixed sections, or `free` for Markdown-driven free layout.
            markdown_content(string): Optional Markdown body used when free layout is desired. Supports headings, lists, emphasis, tables, and LaTeX math. When geometry_scene_json or plot_spec_json is provided, do not leave dangling placeholders such as "几何示意图:" or "see the graph below"; include the complete solution or proof text.
            geometry_scene_json(string): Optional geometry scene JSON string for triangles, circles, auxiliary lines, angle marks, and point-relation diagrams. `points` may be the canonical array or a compact object map like {"A":[0,0]}.
            geometry_caption(string): Optional caption shown below the geometry diagram.
            geometry_position(string): Optional geometry placement hint such as `before_content`, `after_question`, `after_key_formula`, `before_answer`, `after_answer`, `after_steps`, `after_final_answer`, or `after_content`.
            plot_spec_json(string): Optional plot spec JSON string. Use it to embed a generated function graph, curve, surface, or vector field into the same solution card.
            plot_caption(string): Optional caption shown below the embedded plot.
            plot_position(string): Optional plot placement hint, using the same values as geometry_position.
        """
        question = question.strip()
        answer = answer.strip()
        key_formula = key_formula.strip()
        layout_mode = layout_mode.strip()
        markdown_content = markdown_content.strip()
        geometry_scene_json = geometry_scene_json.strip()
        geometry_caption = geometry_caption.strip()
        geometry_position = geometry_position.strip()
        plot_spec_json = plot_spec_json.strip()
        plot_caption = plot_caption.strip()
        plot_position = plot_position.strip()

        if not any([question, answer, key_formula, markdown_content, geometry_scene_json, plot_spec_json]):
            raise ValueError(
                "At least one of question, answer, key_formula, markdown_content, geometry_scene_json, or plot_spec_json must be provided."
            )

        preview_text = question or answer or markdown_content or key_formula or geometry_caption or plot_caption or geometry_scene_json or plot_spec_json
        await self._maybe_send_pre_reply(event, scene="solution", trigger="tool", original_text=preview_text)
        content = SolutionCardContent(
            question=question,
            answer=answer,
            title=title.strip() or "数学解答",
            key_formula=key_formula,
            style_hint=style_hint or self._text("default_style", DEFAULT_STYLE),
            accent_color=accent_color or self._text("default_accent_color", ""),
            layout_mode=layout_mode,
            markdown_content=markdown_content,
            geometry_scene=self._parse_geometry_scene_json(geometry_scene_json),
            geometry_caption=geometry_caption,
            geometry_position=geometry_position,
            plot_spec=self._parse_plot_spec_json(plot_spec_json),
            plot_caption=plot_caption,
            plot_position=plot_position,
        )
        content = await self._materialize_plot_for_card(content)
        image_path = await self.renderer.render_solution_card(content)
        self._debug("llm tool render_math_solution_card sent image=%s", image_path)
        fallback = await self._send_image_from_tool(event, image_path)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result()

    @filter.llm_tool(name="plot_function")
    async def plot_function_tool(
        self,
        event: AstrMessageEvent,
        expression: str,
        x_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ):
        """Draw a one-variable function graph y=f(x) and send the image to the user.

        Args:
            expression(string): Function expression in x, for example sin(x), x**2, or exp(-x**2).
            x_range(string): Optional x range as "min,max", for example "-10,10".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
        """
        try:
            result = self.plotter.plot_function(
                expression,
                x_range=x_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        except Exception as exc:
            logger.exception("plot_function tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_multiple")
    async def plot_multiple_tool(
        self,
        event: AstrMessageEvent,
        expressions: str,
        x_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ):
        """Draw multiple one-variable function graphs in one coordinate system.

        Args:
            expressions(string): Comma-separated expressions in x, for example "sin(x), cos(x), x**2".
            x_range(string): Optional x range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
        """
        try:
            result = self.plotter.plot_multiple(
                expressions,
                x_range=x_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        except Exception as exc:
            logger.exception("plot_multiple tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_implicit")
    async def plot_implicit_tool(
        self,
        event: AstrMessageEvent,
        equation: str,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ):
        """Draw an implicit equation F(x,y)=0 or an equation containing '='.

        Args:
            equation(string): Equation such as "x**2+y**2-1" or "x**2+y**2=1".
            x_range(string): Optional x range as "min,max".
            y_range(string): Optional y range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
        """
        try:
            result = self.plotter.plot_implicit(
                equation,
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        except Exception as exc:
            logger.exception("plot_implicit tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_polar")
    async def plot_polar_tool(
        self,
        event: AstrMessageEvent,
        expression: str,
        theta_range: str = "",
        title: str = "",
    ):
        """Draw a polar curve r=f(theta).

        Args:
            expression(string): Polar expression in theta, for example sin(3*theta).
            theta_range(string): Optional theta range as "min,max"; pi is supported.
            title(string): Optional plot title.
        """
        try:
            result = self.plotter.plot_polar(expression, theta_range=theta_range, title=title)
        except Exception as exc:
            logger.exception("plot_polar tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_parametric")
    async def plot_parametric_tool(
        self,
        event: AstrMessageEvent,
        x_expression: str,
        y_expression: str,
        t_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ):
        """Draw a 2D parametric curve x=f(t), y=g(t).

        Args:
            x_expression(string): x(t), for example cos(t).
            y_expression(string): y(t), for example sin(t).
            t_range(string): Optional t range as "min,max"; pi is supported.
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
        """
        try:
            result = self.plotter.plot_parametric(
                x_expression,
                y_expression,
                t_range=t_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        except Exception as exc:
            logger.exception("plot_parametric tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_3d_function")
    async def plot_3d_function_tool(
        self,
        event: AstrMessageEvent,
        expression: str,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ):
        """Draw a 3D surface z=f(x,y).

        Use this for surfaces with one z expression in x and y. If the target is
        a 3D parametric curve such as x=sin(2*t), y=cos(3*t), z=t/4, call
        plot_3d_parametric instead.

        Args:
            expression(string): Surface expression in x and y, for example sin(sqrt(x**2+y**2)). Do not pass x=..., y=..., z=... parametric equations here.
            x_range(string): Optional x range as "min,max".
            y_range(string): Optional y range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
            parametric_parts = self._parse_3d_parametric_equations(expression)
            if parametric_parts:
                self._debug("rerouting plot_3d_function parametric payload to plot_3d_parametric expression=%r", expression)
                result = self.plotter.plot_parametric_3d(
                    parametric_parts["x"],
                    parametric_parts["y"],
                    parametric_parts["z"],
                    title=title or "3D Parametric Curve",
                    xlabel=xlabel,
                    ylabel=ylabel,
                    zlabel=zlabel,
                )
            else:
                result = self.plotter.plot_surface(
                    expression,
                    x_range=x_range,
                    y_range=y_range,
                    title=title,
                    xlabel=xlabel,
                    ylabel=ylabel,
                    zlabel=zlabel,
                )
        except Exception as exc:
            logger.exception("plot_3d_function tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_3d_multiple")
    async def plot_3d_multiple_tool(
        self,
        event: AstrMessageEvent,
        expressions: str,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ):
        """Draw multiple 3D surfaces z=f(x,y) in one 3D coordinate system.

        Args:
            expressions(string): Comma-separated surface expressions in x and y, for example "x**2+y**2, sqrt(x**2+y**2)".
            x_range(string): Optional x range as "min,max".
            y_range(string): Optional y range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
            result = self.plotter.plot_multiple_surfaces(
                expressions,
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        except Exception as exc:
            logger.exception("plot_3d_multiple tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_3d_spherical")
    async def plot_3d_spherical_tool(
        self,
        event: AstrMessageEvent,
        expression: str,
        theta_range: str = "",
        phi_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ):
        """Draw a spherical-coordinate 3D surface r=f(theta,phi).

        Args:
            expression(string): Radius expression in theta and phi, for example "1+0.3*sin(4*theta)*cos(3*phi)".
            theta_range(string): Optional theta range as "min,max"; default is "0,pi".
            phi_range(string): Optional phi range as "min,max"; default is "0,2*pi".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
            result = self.plotter.plot_spherical_3d(
                expression,
                theta_range=theta_range,
                phi_range=phi_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        except Exception as exc:
            logger.exception("plot_3d_spherical tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_implicit_3d")
    async def plot_implicit_3d_tool(
        self,
        event: AstrMessageEvent,
        equation: str,
        x_range: str = "",
        y_range: str = "",
        z_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ):
        """Draw an implicit 3D surface F(x,y,z)=0.

        Args:
            equation(string): Equation such as "x**2+y**2+z**2=1" or zero-form "x**2+y**2-z**2-1".
            x_range(string): Optional x range as "min,max".
            y_range(string): Optional y range as "min,max".
            z_range(string): Optional z range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
            result = self.plotter.plot_implicit_3d(
                equation,
                x_range=x_range,
                y_range=y_range,
                z_range=z_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        except Exception as exc:
            logger.exception("plot_implicit_3d tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_3d_parametric")
    async def plot_3d_parametric_tool(
        self,
        event: AstrMessageEvent,
        x_expression: str,
        y_expression: str,
        z_expression: str,
        t_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ):
        """Draw a 3D parametric curve x=f(t), y=g(t), z=h(t).

        Args:
            x_expression(string): x(t), for example cos(t).
            y_expression(string): y(t), for example sin(t).
            z_expression(string): z(t), for example t/5.
            t_range(string): Optional t range as "min,max"; pi is supported.
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
            result = self.plotter.plot_parametric_3d(
                x_expression,
                y_expression,
                z_expression,
                t_range=t_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        except Exception as exc:
            logger.exception("plot_3d_parametric tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_vector_3d")
    async def plot_vector_3d_tool(
        self,
        event: AstrMessageEvent,
        vectors: str,
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ):
        """Draw finite 3D vectors as arrows in space.

        Args:
            vectors(string): Semicolon-separated vector definitions. Use "x,y,z:color:label" from origin or "x1,y1,z1->x2,y2,z2:color:label".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
            result = self.plotter.plot_vectors_3d(
                vectors,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        except Exception as exc:
            logger.exception("plot_vector_3d tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    @filter.llm_tool(name="plot_vector_field_2d")
    async def plot_vector_field_2d_tool(
        self,
        event: AstrMessageEvent,
        x_expression: str,
        y_expression: str,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ):
        """Draw a 2D vector field F=(Fx(x,y), Fy(x,y)).

        Args:
            x_expression(string): Fx(x,y), for example -y.
            y_expression(string): Fy(x,y), for example x.
            x_range(string): Optional x range as "min,max".
            y_range(string): Optional y range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
        """
        try:
            result = self.plotter.plot_vector_field_2d(
                x_expression,
                y_expression,
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        except Exception as exc:
            logger.exception("plot_vector_field_2d tool failed")
            yield f"Plot failed: {exc}"
            return
        fallback = await self._send_image_from_tool(event, result.path, result.description)
        if fallback:
            yield fallback
            return
        yield self._tool_direct_send_result(result.description)

    async def _solve_question(self, event: AstrMessageEvent, question: str) -> SolutionCardContent:
        provider_id = await self._get_current_provider_id(event)
        if not provider_id:
            raise RuntimeError("当前会话没有可用的 Chat Provider。")

        self._debug("solving question with provider=%s", provider_id)
        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=build_solver_prompt(
                question,
                default_style=self._text("default_style", DEFAULT_STYLE),
                max_steps=self._int("manual_solver_step_limit", 5),
                layout_mode=self._text("llm_render_layout_mode", "auto"),
                geometry_enabled=self._bool("geometry_render_enabled", True)
                and self._bool("geometry_solver_prompt_enabled", True),
                geometry_prompt=self._text("geometry_solver_prompt", ""),
                plot_enabled=self._bool("plot_in_solution_card_enabled", True),
                plot_prompt=self._text("plot_solver_prompt", ""),
            ),
            system_prompt=SOLVER_SYSTEM_PROMPT,
        )
        return parse_solver_response(
            response.completion_text or "",
            question=question,
            default_style=self._text("default_style", DEFAULT_STYLE),
        )

    async def _prepare_formula_for_render(
        self,
        event: AstrMessageEvent,
        raw_formula: str,
    ) -> LatexConversionResult:
        normalized = normalize_latex_output(raw_formula)
        if not normalized:
            raise RuntimeError("公式内容为空。")
        if is_likely_latex(normalized):
            self._debug("formula treated as latex directly")
            return LatexConversionResult(normalized, "already_latex")
        return await self._convert_expression_to_latex(event, normalized)

    async def _convert_expression_to_latex(
        self,
        event: AstrMessageEvent,
        expression: str,
    ) -> LatexConversionResult:
        backend = self._text("expression_latexify_backend", "auto").lower()
        if backend not in {"auto", "local", "llm"}:
            backend = "auto"

        errors: list[str] = []
        self._debug("latexify start backend=%s expression=%r", backend, expression)

        if backend in {"auto", "local"}:
            try:
                local_result = locally_convert_expression_to_latex(expression)
                if local_result and local_result.latex.strip():
                    self._debug("latexify local success method=%s", local_result.method)
                    return local_result
                errors.append("local conversion returned empty result")
            except Exception as exc:
                errors.append(f"local conversion failed: {exc}")
                self._debug("latexify local failed: %s", exc)
                if backend == "local":
                    raise RuntimeError(f"本地表达式转 LaTeX 失败: {exc}") from exc

        llm_fallback_enabled = self._bool("allow_llm_latexify_fallback", True)
        if backend == "llm" or (backend == "auto" and llm_fallback_enabled):
            try:
                llm_result = await self._llm_convert_expression_to_latex(event, expression)
                self._debug("latexify llm success")
                return llm_result
            except Exception as exc:
                errors.append(f"llm conversion failed: {exc}")
                self._debug("latexify llm failed: %s", exc)
                if backend == "llm":
                    raise RuntimeError(f"LLM 表达式转 LaTeX 失败: {exc}") from exc

        joined = "；".join(errors) if errors else "没有可用的表达式转 LaTeX 后端"
        raise RuntimeError(f"表达式转 LaTeX 失败：{joined}")

    async def _llm_convert_expression_to_latex(
        self,
        event: AstrMessageEvent,
        expression: str,
    ) -> LatexConversionResult:
        provider_id = await self._get_current_provider_id(event)
        if not provider_id:
            raise RuntimeError("当前会话没有可用的 Chat Provider。")

        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=build_latexify_prompt(expression),
            system_prompt=LATEXIFY_SYSTEM_PROMPT,
        )
        latex = normalize_latex_output(response.completion_text or "")
        if not latex:
            raise RuntimeError("LLM 没有返回可用的 LaTeX 结果。")
        return LatexConversionResult(latex=latex, method="llm")

    async def _maybe_send_pre_reply(
        self,
        event: AstrMessageEvent,
        *,
        scene: str,
        trigger: str,
        original_text: str,
    ) -> None:
        if trigger == "manual" and not self._bool("send_pre_reply_before_manual_render", True):
            return
        if trigger == "tool" and not self._bool("send_pre_reply_before_tool_render", True):
            return

        extra_key = f"_math_render_pre_reply::{trigger}::{scene}"
        if event.get_extra(extra_key, False):
            return

        fallback = self._fallback_pre_reply(scene)
        reply_text = fallback
        if self._bool("pre_reply_use_llm", True):
            try:
                reply_text = await self._generate_pre_reply_with_llm(event, scene=scene, original_text=original_text)
            except Exception as exc:
                self._debug("pre-reply llm failed: %s", exc)
                reply_text = fallback

        cleaned = self._clean_pre_reply(reply_text, fallback)
        await event.send(MessageChain().message(cleaned))
        event.set_extra(extra_key, True)
        self._debug("pre-reply sent trigger=%s scene=%s text=%r", trigger, scene, cleaned)

    async def _generate_pre_reply_with_llm(
        self,
        event: AstrMessageEvent,
        *,
        scene: str,
        original_text: str,
    ) -> str:
        provider_id = await self._get_current_provider_id(event)
        if not provider_id:
            raise RuntimeError("当前会话没有可用的 Chat Provider。")

        persona_prompt = await self._resolve_persona_prompt(event)
        system_prompt = self._text("pre_reply_system_prompt", PRE_REPLY_SYSTEM_PROMPT)
        if persona_prompt:
            system_prompt = f"{persona_prompt}\n\n{system_prompt}"

        scene_name = "公式渲染" if scene == "formula" else "解答出图"
        prompt = self._apply_prompt_template(
            self._text(
                "pre_reply_user_prompt",
                "场景：{{scene_name}}\n用户原始内容：{{original_text}}\n请按当前人设风格，回复一句自然的话，表示你已经开始处理并稍后发图。",
            ),
            scene_name=scene_name,
            original_text=(original_text or "").strip(),
        )
        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt=system_prompt,
        )
        text = (response.completion_text or "").strip()
        if not text:
            raise RuntimeError("LLM 预回复为空。")
        return text

    async def _resolve_persona_prompt(self, event: AstrMessageEvent) -> str:
        conversation_persona_id = None
        try:
            cid = await self.context.conversation_manager.get_curr_conversation_id(event.unified_msg_origin)
            if cid:
                conversation = await self.context.conversation_manager.get_conversation(event.unified_msg_origin, cid)
                if conversation:
                    conversation_persona_id = getattr(conversation, "persona_id", None)
        except Exception as exc:
            self._debug("failed to load conversation persona: %s", exc)

        provider_settings = self.context.get_config(event.unified_msg_origin).get("provider_settings", {})
        persona_id, persona, _, _ = await self.context.persona_manager.resolve_selected_persona(
            umo=event.unified_msg_origin,
            conversation_persona_id=conversation_persona_id,
            platform_name=event.get_platform_name(),
            provider_settings=provider_settings,
        )
        if persona and persona.get("prompt"):
            self._debug("resolved persona=%s", persona_id)
            return str(persona.get("prompt", "")).strip()

        try:
            default_persona = await self.context.persona_manager.get_default_persona_v3(event.unified_msg_origin)
            if default_persona and default_persona.get("prompt"):
                return str(default_persona.get("prompt", "")).strip()
        except Exception as exc:
            self._debug("failed to load default persona: %s", exc)
        return ""

    async def _get_current_provider_id(self, event: AstrMessageEvent) -> str | None:
        try:
            return await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        except Exception as exc:
            self._debug("failed to resolve current provider: %s", exc)
            return None

    def _image_chain_for_send(self, image_path: str | Path) -> tuple[MessageChain | None, Path | None]:
        prepared_path = self._prepare_image_for_send(Path(image_path))
        if prepared_path is None:
            return None, None

        transport = self._text("send_image_transport", "file").lower()
        if transport == "base64":
            data = prepared_path.read_bytes()
            encoded = base64.b64encode(data).decode("ascii")
            self._debug(
                "image send payload prepared transport=base64 path=%s bytes=%s base64_chars=%s",
                prepared_path,
                len(data),
                len(encoded),
            )
            return MessageChain().base64_image(encoded), prepared_path

        size = prepared_path.stat().st_size
        self._debug("image send payload prepared transport=file path=%s bytes=%s", prepared_path, size)
        return MessageChain().file_image(str(prepared_path)), prepared_path

    def _image_result_for_send(self, event: AstrMessageEvent, image_path: str | Path):
        chain, _ = self._image_chain_for_send(image_path)
        if chain is None:
            return event.plain_result("图片已经生成，但发送前找不到图片文件；请查看 AstrBot 日志。")
        return event.chain_result(chain.chain)

    async def _send_image_from_tool(
        self,
        event: AstrMessageEvent,
        image_path: str | Path,
        description: str = "",
    ) -> str | None:
        chain, prepared_path = self._image_chain_for_send(image_path)
        if chain is None or prepared_path is None:
            logger.error("math_render tool image send failed: prepared image is missing for %s", image_path)
            return "图片已经生成，但发送前找不到图片文件；请查看 AstrBot 日志。"

        session = str(getattr(event, "unified_msg_origin", "") or "")
        errors: list[str] = []
        send_message = getattr(getattr(self, "context", None), "send_message", None)
        if callable(send_message) and session:
            try:
                self._debug(
                    "image direct send attempt method=context session=%s path=%s",
                    session,
                    prepared_path,
                )
                sent = await send_message(session, chain)
                self._debug(
                    "image direct send complete method=context sent=%s session=%s path=%s",
                    sent,
                    session,
                    prepared_path,
                )
                if sent:
                    return None
                errors.append("context.send_message returned False")
            except Exception as exc:
                errors.append(f"context.send_message failed: {exc}")
                logger.exception("math_render tool image context send failed: path=%s", prepared_path)

        try:
            self._debug("image direct send attempt method=event path=%s", prepared_path)
            await event.send(chain)
            self._debug("image direct send complete method=event path=%s", prepared_path)
            return None
        except Exception as exc:
            errors.append(f"event.send failed: {exc}")
            logger.exception("math_render tool image event send failed: path=%s", prepared_path)

        fallback_text = (
            "The image was rendered successfully, but the plugin could not send it directly. "
            "You MUST call `send_message_to_user` now with "
            f"`messages=[{{\"type\":\"image\",\"path\":\"{prepared_path}\"}}]` to deliver it to the user. "
            f"Rendered image path: {prepared_path}"
        )
        if errors:
            fallback_text += "\n\nDirect send errors: " + "; ".join(errors)
        if description:
            fallback_text += f"\n\nImage description: {description}"
        return fallback_text

    def _tool_direct_send_result(self, description: str = "") -> str:
        message = (
            "The rendered image has already been sent directly to the user. "
            "Reply with one short natural follow-up only. Do not repeat the full solution or claim another send is needed."
        )
        if description:
            message += f"\n\nImage description: {description}"
        return message

    def _prepare_image_for_send(self, image_path: Path) -> Path | None:
        if not image_path.exists():
            logger.error("math_render image send failed: file does not exist: %s", image_path)
            return None

        try:
            from PIL import Image as PILImage
        except ImportError:
            size = image_path.stat().st_size
            self._debug("image send without PIL path=%s bytes=%s", image_path, size)
            return image_path

        max_bytes = max(self._int("send_image_max_bytes", 7_500_000), 200_000)
        max_side = max(self._int("send_image_max_side", 4096), 512)
        jpeg_quality = min(max(self._int("send_image_jpeg_quality", 92), 50), 98)

        try:
            with PILImage.open(image_path) as image:
                width, height = image.size
                size = image_path.stat().st_size
                self._debug(
                    "image send inspect path=%s bytes=%s width=%s height=%s",
                    image_path,
                    size,
                    width,
                    height,
                )
                if size <= max_bytes and max(width, height) <= max_side:
                    return image_path

                scale = min(max_side / max(width, height), 1.0)
                next_width = max(int(width * scale), 1)
                next_height = max(int(height * scale), 1)
                resized = image
                if scale < 1.0:
                    resized = image.resize((next_width, next_height), PILImage.Resampling.LANCZOS)

                png_path = image_path.with_name(f"{image_path.stem}_send.png")
                resized.save(png_path, format="PNG", optimize=True)
                png_size = png_path.stat().st_size
                if png_size <= max_bytes:
                    self._debug(
                        "image send compressed png path=%s bytes=%s width=%s height=%s",
                        png_path,
                        png_size,
                        next_width,
                        next_height,
                    )
                    return png_path

                jpg_path = image_path.with_name(f"{image_path.stem}_send.jpg")
                rgb = PILImage.new("RGB", resized.size, "white")
                if resized.mode == "RGBA":
                    rgb.paste(resized, mask=resized.getchannel("A"))
                else:
                    rgb.paste(resized.convert("RGB"))
                rgb.save(jpg_path, format="JPEG", quality=jpeg_quality, optimize=True)
                self._debug(
                    "image send compressed jpeg path=%s bytes=%s width=%s height=%s quality=%s",
                    jpg_path,
                    jpg_path.stat().st_size,
                    next_width,
                    next_height,
                    jpeg_quality,
                )
                return jpg_path
        except Exception as exc:
            logger.exception("math_render image send preparation failed: %s", image_path)
            self._debug("image send preparation failed: %s", exc)
            return image_path

    def _apply_prompt_template(self, template: str, **values: str) -> str:
        rendered = template or ""
        for key, value in values.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value or "")
        return rendered.strip()

    def _fallback_pre_reply(self, scene: str) -> str:
        if scene == "formula":
            return self._text("pre_reply_fallback_text_formula", "我来把这个公式整理成清晰的图片，稍等一下。")
        return self._text("pre_reply_fallback_text_solution", "我先整理思路并生成解答图，马上发你。")

    def _clean_pre_reply(self, text: str, fallback: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        cleaned = cleaned.strip("`")
        if not cleaned:
            return fallback
        if cleaned.startswith(("```", "-", "*", "1.")):
            return fallback
        return cleaned

    def _looks_like_math(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False

        lowered = candidate.lower()
        custom_keywords = [
            item.strip().lower()
            for item in self._text("math_keywords", "\n".join(DEFAULT_MATH_KEYWORDS)).splitlines()
            if item.strip()
        ]
        if any(keyword in lowered for keyword in custom_keywords):
            return True

        return any(re.search(pattern, candidate, re.IGNORECASE | re.DOTALL) for pattern in MATH_SIGNAL_PATTERNS)

    def _looks_like_geometry(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False

        lowered = candidate.lower()
        custom_keywords = [
            item.strip().lower()
            for item in self._text("geometry_keywords", "\n".join(DEFAULT_GEOMETRY_KEYWORDS)).splitlines()
            if item.strip()
        ]
        if any(keyword in lowered for keyword in custom_keywords):
            return True

        return any(
            re.search(pattern, candidate, re.IGNORECASE)
            for pattern in (
                r"[△∠⊥∥]",
                r"(圆|半圆|弧|切线|弦|半径|直径|三角形|四边形|平行|垂直|中点|角平分线)",
                r"(triangle|circle|angle|perpendicular|parallel|geometry)",
            )
        )

    def _looks_like_plot(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False

        lowered = candidate.lower()
        custom_keywords = [
            item.strip().lower()
            for item in self._text("plot_keywords", "\n".join(DEFAULT_PLOT_KEYWORDS)).splitlines()
            if item.strip()
        ]
        if any(keyword in lowered for keyword in custom_keywords):
            return True

        return any(
            re.search(pattern, candidate, re.IGNORECASE)
            for pattern in (
                r"(plot|graph|draw).{0,24}(function|curve|surface|vector)",
                r"(function|curve|surface|polar|parametric|vector field).{0,24}(plot|graph)",
                r"\by\s*=\s*[A-Za-z0-9_\\+\-*/^().]+",
                r"\bz\s*=\s*[A-Za-z0-9_\\+\-*/^().]+",
            )
        )

    def _looks_like_implicit_plot(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False
        if "=" in candidate:
            return True
        return bool(re.search(r"(?<![A-Za-z])y(?![A-Za-z])", candidate))

    def _looks_like_math_image_request(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False
        if self._looks_like_math(candidate) or self._looks_like_geometry(candidate):
            return True

        lowered = candidate.lower()
        if any(keyword in lowered for keyword in IMAGE_MATH_INTENT_KEYWORDS):
            return True

        return any(
            re.search(pattern, candidate, re.IGNORECASE)
            for pattern in (
                r"(这|这个|这道).{0,4}题",
                r"(怎么|如何).{0,4}(做|解|求|证)",
                r"(帮我|麻烦).{0,4}(做|解|算|讲|分析)",
                r"(求解|解答|讲解|思路|过程|答案|证明|求证)",
            )
        )

    def _request_has_image(self, event: AstrMessageEvent, req: ProviderRequest) -> bool:
        if getattr(req, "image_urls", None):
            return True

        try:
            return any(isinstance(component, Image) for component in event.get_messages())
        except Exception as exc:
            self._debug("failed to inspect message images: %s", exc)
            return False

    def _parse_geometry_scene_json(self, raw: str) -> dict[str, Any] | None:
        text = (raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid geometry_scene_json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("geometry_scene_json must decode to a JSON object.")
        return parsed

    def _parse_plot_spec_json(self, raw: str) -> dict[str, Any] | None:
        text = (raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid plot_spec_json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("plot_spec_json must decode to a JSON object.")
        return parsed

    async def _materialize_plot_for_card(self, content: SolutionCardContent) -> SolutionCardContent:
        if not self._bool("plot_in_solution_card_enabled", True):
            return content
        if not content.plot_spec or content.plot_image_path:
            return content

        try:
            result = self._render_plot_spec(content.plot_spec)
        except Exception as exc:
            logger.exception("math_render solution-card plot render failed spec=%s", content.plot_spec)
            self._debug("solution-card plot render failed: %s", exc)
            return content

        content.plot_image_path = str(result.path)
        if not (content.plot_caption or "").strip() and self._bool("plot_auto_caption_enabled", True):
            content.plot_caption = result.description
        self._debug("solution-card plot materialized path=%s description=%s", result.path, result.description)
        return content

    def _render_plot_spec(self, spec: dict[str, Any]) -> PlotResult:
        kind = self._plot_spec_text(spec, "kind", "type", "plot_type").lower().replace("-", "_")
        kind_aliases = {
            "single": "function",
            "functions": "multiple",
            "comparison": "multiple",
            "implicit_equation": "implicit",
            "polar_curve": "polar",
            "parametric_curve": "parametric",
            "surface3d": "surface",
            "3d_surface": "surface",
            "3d_function": "surface",
            "function3d": "surface",
            "surfaces": "multiple_surfaces",
            "multiple_surface": "multiple_surfaces",
            "surface_multiple": "multiple_surfaces",
            "multiple_3d": "multiple_surfaces",
            "3d_multiple": "multiple_surfaces",
            "plot_3d_multiple": "multiple_surfaces",
            "spherical3d": "spherical",
            "spherical_surface": "spherical",
            "3d_spherical": "spherical",
            "plot_3d_spherical": "spherical",
            "implicit_3d": "implicit3d",
            "3d_implicit": "implicit3d",
            "implicit_surface": "implicit3d",
            "plot_implicit_3d": "implicit3d",
            "parametric_3d": "parametric3d",
            "3d_parametric": "parametric3d",
            "vector_field": "vector_field_2d",
            "vector2d": "vector_field_2d",
            "vector_3d": "vector3d",
            "3d_vector": "vector3d",
            "plot_vector_3d": "vector3d",
        }
        kind = kind_aliases.get(kind, kind)
        if not kind:
            kind = self._infer_plot_kind(spec)

        expression = self._plot_spec_text(spec, "expression", "equation", "expr", "formula", "radius_expression", "r_expression", "r")
        title = self._plot_spec_text(spec, "title")
        xlabel = self._plot_spec_text(spec, "xlabel", "x_label")
        ylabel = self._plot_spec_text(spec, "ylabel", "y_label")
        zlabel = self._plot_spec_text(spec, "zlabel", "z_label")
        x_range = self._plot_spec_text(spec, "x_range", "xrange")
        y_range = self._plot_spec_text(spec, "y_range", "yrange")
        z_range = self._plot_spec_text(spec, "z_range", "zrange")
        t_range = self._plot_spec_text(spec, "t_range", "trange")
        theta_range = self._plot_spec_text(spec, "theta_range", "thetarange")
        phi_range = self._plot_spec_text(spec, "phi_range", "phirange")
        parametric_3d_parts = self._parse_3d_parametric_equations(expression)

        if kind == "function":
            expression = self._strip_equation_lhs(expression, allowed_lhs=("y", "f(x)"))
            return self.plotter.plot_function(
                expression,
                x_range=x_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        if kind == "multiple":
            expressions = self._plot_spec_expressions(spec)
            return self.plotter.plot_multiple(
                expressions,
                x_range=x_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        if kind == "implicit":
            return self.plotter.plot_implicit(
                expression,
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        if kind == "polar":
            return self.plotter.plot_polar(
                expression,
                theta_range=theta_range,
                title=title,
            )
        if kind == "parametric":
            return self.plotter.plot_parametric(
                self._strip_equation_lhs(self._plot_spec_text(spec, "x_expression", "x_expr", "x"), allowed_lhs=("x", "x(t)")),
                self._strip_equation_lhs(self._plot_spec_text(spec, "y_expression", "y_expr", "y"), allowed_lhs=("y", "y(t)")),
                t_range=t_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        if kind == "surface":
            expression = self._strip_equation_lhs(expression, allowed_lhs=("z", "z(x,y)", "f(x,y)"))
            return self.plotter.plot_surface(
                expression,
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        if kind == "multiple_surfaces":
            return self.plotter.plot_multiple_surfaces(
                self._plot_spec_expressions(spec),
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        if kind == "spherical":
            return self.plotter.plot_spherical_3d(
                self._strip_equation_lhs(expression, allowed_lhs=("r", "r(theta,phi)", "r(θ,φ)")),
                theta_range=theta_range,
                phi_range=phi_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        if kind == "implicit3d":
            return self.plotter.plot_implicit_3d(
                expression,
                x_range=x_range,
                y_range=y_range,
                z_range=z_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        if kind == "parametric3d":
            x_expression = self._strip_equation_lhs(self._plot_spec_text(spec, "x_expression", "x_expr", "x"), allowed_lhs=("x", "x(t)"))
            y_expression = self._strip_equation_lhs(self._plot_spec_text(spec, "y_expression", "y_expr", "y"), allowed_lhs=("y", "y(t)"))
            z_expression = self._strip_equation_lhs(self._plot_spec_text(spec, "z_expression", "z_expr", "z"), allowed_lhs=("z", "z(t)"))
            if parametric_3d_parts:
                x_expression = x_expression or parametric_3d_parts["x"]
                y_expression = y_expression or parametric_3d_parts["y"]
                z_expression = z_expression or parametric_3d_parts["z"]
            return self.plotter.plot_parametric_3d(
                x_expression,
                y_expression,
                z_expression,
                t_range=t_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )
        if kind == "vector_field_2d":
            return self.plotter.plot_vector_field_2d(
                self._plot_spec_text(spec, "x_expression", "fx", "u", "dx"),
                self._plot_spec_text(spec, "y_expression", "fy", "v", "dy"),
                x_range=x_range,
                y_range=y_range,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
        if kind == "vector3d":
            return self.plotter.plot_vectors_3d(
                self._plot_spec_vectors(spec),
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
                zlabel=zlabel,
            )

        raise ValueError(f"Unsupported plot_spec kind: {kind or '<empty>'}")

    def _infer_plot_kind(self, spec: dict[str, Any]) -> str:
        if spec.get("vectors"):
            return "vector3d"
        if spec.get("expressions"):
            return "multiple"
        if spec.get("phi_range") or spec.get("phirange"):
            return "spherical"
        if spec.get("z_expression") or spec.get("z_expr"):
            return "parametric3d"
        if (spec.get("x_expression") or spec.get("x_expr")) and (spec.get("y_expression") or spec.get("y_expr")):
            return "parametric"
        expression = self._plot_spec_text(spec, "expression", "equation", "expr", "formula", "radius_expression", "r_expression", "r")
        if self._parse_3d_parametric_equations(expression):
            return "parametric3d"
        if re.search(r"(?<![A-Za-z])z(?![A-Za-z])", expression) and "=" in expression:
            return "implicit3d"
        if "theta" in expression and "phi" in expression:
            return "spherical"
        if "theta" in expression or spec.get("theta_range"):
            return "polar"
        if "=" in expression and not re.match(r"^\s*y\s*=", expression, re.IGNORECASE):
            return "implicit"
        return "function"

    def _plot_spec_text(self, spec: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = spec.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                return ", ".join(str(item).strip() for item in value if str(item).strip())
            text = str(value).strip()
            if text:
                return text
        return ""

    def _plot_spec_expressions(self, spec: dict[str, Any]) -> str:
        expressions = spec.get("expressions")
        if isinstance(expressions, (list, tuple)):
            return ", ".join(str(item).strip() for item in expressions if str(item).strip())
        if expressions is not None:
            return str(expressions).strip()
        return self._plot_spec_text(spec, "expression", "equation", "expr", "formula")

    def _plot_spec_vectors(self, spec: dict[str, Any]) -> str:
        vectors = spec.get("vectors")
        if isinstance(vectors, (list, tuple)):
            return "; ".join(str(item).strip() for item in vectors if str(item).strip())
        if vectors is not None:
            return str(vectors).strip()
        return self._plot_spec_text(spec, "expression", "equation", "expr", "formula")

    def _parse_3d_parametric_equations(self, text: str) -> dict[str, str] | None:
        candidate = (text or "").strip()
        if not candidate:
            return None

        parts: dict[str, str] = {}
        for piece in re.split(r"[,;，；\n]+", candidate):
            match = re.match(r"^\s*([xyz])\s*(?:\([^)]*\))?\s*=\s*(.+?)\s*$", piece, re.IGNORECASE)
            if not match:
                continue
            axis = match.group(1).lower()
            expression = match.group(2).strip()
            if expression:
                parts[axis] = expression

        if {"x", "y", "z"} <= parts.keys() and any(
            re.search(r"(?<![A-Za-z])t(?![A-Za-z])", value, re.IGNORECASE) for value in parts.values()
        ):
            return parts
        return None

    def _strip_equation_lhs(self, expression: str, *, allowed_lhs: tuple[str, ...]) -> str:
        text = (expression or "").strip()
        if "=" not in text:
            return text
        lhs, rhs = text.split("=", 1)
        lhs = lhs.strip().replace(" ", "").lower()
        normalized_allowed = {item.replace(" ", "").lower() for item in allowed_lhs}
        if lhs in normalized_allowed:
            return rhs.strip()
        return text

    def _extract_payload(self, message: str, commands: tuple[str, ...]) -> str:
        raw = (message or "").strip()
        if not raw:
            return ""

        normalized_commands = sorted(commands, key=len, reverse=True)
        for command_name in normalized_commands:
            for prefix in ("", "/", "!", "#"):
                token = f"{prefix}{command_name}"
                if raw == token:
                    return ""
                if raw.startswith(token + " "):
                    return raw[len(token) :].strip()
                if raw.startswith(token + "\n"):
                    return raw[len(token) :].strip()
        return raw

    def _debug(self, message: str, *args: Any) -> None:
        if self._bool("debug_logging_enabled", False):
            logger.debug("[math_render] " + message, *args)

    def _text(self, key: str, default: str) -> str:
        value = get_config_value(self.config, key, default)
        return str(value).strip() if value is not None else default

    def _int(self, key: str, default: int) -> int:
        value = get_config_value(self.config, key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _bool(self, key: str, default: bool) -> bool:
        value = get_config_value(self.config, key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
