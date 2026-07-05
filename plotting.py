from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import sympy as sp
from matplotlib import font_manager
from sympy import SympifyError, lambdify, latex, symbols, sympify

try:
    from .config_utils import get_config_value
except ImportError:  # pragma: no cover
    from config_utils import get_config_value


PLOT_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\s+\-*/^().,=<>|:]+$")
PLOT_BLOCKED_TOKENS = (
    "__",
    "import",
    "lambda",
    "exec",
    "eval",
    "open",
    "read",
    "write",
    "globals",
    "locals",
    "getattr",
    "setattr",
)


@dataclass(frozen=True)
class PlotResult:
    path: Path
    description: str


class MathPlotService:
    """Local matplotlib plotting service used by the AstrBot entrypoint."""

    def __init__(
        self,
        config: dict[str, Any] | None,
        temp_dir: Path,
        debug: Callable[[str, Any], None] | None = None,
    ) -> None:
        self._config = config or {}
        self._temp_dir = Path(temp_dir)
        self._debug = debug or (lambda *_args, **_kwargs: None)
        self._configure_fonts()

    @property
    def temp_dir(self) -> Path:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        return self._temp_dir

    def plot_function(
        self,
        expression: str,
        *,
        x_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        expr = self._parse_expr(expression, variables=("x",))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_x_range", "-10,10"))
        x_vals = np.linspace(x_min, x_max, self._int("plot_sample_points", 2000))
        y_vals = self._evaluate_1d(expr, x_vals, variable=symbols("x"))
        x_vals, y_vals = self._finite_pair(x_vals, y_vals)
        if len(x_vals) == 0:
            raise ValueError(f"Expression has no finite values on [{x_min}, {x_max}].")

        render_key = self._cache_key("plot_function", expression, x_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_function_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制函数 y = {latex(expr)}，x 范围 [{x_min}, {x_max}]。")

        fig, ax = self._make_2d_figure()
        ax.plot(
            x_vals,
            y_vals,
            linewidth=self._float("plot_line_width", 2.0),
            color=self._text("plot_primary_color", "#2563EB"),
            label=f"$y = {latex(expr)}$",
        )
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.legend(fontsize=10)
        ax.set_title(title or f"$y = {latex(expr)}$", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制函数 y = {latex(expr)}，x 范围 [{x_min}, {x_max}]。")

    def plot_multiple(
        self,
        expressions: str,
        *,
        x_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        expr_texts = self.split_expressions(expressions)
        if len(expr_texts) < 2:
            raise ValueError("Please provide at least two comma-separated expressions.")
        max_count = self._int("plot_max_functions", 6)
        if len(expr_texts) > max_count:
            raise ValueError(f"At most {max_count} functions can be plotted together.")

        parsed = [self._parse_expr(item, variables=("x",)) for item in expr_texts]
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_x_range", "-10,10"))
        x_vals = np.linspace(x_min, x_max, self._int("plot_sample_points", 2000))

        render_key = self._cache_key("plot_multiple", expressions, x_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_multiple_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制 {len(parsed)} 条函数曲线，x 范围 [{x_min}, {x_max}]。")

        fig, ax = self._make_2d_figure()
        colors = self._plot_colors()
        plotted = 0
        for index, expr in enumerate(parsed):
            y_vals = self._evaluate_1d(expr, x_vals, variable=symbols("x"))
            xs, ys = self._finite_pair(x_vals, y_vals)
            if len(xs) == 0:
                continue
            ax.plot(
                xs,
                ys,
                linewidth=self._float("plot_line_width", 2.0),
                color=colors[index % len(colors)],
                label=f"$y = {latex(expr)}$",
            )
            plotted += 1
        if plotted == 0:
            plt.close(fig)
            raise ValueError("No expression produced finite values in the requested range.")

        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.legend(fontsize=10)
        ax.set_title(title or "Function comparison", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制 {plotted} 条函数曲线，x 范围 [{x_min}, {x_max}]。")

    def plot_implicit(
        self,
        equation: str,
        *,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        expr = self._parse_equation_as_zero(equation, variables=("x", "y"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_implicit_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._int("plot_implicit_grid_density", 420)
        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        x_grid, y_grid = np.meshgrid(xs, ys)
        func = lambdify((symbols("x"), symbols("y")), expr, "numpy")
        values = self._as_grid(func(x_grid, y_grid), x_grid.shape)
        if not np.isfinite(values).any():
            raise ValueError("Implicit equation has no finite values in the requested range.")

        render_key = self._cache_key("plot_implicit", equation, x_range, y_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_implicit_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制隐式方程 {latex(expr)} = 0。")

        fig, ax = self._make_2d_figure()
        ax.contour(
            x_grid,
            y_grid,
            values,
            levels=[0],
            colors=self._text("plot_primary_color", "#2563EB"),
            linewidths=self._float("plot_line_width", 2.0),
        )
        if self._bool("plot_implicit_show_aux_contours", True):
            ax.contour(x_grid, y_grid, values, levels=10, colors="#64748B", linewidths=0.35, alpha=0.45)
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.set_title(title or f"${latex(expr)} = 0$", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制隐式方程 {latex(expr)} = 0。")

    def plot_polar(
        self,
        expression: str,
        *,
        theta_range: str = "",
        title: str = "",
    ) -> PlotResult:
        theta = symbols("theta")
        expr = self._parse_expr(expression, variables=("theta",))
        t_min, t_max = self._parse_range(theta_range, self._text("plot_default_theta_range", "0,2*pi"))
        theta_vals = np.linspace(t_min, t_max, self._int("plot_sample_points", 2000))
        r_vals = self._evaluate_1d(expr, theta_vals, variable=theta)
        mask = np.isfinite(theta_vals) & np.isfinite(r_vals)
        theta_vals = theta_vals[mask]
        r_vals = r_vals[mask]
        if len(theta_vals) == 0:
            raise ValueError("Polar expression has no finite values in the requested range.")

        render_key = self._cache_key("plot_polar", expression, theta_range, title)
        target_path = self.temp_dir / f"plot_polar_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制极坐标曲线 r = {latex(expr)}。")

        fig = plt.figure(
            figsize=(self._float("plot_polar_figure_size_in", 8.0), self._float("plot_polar_figure_size_in", 8.0)),
            dpi=self._int("plot_dpi", 140),
            constrained_layout=True,
        )
        ax = fig.add_subplot(111, projection="polar")
        ax.plot(
            theta_vals,
            r_vals,
            linewidth=self._float("plot_line_width", 2.0),
            color=self._text("plot_polar_color", "#DB2777"),
            label=f"$r = {latex(expr)}$",
        )
        ax.grid(True, alpha=self._float("plot_grid_alpha", 0.28), linestyle="--")
        ax.legend(fontsize=10, loc="upper right")
        ax.set_title(title or f"$r = {latex(expr)}$", fontsize=14, pad=14)
        self._save_and_close(fig, target_path, tight=False)
        return PlotResult(target_path, f"已绘制极坐标曲线 r = {latex(expr)}。")

    def plot_parametric(
        self,
        x_expression: str,
        y_expression: str,
        *,
        t_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        t = symbols("t")
        expr_x = self._parse_expr(x_expression, variables=("t",))
        expr_y = self._parse_expr(y_expression, variables=("t",))
        t_min, t_max = self._parse_range(t_range, self._text("plot_default_t_range", "0,2*pi"))
        t_vals = np.linspace(t_min, t_max, self._int("plot_parametric_sample_points", 3000))
        x_vals = self._evaluate_1d(expr_x, t_vals, variable=t)
        y_vals = self._evaluate_1d(expr_y, t_vals, variable=t)
        x_vals, y_vals = self._finite_pair(x_vals, y_vals)
        if len(x_vals) == 0:
            raise ValueError("Parametric curve has no finite points in the requested range.")

        render_key = self._cache_key("plot_parametric", x_expression, y_expression, t_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_parametric_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, "已绘制二维参数曲线。")

        fig, ax = self._make_2d_figure()
        ax.plot(
            x_vals,
            y_vals,
            linewidth=self._float("plot_line_width", 2.0),
            color=self._text("plot_parametric_color", "#7C3AED"),
            label=f"$x={latex(expr_x)},\\ y={latex(expr_y)}$",
        )
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.legend(fontsize=10)
        ax.set_title(title or f"$(x,y)=({latex(expr_x)}, {latex(expr_y)})$", fontsize=14)
        ax.set_aspect("equal", adjustable="datalim")
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, "已绘制二维参数曲线。")

    def plot_surface(
        self,
        expression: str,
        *,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ) -> PlotResult:
        expr = self._parse_expr(expression, variables=("x", "y"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_3d_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._int("plot_3d_grid_density", 160)
        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        x_grid, y_grid = np.meshgrid(xs, ys)
        func = lambdify((symbols("x"), symbols("y")), expr, "numpy")
        z_grid = self._as_grid(func(x_grid, y_grid), x_grid.shape)
        z_grid[~np.isfinite(z_grid)] = np.nan
        if np.all(np.isnan(z_grid)):
            raise ValueError("Surface expression has no finite values in the requested range.")

        render_key = self._cache_key("plot_surface", expression, x_range, y_range, title, xlabel, ylabel, zlabel)
        target_path = self.temp_dir / f"plot_surface_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制三维曲面 z = {latex(expr)}。")

        fig = plt.figure(figsize=(11, 8), dpi=self._int("plot_dpi", 140), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        surface = ax.plot_surface(
            x_grid,
            y_grid,
            z_grid,
            cmap=self._text("plot_3d_cmap", "viridis"),
            alpha=self._float("plot_3d_alpha", 0.88),
            linewidth=0,
            antialiased=True,
        )
        if self._bool("plot_3d_contour_projection", True):
            z_min = float(np.nanmin(z_grid))
            ax.contour(x_grid, y_grid, z_grid, zdir="z", offset=z_min, levels=10, colors="#64748B", alpha=0.42)
        fig.colorbar(surface, ax=ax, shrink=0.58, aspect=14, label=zlabel or "z")
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.set_title(title or f"$z = {latex(expr)}$", fontsize=14)
        ax.view_init(elev=self._float("plot_3d_elev", 25), azim=self._float("plot_3d_azim", -60))
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制三维曲面 z = {latex(expr)}。")

    def plot_parametric_3d(
        self,
        x_expression: str,
        y_expression: str,
        z_expression: str,
        *,
        t_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ) -> PlotResult:
        t = symbols("t")
        expr_x = self._parse_expr(x_expression, variables=("t",))
        expr_y = self._parse_expr(y_expression, variables=("t",))
        expr_z = self._parse_expr(z_expression, variables=("t",))
        t_min, t_max = self._parse_range(t_range, self._text("plot_default_3d_t_range", "0,4*pi"))
        t_vals = np.linspace(t_min, t_max, self._int("plot_parametric_sample_points", 3000))
        x_vals = self._evaluate_1d(expr_x, t_vals, variable=t)
        y_vals = self._evaluate_1d(expr_y, t_vals, variable=t)
        z_vals = self._evaluate_1d(expr_z, t_vals, variable=t)
        mask = np.isfinite(x_vals) & np.isfinite(y_vals) & np.isfinite(z_vals)
        x_vals, y_vals, z_vals = x_vals[mask], y_vals[mask], z_vals[mask]
        if len(x_vals) == 0:
            raise ValueError("3D parametric curve has no finite points in the requested range.")

        render_key = self._cache_key(
            "plot_parametric_3d",
            x_expression,
            y_expression,
            z_expression,
            t_range,
            title,
            xlabel,
            ylabel,
            zlabel,
        )
        target_path = self.temp_dir / f"plot_parametric_3d_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, "已绘制三维参数曲线。")

        fig = plt.figure(figsize=(11, 8), dpi=self._int("plot_dpi", 140), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        ax.plot(x_vals, y_vals, z_vals, linewidth=self._float("plot_line_width", 2.0), color="#2563EB")
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.set_title(
            title or f"$(x,y,z)=({latex(expr_x)}, {latex(expr_y)}, {latex(expr_z)})$",
            fontsize=14,
        )
        ax.view_init(elev=self._float("plot_3d_elev", 25), azim=self._float("plot_3d_azim", -60))
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, "已绘制三维参数曲线。")

    def plot_vector_field_2d(
        self,
        x_expression: str,
        y_expression: str,
        *,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        expr_x = self._parse_expr(x_expression, variables=("x", "y"))
        expr_y = self._parse_expr(y_expression, variables=("x", "y"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_vector_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._int("plot_vector_field_density", 29)
        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        x_grid, y_grid = np.meshgrid(xs, ys)
        fx = lambdify((symbols("x"), symbols("y")), expr_x, "numpy")
        fy = lambdify((symbols("x"), symbols("y")), expr_y, "numpy")
        u_vals = self._as_grid(fx(x_grid, y_grid), x_grid.shape)
        v_vals = self._as_grid(fy(x_grid, y_grid), x_grid.shape)
        mask = np.isfinite(u_vals) & np.isfinite(v_vals)
        u_vals[~mask] = 0
        v_vals[~mask] = 0
        magnitude = np.sqrt(u_vals**2 + v_vals**2)
        magnitude_max = float(np.nanmax(magnitude)) if np.isfinite(magnitude).any() else 0.0
        if magnitude_max <= 0:
            raise ValueError("Vector field is zero or invalid in the requested range.")
        if self._bool("plot_vector_field_normalize", True):
            u_vals = u_vals / magnitude_max
            v_vals = v_vals / magnitude_max

        render_key = self._cache_key("plot_vector_field", x_expression, y_expression, x_range, y_range, title)
        target_path = self.temp_dir / f"plot_vector_field_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, "已绘制二维向量场。")

        fig, ax = self._make_2d_figure()
        quiver = ax.quiver(
            x_grid,
            y_grid,
            u_vals,
            v_vals,
            magnitude,
            cmap=self._text("plot_vector_field_cmap", "plasma"),
            scale=self._float("plot_vector_field_scale", 30.0),
            width=self._float("plot_vector_field_width", 0.003),
            alpha=0.86,
            pivot="mid",
        )
        fig.colorbar(quiver, ax=ax, label="|F|")
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.set_title(title or f"$F=({latex(expr_x)}, {latex(expr_y)})$", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, "已绘制二维向量场。")

    def split_expressions(self, text: str) -> list[str]:
        items: list[str] = []
        current: list[str] = []
        depth = 0
        for char in (text or "").replace("，", ","):
            if char in "([{":
                depth += 1
            elif char in ")]}" and depth > 0:
                depth -= 1
            if char == "," and depth == 0:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
                continue
            current.append(char)
        item = "".join(current).strip()
        if item:
            items.append(item)
        return items

    def status_text(self) -> str:
        files = sorted(self.temp_dir.glob("plot_*.png"))
        total_size = sum(path.stat().st_size for path in files if path.is_file())
        return (
            "Math Render plotting status\n"
            f"- plot images: {len(files)}\n"
            f"- plot cache size: {total_size / 1024:.1f} KiB\n"
            f"- dpi: {self._int('plot_dpi', 140)}\n"
            f"- default x range: {self._text('plot_default_x_range', '-10,10')}"
        )

    def _parse_equation_as_zero(self, expression: str, *, variables: tuple[str, ...]) -> sp.Expr:
        text = self._preprocess_expr(expression)
        if "=" not in text:
            return self._parse_expr(text, variables=variables)
        left, right = text.split("=", 1)
        return self._parse_expr(f"({left})-({right})", variables=variables)

    def _parse_expr(self, expression: str, *, variables: tuple[str, ...]) -> sp.Expr:
        text = self._preprocess_expr(expression)
        self._validate_expression(text)
        locals_dict = self._locals_for(variables)
        return sympify(text, locals=locals_dict)

    def _preprocess_expr(self, expression: str) -> str:
        text = (expression or "").strip()
        text = text.replace("，", ",").replace("π", "pi").replace("Π", "pi")
        text = text.replace("θ", "theta").replace("Θ", "theta")
        text = text.replace("φ", "phi").replace("Φ", "phi").replace("ϕ", "phi")
        text = text.replace("^", "**")
        text = re.sub(r"\bmax\s*\(", "Max(", text)
        text = re.sub(r"\bmin\s*\(", "Min(", text)
        return text

    def _validate_expression(self, expression: str) -> None:
        lowered = expression.lower()
        if any(token in lowered for token in PLOT_BLOCKED_TOKENS):
            raise ValueError("Expression contains unsupported tokens.")
        if not PLOT_SAFE_NAME_PATTERN.match(expression):
            raise ValueError("Expression contains unsupported characters.")

    def _locals_for(self, variables: tuple[str, ...]) -> dict[str, Any]:
        allowed: dict[str, Any] = {
            "sin": sp.sin,
            "cos": sp.cos,
            "tan": sp.tan,
            "asin": sp.asin,
            "acos": sp.acos,
            "atan": sp.atan,
            "sinh": sp.sinh,
            "cosh": sp.cosh,
            "tanh": sp.tanh,
            "exp": sp.exp,
            "log": sp.log,
            "ln": sp.log,
            "sqrt": sp.sqrt,
            "abs": sp.Abs,
            "Abs": sp.Abs,
            "Max": sp.Max,
            "Min": sp.Min,
            "Heaviside": sp.Heaviside,
            "Piecewise": sp.Piecewise,
            "sign": sp.sign,
            "floor": sp.floor,
            "ceiling": sp.ceiling,
            "pi": sp.pi,
            "E": sp.E,
            "e": sp.E,
        }
        for name in variables:
            allowed[name] = symbols(name)
        return allowed

    def _evaluate_1d(self, expr: sp.Expr, values: np.ndarray, *, variable: sp.Symbol) -> np.ndarray:
        func = lambdify(variable, expr, "numpy")
        result = func(values)
        if isinstance(result, (int, float, complex)):
            result = np.full_like(values, result, dtype=float)
        return np.asarray(result, dtype=float)

    def _finite_pair(self, x_values: np.ndarray, y_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mask = np.isfinite(x_values) & np.isfinite(y_values)
        return x_values[mask], y_values[mask]

    def _as_grid(self, value: Any, shape: tuple[int, ...]) -> np.ndarray:
        grid = np.asarray(value, dtype=float)
        if grid.shape == ():
            return np.full(shape, float(grid), dtype=float)
        if grid.shape != shape:
            return np.broadcast_to(grid, shape).astype(float)
        return grid

    def _parse_range(self, value: str, default: str) -> tuple[float, float]:
        raw = (value or default or "").strip()
        parts = self.split_expressions(raw)
        if len(parts) != 2:
            parts = [item.strip() for item in raw.split(",")]
        if len(parts) != 2:
            raise ValueError(f"Invalid range: {raw!r}. Expected 'min,max'.")
        start = float(sp.N(self._parse_expr(parts[0], variables=())))
        end = float(sp.N(self._parse_expr(parts[1], variables=())))
        if not math.isfinite(start) or not math.isfinite(end) or start >= end:
            raise ValueError(f"Invalid range: {raw!r}.")
        return start, end

    def _make_2d_figure(self) -> tuple[Any, Any]:
        fig, ax = plt.subplots(
            figsize=(self._float("plot_figure_width_in", 10.0), self._float("plot_figure_height_in", 6.0)),
            dpi=self._int("plot_dpi", 140),
            constrained_layout=True,
        )
        return fig, ax

    def _style_2d_axes(self, ax: Any, xlabel: str, ylabel: str) -> None:
        ax.grid(True, alpha=self._float("plot_grid_alpha", 0.28), linestyle="--")
        ax.axhline(y=0, color="#0F172A", linewidth=0.8, alpha=0.75)
        ax.axvline(x=0, color="#0F172A", linewidth=0.8, alpha=0.75)
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)

    def _style_3d_axes(self, ax: Any, xlabel: str, ylabel: str, zlabel: str) -> None:
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_zlabel(zlabel, fontsize=10)
        ax.grid(True, alpha=self._float("plot_grid_alpha", 0.28), linestyle="--")

    def _save_and_close(self, fig: Any, target_path: Path, *, tight: bool = True) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"dpi": self._int("plot_dpi", 140), "facecolor": "white"}
        if tight:
            kwargs["bbox_inches"] = "tight"
        fig.savefig(target_path, **kwargs)
        plt.close(fig)

    def _cached(self, target_path: Path) -> bool:
        if self._bool("enable_cache", True) and target_path.exists():
            target_path.touch()
            return True
        return False

    def _cache_key(self, *parts: Any) -> str:
        raw = repr(parts).encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()[:20]

    def _plot_colors(self) -> list[str]:
        raw = self._text("plot_palette", "")
        if raw:
            colors = [item.strip() for item in re.split(r"[,;\n]+", raw) if item.strip()]
            if colors:
                return colors
        return ["#2563EB", "#DC2626", "#16A34A", "#EA580C", "#7C3AED", "#0891B2"]

    def _configure_fonts(self) -> None:
        configured = self._text("plot_font_family", "")
        candidates = [item.strip() for item in configured.split(",") if item.strip()]
        candidates.extend(
            [
                "Noto Sans CJK SC",
                "Microsoft YaHei",
                "SimHei",
                "WenQuanYi Zen Hei",
                "DejaVu Sans",
            ]
        )
        available = {font.name for font in font_manager.fontManager.ttflist}
        chosen = next((name for name in candidates if name in available), "DejaVu Sans")
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        self._debug("plot font selected: %s", chosen)

    def _text(self, key: str, default: str) -> str:
        value = get_config_value(self._config, key, default)
        return str(value).strip() if value is not None else default

    def _int(self, key: str, default: int) -> int:
        value = get_config_value(self._config, key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _float(self, key: str, default: float) -> float:
        value = get_config_value(self._config, key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _bool(self, key: str, default: bool) -> bool:
        value = get_config_value(self._config, key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
