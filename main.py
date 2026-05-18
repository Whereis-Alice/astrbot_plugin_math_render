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


class MathRenderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or AstrBotConfig()
        self.renderer = MathRenderService(self, self.config, plugin_name=PLUGIN_NAME)

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
        is_math_text = self._looks_like_math(prompt_text)
        is_geometry_text = self._looks_like_geometry(prompt_text)
        is_image_math_request = has_image and self._looks_like_math_image_request(prompt_text)
        if not is_math_text and not is_geometry_text and not is_image_math_request and not (has_image and image_tool_prompt_enabled):
            return

        existing = req.system_prompt.strip()
        prompt_parts = [existing]
        if is_math_text or is_image_math_request:
            prompt_parts.append(AUTO_RENDER_PROMPT)
        if has_image and image_tool_prompt_enabled:
            prompt_parts.append(self._text("image_math_tool_awareness_prompt", IMAGE_MATH_TOOL_AWARENESS_PROMPT))
        if is_image_math_request:
            prompt_parts.append(self._text("image_math_auto_render_prompt", IMAGE_MATH_AUTO_RENDER_PROMPT))
        if geometry_tool_prompt_enabled and (is_geometry_text or has_image):
            prompt_parts.append(self._text("geometry_tool_awareness_prompt", GEOMETRY_TOOL_AWARENESS_PROMPT))
        if geometry_tool_prompt_enabled and has_image and self._bool("image_geometry_auto_render_prompt_enabled", True):
            prompt_parts.append(self._text("image_geometry_auto_render_prompt", IMAGE_GEOMETRY_AUTO_RENDER_PROMPT))
        if self._bool("llm_render_layout_prompt_enabled", True):
            prompt_parts.append(self._text("llm_render_layout_prompt", DEFAULT_FREE_LAYOUT_MARKDOWN_PROMPT))
        req.system_prompt = "\n\n".join(part for part in prompt_parts if part).strip()
        self._debug(
            "auto render prompt injected has_image=%s image_tool_prompt_enabled=%s geometry_tool_prompt_enabled=%s is_math_text=%s is_geometry_text=%s is_image_math_request=%s message=%r",
            has_image,
            image_tool_prompt_enabled,
            geometry_tool_prompt_enabled,
            is_math_text,
            is_geometry_text,
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

        yield event.image_result(str(image_path))

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
            image_path = await self.renderer.render_solution_card(content)
        except Exception as exc:
            logger.exception("mathsolveimg render failed")
            yield event.plain_result(f"解答出图失败: {exc}")
            return

        yield event.image_result(str(image_path))

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
        """
        question = question.strip()
        answer = answer.strip()
        key_formula = key_formula.strip()
        layout_mode = layout_mode.strip()
        markdown_content = markdown_content.strip()
        geometry_scene_json = geometry_scene_json.strip()
        geometry_caption = geometry_caption.strip()

        if not any([question, answer, key_formula, markdown_content, geometry_scene_json]):
            raise ValueError(
                "At least one of question, answer, key_formula, markdown_content, or geometry_scene_json must be provided."
            )

        preview_text = question or answer or markdown_content or key_formula or geometry_caption or geometry_scene_json
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
        )
        image_path = await self.renderer.render_solution_card(content)
        self._debug("llm tool render_math_solution_card sent image=%s", image_path)
        yield event.image_result(str(image_path))
        yield "The rendered math solution card has been sent to the user. Keep follow-up text concise and avoid repeating the full answer."

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
