from __future__ import annotations

import json
import re
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

from .conversion import (
    LATEXIFY_SYSTEM_PROMPT,
    LatexConversionResult,
    build_latexify_prompt,
    is_likely_latex,
    locally_convert_expression_to_latex,
    normalize_latex_output,
)
from .rendering import DEFAULT_STYLE, MathRenderService, PLUGIN_NAME, SolutionCardContent
from .plotting import MathPlotService
from .solving import SOLVER_SYSTEM_PROMPT, build_solver_prompt, parse_solver_response


FORMULA_COMMANDS = (
    "lateximg",
    "latex2img",
    "exprimg",
    "expr2img",
    "????",
    "latex??",
    "?????",
    "????",
)
SOLVE_COMMANDS = ("mathsolveimg", "????", "????", "????")
CLEANUP_COMMANDS = ("mathimgcleanup", "????", "????")
PLOT_COMMANDS = ("plot", "mathplot", "functionplot", "????", "??")
PLOT3D_COMMANDS = ("plot3d", "surfaceplot", "????", "????")
POLAR_COMMANDS = ("polar", "polarplot", "?????")
PARAMETRIC_COMMANDS = ("parametric", "paramplot", "????")
VECTOR_FIELD_COMMANDS = ("vector2d", "vectorfield", "???")
PARAMETRIC3D_COMMANDS = ("parametric3d", "param3d", "??????")

MATH_SIGNAL_PATTERNS = (
    r"\\(?:frac|sqrt|sum|int|lim|begin|alpha|beta|gamma|theta|pi)\b",
    r"\$\$.*\$\$",
    r"\$[^$]+\$",
    r"[A-Za-z0-9\)\]]\s*=\s*[A-Za-z0-9\(\[]",
    r"\d+\s*[\+\-\*/??]\s*\d+",
    r"[A-Za-z]\^[A-Za-z0-9]",
)

DEFAULT_MATH_KEYWORDS = (
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "solve",
    "equation",
    "derivative",
    "integral",
    "matrix",
    "proof",
    "latex",
)

IMAGE_MATH_INTENT_KEYWORDS = (
    "??",
    "???",
    "???",
    "??",
    "??",
    "?????",
    "????",
    "????",
    "???",
    "???",
    "???",
    "???",
    "???",
    "???",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "???",
    "???",
    "solve this",
    "how to solve",
    "show steps",
    "math problem",
)

DEFAULT_GEOMETRY_KEYWORDS = (
    "??",
    "????",
    "????",
    "???",
    "???",
    "?",
    "??",
    "?",
    "??",
    "?",
    "??",
    "??",
    "??",
    "??",
    "??",
    "????",
    "??",
    "??",
    "???",
    "geometry",
    "triangle",
    "circle",
    "angle",
    "polygon",
    "perpendicular",
    "parallel",
)

DEFAULT_PLOT_KEYWORDS = (
    "plot",
    "graph",
    "curve",
    "surface",
    "polar",
    "parametric",
    "vector field",
    "function graph",
    "function plot",
)

PLOT_TOOL_AWARENESS_PROMPT = """When the user asks to draw or compare math functions, curves, implicit equations, polar curves, parametric curves, 3D surfaces, or 2D vector fields, you can call the plotting tools from this plugin.

Available plotting tools:
- `plot_function`: draw one-variable functions y=f(x).
- `plot_multiple`: compare multiple one-variable functions in one coordinate system.
- `plot_implicit`: draw implicit equations F(x,y)=0.
- `plot_polar`: draw polar curves r=f(theta).
- `plot_parametric`: draw 2D parametric curves x=f(t), y=g(t).
- `plot_3d_function`: draw 3D surfaces z=f(x,y).
- `plot_3d_parametric`: draw 3D parametric curves x=f(t), y=g(t), z=h(t).
- `plot_vector_field_2d`: draw 2D vector fields F=(Fx(x,y), Fy(x,y)).

Use formula or solution-card rendering for normal formula display or step-by-step answers. Use plotting tools when the user explicitly wants a graph, curve, surface, or vector field."""

AUTO_RENDER_PROMPT = """???????????????
1. `render_math_solution_card`?????????????????????????
2. `render_latex_formula`???? LaTeX ???????????????????????????

?????????????????????????????????????????????
??????????
- ???????????????????????????
- ??????????????????????

?????
- ???????????`style_hint` ?? paper?notebook?blackboard?aurora?????????????
- ??????????????????????????????????
- ???????????????????????"""

IMAGE_MATH_TOOL_AWARENESS_PROMPT = """??????????????
??????????????????????????????????????????????????????
- `render_math_solution_card`?????????????????????????
- `render_latex_formula`??????????????????????????????
???????????????????????????????"""

IMAGE_MATH_AUTO_RENDER_PROMPT = """???????????????????????????????
????????
- ??????????????????
- ?????????????????????????????? `render_math_solution_card` ?????????
- ???????????????????????? `render_latex_formula`?
- ???????? Python ????????????????????????????????????????????????????????????
- ????????????????????????????????????????"""

PRE_REPLY_SYSTEM_PROMPT = """?? AstrBot ????????????????????????????????????????????????
???
1. ?????????????????
2. ???? Markdown????????
3. ?????????????????????????????
4. ???????????????????????????????"""

DEFAULT_FREE_LAYOUT_MARKDOWN_PROMPT = """????????????????????????????????? / ???? / ?? / ????????????????
- ? `layout_mode` ?? `free`
- ??????? `markdown_content`
- `markdown_content` ???? Markdown ???????????????????? `$...$` ? `$$...$$` ????
- ???????????????????????????????
- ???????????????????????????? `structured` ??"""


GEOMETRY_TOOL_AWARENESS_PROMPT = """??????????????????????????????????????
- `render_math_solution_card` ???????????? `geometry_scene_json`
- `geometry_scene_json` ????? JSON ?????????????
- ?????????????????????????
- ???????????????????????????????????
- ???????????????????????????????????"""

IMAGE_GEOMETRY_AUTO_RENDER_PROMPT = """???????????????????????????????????????????????????????
- ?????????????
- ??????????????????? `render_math_solution_card`
- ??????? `geometry_scene_json`??????????????????????????
- ????????????????????????????
- ??????????????????????????????????????????"""


GEOMETRY_SCHEMA_REMINDER_PROMPT = """When you provide `geometry_scene_json` or `geometry_scene`, return a plain JSON object using supported keys such as `points`, `segments`, `lines`, `rays`, `circles`, `polygons`, `angle_marks`, and `annotations`.
Do not invent a custom DSL like `{ "type": "GeometryScene", "setup": [...] }`.
Prefer the canonical field names: point `name`, segment/angle `from` + `to`, circle `orientation`, and numeric `offset` for label placement.
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
        alias=["latex2img", "exprimg", "expr2img", "????", "latex??", "?????", "????"],
    )
    async def lateximg(self, event: AstrMessageEvent):
        formula = self._extract_payload(event.message_str, FORMULA_COMMANDS)
        if not formula:
            yield event.plain_result(
                "??: /lateximg <LaTeX ??????????>\n"
                "??1: /lateximg \\int_0^1 x^2\\,dx = \\frac{1}{3}\n"
                "??2: /lateximg 1/2"
            )
            return

        try:
            await self._maybe_send_pre_reply(event, scene="formula", trigger="manual", original_text=formula)
            converted = await self._prepare_formula_for_render(event, formula)
            note = f"? AstrBot Math Render ?? ? ????: {converted.method}"
            image_path = await self.renderer.render_formula_card(
                formula=converted.latex,
                title="??????",
                note=note,
                style_hint=self._text("default_style", DEFAULT_STYLE),
                accent_color=self._text("default_accent_color", ""),
            )
        except Exception as exc:
            logger.exception("lateximg render failed")
            yield event.plain_result(f"??????: {exc}")
            return

        yield event.image_result(str(image_path))

    @filter.command("mathsolveimg", alias=["????", "????", "????"])
    async def mathsolveimg(self, event: AstrMessageEvent):
        question = self._extract_payload(event.message_str, SOLVE_COMMANDS)
        if not question:
            yield event.plain_result(
                "??: /mathsolveimg <????>\n"
                "??: /mathsolveimg ?????? x^2 - 5x + 6 = 0"
            )
            return

        try:
            await self._maybe_send_pre_reply(event, scene="solution", trigger="manual", original_text=question)
            content = await self._solve_question(event, question)
            image_path = await self.renderer.render_solution_card(content)
        except Exception as exc:
            logger.exception("mathsolveimg render failed")
            yield event.plain_result(f"??????: {exc}")
            return

        yield event.image_result(str(image_path))

    @filter.command("plot", alias=["mathplot", "functionplot"])
    async def plot(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PLOT_COMMANDS)
        if not payload:
            yield event.plain_result(
                "??: /plot <???>\n"
                "??: /plot sin(x)\n"
                "??: /plot sin(x), cos(x)\n"
                "??: /plot x^2 + y^2 = 1"
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
            yield event.plain_result(f"????: {exc}")
            return
        yield event.image_result(str(result.path))

    @filter.command("plot3d", alias=["surfaceplot"])
    async def plot3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PLOT3D_COMMANDS)
        if not payload:
            yield event.plain_result("??: /plot3d <z=f(x,y)>???: /plot3d sin(sqrt(x^2+y^2))")
            return
        try:
            result = self.plotter.plot_surface(payload)
        except Exception as exc:
            logger.exception("plot3d command failed")
            yield event.plain_result(f"??????: {exc}")
            return
        yield event.image_result(str(result.path))

    @filter.command("polar", alias=["polarplot"])
    async def polar(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, POLAR_COMMANDS)
        if not payload:
            yield event.plain_result("??: /polar <r=f(theta)>???: /polar sin(3*theta)")
            return
        try:
            result = self.plotter.plot_polar(payload)
        except Exception as exc:
            logger.exception("polar command failed")
            yield event.plain_result(f"???????: {exc}")
            return
        yield event.image_result(str(result.path))

    @filter.command("parametric", alias=["paramplot"])
    async def parametric(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PARAMETRIC_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) != 2:
            yield event.plain_result("??: /parametric <x(t)>, <y(t)>???: /parametric cos(t), sin(t)")
            return
        try:
            result = self.plotter.plot_parametric(parts[0], parts[1])
        except Exception as exc:
            logger.exception("parametric command failed")
            yield event.plain_result(f"????????: {exc}")
            return
        yield event.image_result(str(result.path))

    @filter.command("vector2d", alias=["vectorfield"])
    async def vector2d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, VECTOR_FIELD_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) != 2:
            yield event.plain_result("??: /vector2d <Fx(x,y)>, <Fy(x,y)>???: /vector2d -y, x")
            return
        try:
            result = self.plotter.plot_vector_field_2d(parts[0], parts[1])
        except Exception as exc:
            logger.exception("vector2d command failed")
            yield event.plain_result(f"???????: {exc}")
            return
        yield event.image_result(str(result.path))

    @filter.command("parametric3d", alias=["param3d"])
    async def parametric3d(self, event: AstrMessageEvent):
        payload = self._extract_payload(event.message_str, PARAMETRIC3D_COMMANDS)
        parts = self.plotter.split_expressions(payload)
        if len(parts) != 3:
            yield event.plain_result(
                "??: /parametric3d <x(t)>, <y(t)>, <z(t)>???: /parametric3d cos(t), sin(t), t/5"
            )
            return
        try:
            result = self.plotter.plot_parametric_3d(parts[0], parts[1], parts[2])
        except Exception as exc:
            logger.exception("parametric3d command failed")
            yield event.plain_result(f"??????????: {exc}")
            return
        yield event.image_result(str(result.path))

    @filter.command("plotstatus")
    async def plotstatus(self, event: AstrMessageEvent):
        yield event.plain_result(self.plotter.status_text())

    @filter.command("mathimgcleanup", alias=["????", "????"])
    async def mathimgcleanup(self, event: AstrMessageEvent):
        removed = await self.renderer.cleanup_temp_files(purge_all=True)
        self._debug("manual cleanup removed=%s", removed)
        yield event.plain_result(f"??? {removed} ????????")

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
            final_note = f"? AstrBot Math Render ?? ? ????: {converted.method}"
        image_path = await self.renderer.render_formula_card(
            formula=converted.latex,
            title=title.strip() or "??????",
            note=final_note,
            style_hint=style_hint or self._text("default_style", DEFAULT_STYLE),
            accent_color=accent_color or self._text("default_accent_color", ""),
        )
        self._debug("llm tool render_latex_formula sent image=%s", image_path)
        yield event.image_result(str(image_path))
        yield "The rendered math formula image has been sent to the user. Keep any follow-up text brief."

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
            markdown_content(string): Optional Markdown body used when free layout is desired. Supports headings, lists, emphasis, tables, and LaTeX math.
            geometry_scene_json(string): Optional geometry scene JSON string for triangles, circles, auxiliary lines, angle marks, and point-relation diagrams.
            geometry_caption(string): Optional caption shown below the geometry diagram.
            geometry_position(string): Optional geometry placement hint such as `before_content`, `after_question`, `after_key_formula`, `before_answer`, `after_answer`, `after_steps`, `after_final_answer`, or `after_content`.
        """
        question = question.strip()
        answer = answer.strip()
        key_formula = key_formula.strip()
        layout_mode = layout_mode.strip()
        markdown_content = markdown_content.strip()
        geometry_scene_json = geometry_scene_json.strip()
        geometry_caption = geometry_caption.strip()
        geometry_position = geometry_position.strip()

        if not any([question, answer, key_formula, markdown_content, geometry_scene_json]):
            raise ValueError(
                "At least one of question, answer, key_formula, markdown_content, or geometry_scene_json must be provided."
            )

        preview_text = question or answer or markdown_content or key_formula or geometry_caption or geometry_scene_json
        await self._maybe_send_pre_reply(event, scene="solution", trigger="tool", original_text=preview_text)
        content = SolutionCardContent(
            question=question,
            answer=answer,
            title=title.strip() or "????",
            key_formula=key_formula,
            style_hint=style_hint or self._text("default_style", DEFAULT_STYLE),
            accent_color=accent_color or self._text("default_accent_color", ""),
            layout_mode=layout_mode,
            markdown_content=markdown_content,
            geometry_scene=self._parse_geometry_scene_json(geometry_scene_json),
            geometry_caption=geometry_caption,
            geometry_position=geometry_position,
        )
        image_path = await self.renderer.render_solution_card(content)
        self._debug("llm tool render_math_solution_card sent image=%s", image_path)
        yield event.image_result(str(image_path))
        yield "The rendered math solution card has been sent to the user. Keep follow-up text concise and avoid repeating the full answer."

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
        yield event.image_result(str(result.path))
        yield result.description

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
        yield event.image_result(str(result.path))
        yield result.description

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
        yield event.image_result(str(result.path))
        yield result.description

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
        yield event.image_result(str(result.path))
        yield result.description

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
        yield event.image_result(str(result.path))
        yield result.description

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

        Args:
            expression(string): Surface expression in x and y, for example sin(sqrt(x**2+y**2)).
            x_range(string): Optional x range as "min,max".
            y_range(string): Optional y range as "min,max".
            title(string): Optional plot title.
            xlabel(string): Optional x-axis label.
            ylabel(string): Optional y-axis label.
            zlabel(string): Optional z-axis label.
        """
        try:
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
        yield event.image_result(str(result.path))
        yield result.description

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
        yield event.image_result(str(result.path))
        yield result.description

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
        yield event.image_result(str(result.path))
        yield result.description

    async def _solve_question(self, event: AstrMessageEvent, question: str) -> SolutionCardContent:
        provider_id = await self._get_current_provider_id(event)
        if not provider_id:
            raise RuntimeError("????????? Chat Provider?")

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
            raise RuntimeError("???????")
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
                    raise RuntimeError(f"?????? LaTeX ??: {exc}") from exc

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
                    raise RuntimeError(f"LLM ???? LaTeX ??: {exc}") from exc

        joined = "?".join(errors) if errors else "????????? LaTeX ??"
        raise RuntimeError(f"???? LaTeX ???{joined}")

    async def _llm_convert_expression_to_latex(
        self,
        event: AstrMessageEvent,
        expression: str,
    ) -> LatexConversionResult:
        provider_id = await self._get_current_provider_id(event)
        if not provider_id:
            raise RuntimeError("????????? Chat Provider?")

        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=build_latexify_prompt(expression),
            system_prompt=LATEXIFY_SYSTEM_PROMPT,
        )
        latex = normalize_latex_output(response.completion_text or "")
        if not latex:
            raise RuntimeError("LLM ??????? LaTeX ???")
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
            raise RuntimeError("????????? Chat Provider?")

        persona_prompt = await self._resolve_persona_prompt(event)
        system_prompt = self._text("pre_reply_system_prompt", PRE_REPLY_SYSTEM_PROMPT)
        if persona_prompt:
            system_prompt = f"{persona_prompt}\n\n{system_prompt}"

        scene_name = "????" if scene == "formula" else "????"
        prompt = self._apply_prompt_template(
            self._text(
                "pre_reply_user_prompt",
                "???{{scene_name}}\n???????{{original_text}}\n?????????????????????????????????",
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
            raise RuntimeError("LLM ??????")
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

    def _apply_prompt_template(self, template: str, **values: str) -> str:
        rendered = template or ""
        for key, value in values.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value or "")
        return rendered.strip()

    def _fallback_pre_reply(self, scene: str) -> str:
        if scene == "formula":
            return self._text("pre_reply_fallback_text_formula", "?????????????????????")
        return self._text("pre_reply_fallback_text_solution", "??????????????????")

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
                r"[????]",
                r"(?|??|?|??|?|??|??|???|???|??|??|??|????)",
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
                r"(?|??|??).{0,4}?",
                r"(??|??).{0,4}(?|?|?|?)",
                r"(??|??).{0,4}(?|?|?|?|??)",
                r"(??|??|??|??|??|??|??|??)",
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
        value = self.config.get(key, default)
        return str(value).strip() if value is not None else default

    def _int(self, key: str, default: int) -> int:
        value = self.config.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
