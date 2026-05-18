from __future__ import annotations

import re
from dataclasses import dataclass


INTERNAL_PROMPT_MARKER = "[MATH_RENDER_INTERNAL]"

LATEXIFY_SYSTEM_PROMPT = """你是一名数学排版助手。你的唯一任务是把用户给出的普通数学表达式转换成适合 MathJax / LaTeX 渲染的公式文本。
规则：
1. 只输出公式本身，不要解释，不要加代码块，不要加前后缀。
2. 不要输出 $$...$$、\\[...\\] 或 ```latex。
3. 分数优先转换成 \\frac{}{} 形式。
4. 保留等号、不等号、括号、函数、根号、积分、求和等数学语义。
5. 如果输入本身已经是合法 LaTeX，只做必要清理后原样输出。
6. 如果无法确定，就尽可能给出最接近原意、可被 LaTeX 渲染的表达。"""


@dataclass(frozen=True, slots=True)
class LatexConversionResult:
    latex: str
    method: str


def build_latexify_prompt(expression: str) -> str:
    return (
        f"{INTERNAL_PROMPT_MARKER}:LATEXIFY\n"
        "请把下面的数学表达式转换成 LaTeX 公式，只输出公式本身。\n"
        f"输入：{expression.strip()}"
    )


def is_likely_latex(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate:
        return False

    latex_signals = (
        "\\frac",
        "\\sqrt",
        "\\sum",
        "\\int",
        "\\lim",
        "\\begin",
        "\\alpha",
        "\\beta",
        "\\gamma",
        "\\theta",
        "\\pi",
        "\\cdot",
        "\\times",
        "\\left",
        "\\right",
        "\\mathrm",
    )
    if any(token in candidate for token in latex_signals):
        return True
    return candidate.startswith("\\") or ("{" in candidate and "}" in candidate)


def normalize_latex_output(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""

    fenced = re.fullmatch(r"```(?:latex)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    text = re.sub(r"^\s*latex\s*:\s*", "", text, flags=re.IGNORECASE)

    wrappers = [
        r"^\$\$(?P<body>.*)\$\$$",
        r"^\\\[(?P<body>.*)\\\]$",
        r"^\\\((?P<body>.*)\\\)$",
    ]
    for pattern in wrappers:
        match = re.match(pattern, text, re.DOTALL)
        if match:
            text = match.group("body").strip()
            break

    return text.strip().strip("`").strip()


def normalize_plain_expression(expression: str) -> str:
    text = (expression or "").strip()
    replacements = {
        "×": "*",
        "÷": "/",
        "－": "-",
        "–": "-",
        "—": "-",
        "〜": "~",
        "∞": "oo",
        "π": "pi",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def locally_convert_expression_to_latex(expression: str) -> LatexConversionResult | None:
    candidate = normalize_latex_output(expression)
    if not candidate:
        return None
    if is_likely_latex(candidate):
        return LatexConversionResult(candidate, "already_latex")

    normalized = normalize_plain_expression(candidate)
    if _contains_cjk(normalized):
        return None

    top_level_fraction = _split_single_top_level_fraction(normalized)
    if top_level_fraction:
        heuristic_fraction = _heuristically_convert_expression(normalized)
        if heuristic_fraction:
            return LatexConversionResult(heuristic_fraction, "heuristic_fraction")

    try:
        relation = _split_relation(normalized)
        if relation:
            left_latex = _parse_sympy_expr(relation.left)
            right_latex = _parse_sympy_expr(relation.right)
            operator = _relation_to_latex(relation.operator)
            return LatexConversionResult(
                latex=f"{left_latex} {operator} {right_latex}",
                method="sympy_relation",
            )

        latex = _parse_sympy_expr(normalized)
        return LatexConversionResult(latex, "sympy")
    except Exception:
        heuristic = _heuristically_convert_expression(normalized)
        if heuristic and heuristic != normalized:
            return LatexConversionResult(heuristic, "heuristic")
        if heuristic and _looks_like_plain_math_expression(normalized):
            return LatexConversionResult(heuristic, "plain_passthrough")
        return None


@dataclass(frozen=True, slots=True)
class RelationSplit:
    left: str
    operator: str
    right: str


def _split_relation(expression: str) -> RelationSplit | None:
    operators = ("<=", ">=", "!=", "=", "<", ">")
    for operator in operators:
        if operator not in expression:
            continue
        position = expression.find(operator)
        if position < 0:
            continue
        if operator == ">" and position > 0 and expression[position - 1] == "-":
            continue
        if operator == "<" and position + 1 < len(expression) and expression[position + 1] == "-":
            continue
        left, right = expression[:position], expression[position + len(operator) :]
        if left.strip() and right.strip():
            return RelationSplit(left=left.strip(), operator=operator, right=right.strip())
    return None


def _relation_to_latex(operator: str) -> str:
    mapping = {
        "<=": r"\le",
        ">=": r"\ge",
        "!=": r"\ne",
    }
    return mapping.get(operator, operator)


def _heuristically_convert_expression(expression: str) -> str:
    relation = _split_relation(expression)
    if relation:
        left = _heuristically_convert_fragment(relation.left)
        right = _heuristically_convert_fragment(relation.right)
        operator = _relation_to_latex(relation.operator)
        return f"{left} {operator} {right}".strip()
    return _heuristically_convert_fragment(expression)


def _heuristically_convert_fragment(expression: str) -> str:
    text = _strip_outer_wrapping_parentheses(expression.strip())
    if not text:
        return ""

    fraction = _split_single_top_level_fraction(text)
    if fraction:
        numerator, denominator = fraction
        return (
            "\\frac{"
            + _heuristically_convert_fragment(numerator)
            + "}{"
            + _heuristically_convert_fragment(denominator)
            + "}"
        )

    text = _replace_sqrt_calls(text)
    text = _replace_constants(text)
    text = _replace_named_functions(text)
    text = text.replace("->", r"\to ")
    text = re.sub(r"(?<=\S)\*(?=\S)", r" \\cdot ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_single_top_level_fraction(expression: str) -> tuple[str, str] | None:
    depth = 0
    slash_positions: list[int] = []
    has_top_level_add_sub = False
    for index, char in enumerate(expression):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            if char == "/":
                slash_positions.append(index)
            elif char in "+-" and index > 0:
                has_top_level_add_sub = True
    if len(slash_positions) != 1 or has_top_level_add_sub:
        return None

    slash_index = slash_positions[0]
    numerator = expression[:slash_index].strip()
    denominator = expression[slash_index + 1 :].strip()
    if not numerator or not denominator:
        return None
    return numerator, denominator


def _replace_sqrt_calls(expression: str) -> str:
    text = expression
    while True:
        start = text.find("sqrt(")
        if start < 0:
            return text
        open_index = start + 4
        close_index = _find_matching_bracket(text, open_index)
        if close_index < 0:
            return text
        inner = text[open_index + 1 : close_index]
        replacement = "\\sqrt{" + _heuristically_convert_fragment(inner) + "}"
        text = text[:start] + replacement + text[close_index + 1 :]


def _find_matching_bracket(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _replace_constants(expression: str) -> str:
    replacements = {
        "pi": r"\pi",
        "theta": r"\theta",
        "alpha": r"\alpha",
        "beta": r"\beta",
        "gamma": r"\gamma",
        "lambda": r"\lambda",
        "mu": r"\mu",
        "sigma": r"\sigma",
        "omega": r"\omega",
        "oo": r"\infty",
    }
    text = expression
    for source, target in replacements.items():
        text = re.sub(rf"(?<!\\)\b{source}\b", lambda _match, value=target: value, text)
    return text


def _replace_named_functions(expression: str) -> str:
    return re.sub(
        r"(?<!\\)\b(sin|cos|tan|log|ln|exp|lim|max|min)\b",
        lambda match: "\\" + match.group(1),
        expression,
    )


def _strip_outer_wrapping_parentheses(expression: str) -> str:
    text = expression.strip()
    while text.startswith("(") and text.endswith(")") and _find_matching_bracket(text, 0) == len(text) - 1:
        text = text[1:-1].strip()
    return text


def _looks_like_plain_math_expression(expression: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9\s+\-*/^_=<>(){}\[\].,:\\]+", expression))


def _parse_sympy_expr(expression: str) -> str:
    try:
        import sympy
        from sympy import acos, asin, atan, cos, exp, log, oo, pi, sin, sqrt, tan
        from sympy.parsing.sympy_parser import (
            convert_xor,
            implicit_multiplication_application,
            parse_expr,
            standard_transformations,
        )
    except ImportError as exc:
        raise RuntimeError("sympy is not installed") from exc

    cleaned = expression.strip()
    if not cleaned:
        raise ValueError("empty expression")

    local_dict = {
        "sin": sin,
        "cos": cos,
        "tan": tan,
        "asin": asin,
        "acos": acos,
        "atan": atan,
        "sqrt": sqrt,
        "log": log,
        "ln": log,
        "exp": exp,
        "pi": pi,
        "oo": oo,
        "e": sympy.E,
    }
    transformations = standard_transformations + (
        convert_xor,
        implicit_multiplication_application,
    )
    parsed = parse_expr(cleaned, local_dict=local_dict, transformations=transformations, evaluate=False)
    return sympy.latex(parsed)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))
