from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any

try:
    from .config_utils import get_config_value
    from .render_runtime import MATPLOTLIB_RENDER_LOCK
except ImportError:  # pragma: no cover
    from config_utils import get_config_value
    from render_runtime import MATPLOTLIB_RENDER_LOCK


# Heavy plotting dependencies are imported on first actual render.  Keeping
# these names module-local preserves the existing implementation/API while
# avoiding a several-second Matplotlib/SymPy import for formula-only use.
matplotlib: Any | None = None
plt: Any | None = None
np: Any | None = None
sp: Any | None = None
font_manager: Any | None = None
Normalize: Any | None = None
Patch: Any | None = None
Line3DCollection: Any | None = None
lambdify: Any | None = None
latex: Any | None = None
symbols: Any | None = None
sympify: Any | None = None


_BACKEND_LOCK = threading.Lock()
_BACKEND_READY = False


def _close_new_figures_on_error(func: Callable[..., Any]) -> Callable[..., Any]:
    """Close figures created by a plot operation when rendering fails.

    Matplotlib keeps figures alive globally.  A validation or save error after
    ``plt.figure`` would otherwise accumulate those objects until the process
    exits, which is particularly costly for repeated LLM tool calls.
    """

    @wraps(func)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with MATPLOTLIB_RENDER_LOCK:
            before: set[int] = set()
            if _BACKEND_READY and plt is not None:
                before = set(plt.get_fignums())
            try:
                return func(self, *args, **kwargs)
            except Exception:
                if _BACKEND_READY and plt is not None:
                    for number in set(plt.get_fignums()) - before:
                        plt.close(number)
                raise

    return wrapped


def _ensure_backend() -> None:
    """Load Matplotlib/NumPy/SymPy exactly once, on demand."""

    global _BACKEND_READY, matplotlib, plt, np, sp, font_manager
    global Normalize, Patch, Line3DCollection, lambdify, latex, symbols, sympify
    if _BACKEND_READY:
        return
    with _BACKEND_LOCK:
        if _BACKEND_READY:
            return
        import matplotlib as _matplotlib

        _matplotlib.use("Agg")
        import matplotlib.pyplot as _plt
        import numpy as _np
        import sympy as _sp
        from matplotlib import font_manager as _font_manager
        from matplotlib.colors import Normalize as _Normalize
        from matplotlib.patches import Patch as _Patch
        from mpl_toolkits.mplot3d.art3d import Line3DCollection as _Line3DCollection
        from sympy import lambdify as _lambdify
        from sympy import latex as _latex
        from sympy import symbols as _symbols
        from sympy import sympify as _sympify

        matplotlib = _matplotlib
        plt = _plt
        np = _np
        sp = _sp
        font_manager = _font_manager
        Normalize = _Normalize
        Patch = _Patch
        Line3DCollection = _Line3DCollection
        lambdify = _lambdify
        latex = _latex
        symbols = _symbols
        sympify = _sympify
        _BACKEND_READY = True


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

PLOT_CACHE_VERSION = "v2"
PLOT_DEFAULT_MAX_EXPRESSION_LENGTH = 1000
PLOT_DEFAULT_MAX_RANGE_SPAN = 1000.0
PLOT_DEFAULT_CACHE_MAX_FILES = 40
PLOT_DEFAULT_CACHE_MAX_MB = 64.0
PLOT_DEFAULT_MAX_VECTORS = 16
PLOT_ALLOWED_FUNCTIONS = {
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "sinh",
    "cosh",
    "tanh",
    "exp",
    "log",
    "sqrt",
    "Abs",
    "Heaviside",
    "Piecewise",
    "sign",
    "floor",
    "ceiling",
    "cot",
    "sec",
    "csc",
    "acot",
    "asec",
    "acsc",
    "atan2",
    "log10",
    "sinc",
    "factorial",
    "erf",
    "Max",
    "Min",
}


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
        self._fonts_configured = False

    @property
    def temp_dir(self) -> Path:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        return self._temp_dir

    def _ensure_ready(self) -> None:
        _ensure_backend()
        if not self._fonts_configured:
            self._configure_fonts()
            self._fonts_configured = True

    @_close_new_figures_on_error
    def plot_function(
        self,
        expression: str,
        *,
        x_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        expression = self._strip_equation_lhs(expression, ("y", "f(x)"))
        expr = self._parse_expr(expression, variables=("x",))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_x_range", "-10,10"))
        render_key = self._cache_key("plot_function", expression, x_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_function_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制函数 y = {latex(expr)}，x 范围 [{x_min}, {x_max}]。")

        x_vals = np.linspace(x_min, x_max, self._bounded_int("plot_sample_points", 2000, 128, 10000))
        y_vals = self._evaluate_1d(expr, x_vals, variable=symbols("x"))
        x_vals, y_vals = self._finite_pair(x_vals, y_vals)
        if len(x_vals) == 0:
            raise ValueError(f"Expression has no finite values on [{x_min}, {x_max}].")

        fig, ax = self._make_2d_figure()
        ax.plot(
            x_vals,
            y_vals,
            linewidth=self._bounded_float("plot_line_width", 2.0, 0.1, 10.0),
            color=self._text("plot_primary_color", "#2563EB"),
            label=f"$y = {latex(expr)}$",
        )
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.legend(fontsize=10)
        ax.set_title(title or f"$y = {latex(expr)}$", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制函数 y = {latex(expr)}，x 范围 [{x_min}, {x_max}]。")

    @_close_new_figures_on_error
    def plot_multiple(
        self,
        expressions: str,
        *,
        x_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        expr_texts = [self._strip_equation_lhs(item, ("y", "f(x)")) for item in self.split_expressions(expressions)]
        if len(expr_texts) < 2:
            raise ValueError("Please provide at least two comma-separated expressions.")
        max_count = self._bounded_int("plot_max_functions", 6, 2, 12)
        if len(expr_texts) > max_count:
            raise ValueError(f"At most {max_count} functions can be plotted together.")

        parsed = [self._parse_expr(item, variables=("x",)) for item in expr_texts]
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_x_range", "-10,10"))
        normalized_expressions = ", ".join(expr_texts)
        render_key = self._cache_key("plot_multiple", normalized_expressions, x_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_multiple_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制 {len(parsed)} 条函数曲线，x 范围 [{x_min}, {x_max}]。")

        x_vals = np.linspace(x_min, x_max, self._bounded_int("plot_sample_points", 2000, 128, 10000))

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
                linewidth=self._bounded_float("plot_line_width", 2.0, 0.1, 10.0),
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

    @_close_new_figures_on_error
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
        self._ensure_ready()
        expr = self._parse_equation_as_zero(equation, variables=("x", "y"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_implicit_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._bounded_int("plot_implicit_grid_density", 420, 32, 800)
        render_key = self._cache_key("plot_implicit", equation, x_range, y_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_implicit_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制隐式方程 {latex(expr)} = 0。")

        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        x_grid, y_grid = np.meshgrid(xs, ys)
        func = lambdify((symbols("x"), symbols("y")), expr, "numpy")
        values = self._as_grid(func(x_grid, y_grid), x_grid.shape)
        if not np.isfinite(values).any():
            raise ValueError("Implicit equation has no finite values in the requested range.")

        fig, ax = self._make_2d_figure()
        ax.contour(
            x_grid,
            y_grid,
            values,
            levels=[0],
            colors=self._text("plot_primary_color", "#2563EB"),
            linewidths=self._bounded_float("plot_line_width", 2.0, 0.1, 10.0),
        )
        if self._bool("plot_implicit_show_aux_contours", True):
            ax.contour(x_grid, y_grid, values, levels=10, colors="#64748B", linewidths=0.35, alpha=0.45)
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.set_title(title or f"${latex(expr)} = 0$", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制隐式方程 {latex(expr)} = 0。")

    @_close_new_figures_on_error
    def plot_polar(
        self,
        expression: str,
        *,
        theta_range: str = "",
        title: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        theta = symbols("theta")
        expression = self._strip_equation_lhs(expression, ("r", "r(theta)", "r(θ)"))
        expr = self._parse_expr(expression, variables=("theta",))
        t_min, t_max = self._parse_range(theta_range, self._text("plot_default_theta_range", "0,2*pi"))
        render_key = self._cache_key("plot_polar", expression, theta_range, title)
        target_path = self.temp_dir / f"plot_polar_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制极坐标曲线 r = {latex(expr)}。")

        theta_vals = np.linspace(t_min, t_max, self._bounded_int("plot_sample_points", 2000, 128, 10000))
        r_vals = self._evaluate_1d(expr, theta_vals, variable=theta)
        mask = np.isfinite(theta_vals) & np.isfinite(r_vals)
        theta_vals = theta_vals[mask]
        r_vals = r_vals[mask]
        if len(theta_vals) == 0:
            raise ValueError("Polar expression has no finite values in the requested range.")

        polar_size = self._bounded_float("plot_polar_figure_size_in", 8.0, 3.0, 24.0)
        fig = plt.figure(
            figsize=(polar_size, polar_size),
            dpi=self._bounded_int("plot_dpi", 140, 72, 320),
            constrained_layout=True,
        )
        ax = fig.add_subplot(111, projection="polar")
        ax.plot(
            theta_vals,
            r_vals,
            linewidth=self._bounded_float("plot_line_width", 2.0, 0.1, 10.0),
            color=self._text("plot_polar_color", "#DB2777"),
            label=f"$r = {latex(expr)}$",
        )
        ax.grid(True, alpha=self._bounded_float("plot_grid_alpha", 0.28, 0.0, 1.0), linestyle="--")
        ax.legend(fontsize=10, loc="upper right")
        ax.set_title(title or f"$r = {latex(expr)}$", fontsize=14, pad=14)
        self._save_and_close(fig, target_path, tight=False)
        return PlotResult(target_path, f"已绘制极坐标曲线 r = {latex(expr)}。")

    @_close_new_figures_on_error
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
        self._ensure_ready()
        t = symbols("t")
        x_expression = self._strip_equation_lhs(x_expression, ("x", "x(t)"))
        y_expression = self._strip_equation_lhs(y_expression, ("y", "y(t)"))
        expr_x = self._parse_expr(x_expression, variables=("t",))
        expr_y = self._parse_expr(y_expression, variables=("t",))
        t_min, t_max = self._parse_range(t_range, self._text("plot_default_t_range", "0,2*pi"))
        render_key = self._cache_key("plot_parametric", x_expression, y_expression, t_range, title, xlabel, ylabel)
        target_path = self.temp_dir / f"plot_parametric_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, "已绘制二维参数曲线。")

        t_vals = np.linspace(t_min, t_max, self._bounded_int("plot_parametric_sample_points", 3000, 128, 12000))
        x_vals = self._evaluate_1d(expr_x, t_vals, variable=t)
        y_vals = self._evaluate_1d(expr_y, t_vals, variable=t)
        x_vals, y_vals = self._finite_pair(x_vals, y_vals)
        if len(x_vals) == 0:
            raise ValueError("Parametric curve has no finite points in the requested range.")

        fig, ax = self._make_2d_figure()
        ax.plot(
            x_vals,
            y_vals,
            linewidth=self._bounded_float("plot_line_width", 2.0, 0.1, 10.0),
            color=self._text("plot_parametric_color", "#7C3AED"),
            label=f"$x={latex(expr_x)},\\ y={latex(expr_y)}$",
        )
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.legend(fontsize=10)
        ax.set_title(title or f"$(x,y)=({latex(expr_x)}, {latex(expr_y)})$", fontsize=14)
        ax.set_aspect("equal", adjustable="datalim")
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, "已绘制二维参数曲线。")

    @_close_new_figures_on_error
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
        self._ensure_ready()
        expression = self._strip_equation_lhs(expression, ("z", "z(x,y)", "f(x,y)"))
        expr = self._parse_expr(expression, variables=("x", "y"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_3d_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._bounded_int("plot_3d_grid_density", 160, 24, 320)
        render_key = self._cache_key("plot_surface", expression, x_range, y_range, title, xlabel, ylabel, zlabel)
        target_path = self.temp_dir / f"plot_surface_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制三维曲面 z = {latex(expr)}。")

        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        x_grid, y_grid = np.meshgrid(xs, ys)
        func = lambdify((symbols("x"), symbols("y")), expr, "numpy")
        z_grid = self._as_grid(func(x_grid, y_grid), x_grid.shape)
        z_grid[~np.isfinite(z_grid)] = np.nan
        if np.all(np.isnan(z_grid)):
            raise ValueError("Surface expression has no finite values in the requested range.")

        fig = plt.figure(figsize=(11, 8), dpi=self._bounded_int("plot_dpi", 140, 72, 320), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        surface = ax.plot_surface(
            x_grid,
            y_grid,
            z_grid,
            cmap=self._text("plot_3d_cmap", "viridis"),
            alpha=self._bounded_float("plot_3d_alpha", 0.88, 0.05, 1.0),
            linewidth=0,
            antialiased=True,
        )
        if self._bool("plot_3d_contour_projection", True):
            z_min = float(np.nanmin(z_grid))
            ax.contour(x_grid, y_grid, z_grid, zdir="z", offset=z_min, levels=10, colors="#64748B", alpha=0.42)
        fig.colorbar(surface, ax=ax, shrink=0.58, aspect=14, label=zlabel or "z")
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.set_title(title or f"$z = {latex(expr)}$", fontsize=14)
        ax.view_init(
            elev=self._bounded_float("plot_3d_elev", 25.0, -90.0, 90.0),
            azim=self._bounded_float("plot_3d_azim", -60.0, -360.0, 360.0),
        )
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制三维曲面 z = {latex(expr)}。")

    @_close_new_figures_on_error
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
        self._ensure_ready()
        t = symbols("t")
        x_expression = self._strip_equation_lhs(x_expression, ("x", "x(t)"))
        y_expression = self._strip_equation_lhs(y_expression, ("y", "y(t)"))
        z_expression = self._strip_equation_lhs(z_expression, ("z", "z(t)"))
        expr_x = self._parse_expr(x_expression, variables=("t",))
        expr_y = self._parse_expr(y_expression, variables=("t",))
        expr_z = self._parse_expr(z_expression, variables=("t",))
        t_min, t_max = self._parse_range(t_range, self._text("plot_default_3d_t_range", "0,4*pi"))
        cmap_name = self._text("plot_3d_parametric_cmap", "plasma") or "plasma"
        line_width = self._bounded_float("plot_line_width", 2.0, 0.1, 10.0)
        render_key = self._cache_key(
            "plot_parametric_3d",
            "gradient_t_v1",
            x_expression,
            y_expression,
            z_expression,
            t_range,
            title,
            xlabel,
            ylabel,
            zlabel,
            cmap_name,
            line_width,
        )
        target_path = self.temp_dir / f"plot_parametric_3d_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, "已绘制三维参数曲线。")

        t_vals = np.linspace(t_min, t_max, self._bounded_int("plot_parametric_sample_points", 3000, 128, 12000))
        x_vals = self._evaluate_1d(expr_x, t_vals, variable=t)
        y_vals = self._evaluate_1d(expr_y, t_vals, variable=t)
        z_vals = self._evaluate_1d(expr_z, t_vals, variable=t)
        mask = np.isfinite(x_vals) & np.isfinite(y_vals) & np.isfinite(z_vals)
        t_vals = t_vals[mask]
        x_vals, y_vals, z_vals = x_vals[mask], y_vals[mask], z_vals[mask]
        if len(x_vals) < 2:
            raise ValueError("3D parametric curve has no finite points in the requested range.")

        fig = plt.figure(figsize=(11, 8), dpi=self._bounded_int("plot_dpi", 140, 72, 320), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        points = np.column_stack((x_vals, y_vals, z_vals)).reshape(-1, 1, 3)
        segments = np.concatenate((points[:-1], points[1:]), axis=1)
        t_midpoints = (t_vals[:-1] + t_vals[1:]) / 2.0
        norm = Normalize(vmin=float(np.min(t_vals)), vmax=float(np.max(t_vals)))
        curve = Line3DCollection(
            segments,
            cmap=cmap_name,
            norm=norm,
            linewidths=line_width,
            antialiased=True,
        )
        curve.set_array(t_midpoints)
        ax.add_collection3d(curve)
        self._set_3d_data_limits(ax, x_vals, y_vals, z_vals)
        colorbar = fig.colorbar(curve, ax=ax, shrink=0.62, aspect=16, pad=0.08)
        colorbar.set_label("t")
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.set_title(
            title or f"$(x,y,z)=({latex(expr_x)}, {latex(expr_y)}, {latex(expr_z)})$",
            fontsize=14,
        )
        ax.view_init(
            elev=self._bounded_float("plot_3d_elev", 25.0, -90.0, 90.0),
            azim=self._bounded_float("plot_3d_azim", -60.0, -360.0, 360.0),
        )
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, "已绘制三维参数曲线。")

    @_close_new_figures_on_error
    def plot_spherical_3d(
        self,
        expression: str,
        *,
        theta_range: str = "",
        phi_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        theta = symbols("theta")
        phi = symbols("phi")
        expression = self._strip_equation_lhs(expression, ("r", "r(theta,phi)", "r(θ,φ)"))
        expr = self._parse_expr(expression, variables=("theta", "phi"))
        theta_min, theta_max = self._parse_range(
            theta_range,
            self._text("plot_default_spherical_theta_range", "0,pi"),
        )
        phi_min, phi_max = self._parse_range(
            phi_range,
            self._text("plot_default_spherical_phi_range", "0,2*pi"),
        )
        density = self._bounded_int("plot_3d_grid_density", 160, 24, 320)
        render_key = self._cache_key(
            "plot_spherical_3d",
            expression,
            theta_range,
            phi_range,
            title,
            xlabel,
            ylabel,
            zlabel,
        )
        target_path = self.temp_dir / f"plot_spherical_3d_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制球坐标曲面 r = {latex(expr)}。")

        theta_vals = np.linspace(theta_min, theta_max, density)
        phi_vals = np.linspace(phi_min, phi_max, density * 2)
        theta_grid, phi_grid = np.meshgrid(theta_vals, phi_vals)
        func = lambdify((theta, phi), expr, "numpy")
        radius = self._as_grid(func(theta_grid, phi_grid), theta_grid.shape)
        radius[~np.isfinite(radius)] = np.nan
        if np.all(np.isnan(radius)):
            raise ValueError("Spherical expression has no finite values in the requested range.")

        x_grid = radius * np.sin(theta_grid) * np.cos(phi_grid)
        y_grid = radius * np.sin(theta_grid) * np.sin(phi_grid)
        z_grid = radius * np.cos(theta_grid)

        fig = plt.figure(figsize=(11, 8), dpi=self._bounded_int("plot_dpi", 140, 72, 320), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        ax.plot_surface(
            x_grid,
            y_grid,
            z_grid,
            facecolors=plt.get_cmap(self._text("plot_3d_cmap", "viridis"))(
                Normalize(vmin=float(np.nanmin(radius)), vmax=float(np.nanmax(radius)))(radius)
            ),
            alpha=self._bounded_float("plot_3d_alpha", 0.88, 0.05, 1.0),
            linewidth=0,
            antialiased=True,
        )
        mappable = plt.cm.ScalarMappable(
            norm=Normalize(vmin=float(np.nanmin(radius)), vmax=float(np.nanmax(radius))),
            cmap=self._text("plot_3d_cmap", "viridis"),
        )
        mappable.set_array(radius[np.isfinite(radius)])
        fig.colorbar(mappable, ax=ax, shrink=0.58, aspect=14, label="r")
        self._set_3d_data_limits(ax, x_grid.ravel(), y_grid.ravel(), z_grid.ravel())
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.set_title(title or f"$r = {latex(expr)}$", fontsize=14)
        ax.view_init(
            elev=self._bounded_float("plot_3d_elev", 25.0, -90.0, 90.0),
            azim=self._bounded_float("plot_3d_azim", -60.0, -360.0, 360.0),
        )
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制球坐标曲面 r = {latex(expr)}。")

    @_close_new_figures_on_error
    def plot_multiple_surfaces(
        self,
        expressions: str,
        *,
        x_range: str = "",
        y_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        expr_texts = [
            self._strip_equation_lhs(item, ("z", "z(x,y)", "f(x,y)"))
            for item in self.split_expressions(expressions)
        ]
        if len(expr_texts) < 2:
            raise ValueError("Please provide at least two comma-separated 3D surface expressions.")
        max_count = self._bounded_int("plot_3d_max_surfaces", 5, 2, 8)
        if len(expr_texts) > max_count:
            raise ValueError(f"At most {max_count} 3D surfaces can be plotted together.")

        parsed = [self._parse_expr(item, variables=("x", "y")) for item in expr_texts]
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_3d_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._bounded_int("plot_3d_grid_density", 160, 24, 320)
        normalized_expressions = ", ".join(expr_texts)
        render_key = self._cache_key(
            "plot_multiple_surfaces",
            normalized_expressions,
            x_range,
            y_range,
            title,
            xlabel,
            ylabel,
            zlabel,
        )
        target_path = self.temp_dir / f"plot_multiple_surfaces_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制 {len(parsed)} 个三维曲面对比。")

        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        x_grid, y_grid = np.meshgrid(xs, ys)

        fig = plt.figure(figsize=(11, 8), dpi=self._bounded_int("plot_dpi", 140, 72, 320), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        colors = self._plot_colors()
        proxies: list[Patch] = []
        plotted = 0
        z_values: list[np.ndarray] = []
        for index, expr in enumerate(parsed):
            func = lambdify((symbols("x"), symbols("y")), expr, "numpy")
            z_grid = self._as_grid(func(x_grid, y_grid), x_grid.shape)
            z_grid[~np.isfinite(z_grid)] = np.nan
            if np.all(np.isnan(z_grid)):
                continue
            color = colors[index % len(colors)]
            ax.plot_surface(
                x_grid,
                y_grid,
                z_grid,
                color=color,
                alpha=0.76 if index == 0 else 0.54,
                linewidth=0,
                antialiased=True,
            )
            proxies.append(Patch(facecolor=color, label=f"$z={latex(expr)}$"))
            z_values.append(z_grid.ravel())
            plotted += 1
        if plotted == 0:
            plt.close(fig)
            raise ValueError("No 3D surface expression produced finite values in the requested range.")

        if z_values:
            self._set_3d_data_limits(ax, x_grid.ravel(), y_grid.ravel(), np.concatenate(z_values))
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.legend(handles=proxies, fontsize=9, loc="upper left")
        ax.set_title(title or "3D surface comparison", fontsize=14)
        ax.view_init(
            elev=self._bounded_float("plot_3d_elev", 25.0, -90.0, 90.0),
            azim=self._bounded_float("plot_3d_azim", -60.0, -360.0, 360.0),
        )
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制 {plotted} 个三维曲面对比。")

    @_close_new_figures_on_error
    def plot_implicit_3d(
        self,
        equation: str,
        *,
        x_range: str = "",
        y_range: str = "",
        z_range: str = "",
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        expr = self._parse_equation_as_zero(equation, variables=("x", "y", "z"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_implicit_3d_range", "-3,3"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        z_min, z_max = self._parse_range(z_range, f"{x_min},{x_max}")
        density = self._bounded_int("plot_implicit_3d_grid_density", 96, 16, 220)
        slices = self._bounded_int("plot_implicit_3d_slices", 48, 8, 160)
        render_key = self._cache_key("plot_implicit_3d", "z_slices_v1", equation, x_range, y_range, z_range, title, xlabel, ylabel, zlabel)
        target_path = self.temp_dir / f"plot_implicit_3d_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制隐式三维曲面 {latex(expr)} = 0。")

        xs = np.linspace(x_min, x_max, density)
        ys = np.linspace(y_min, y_max, density)
        zs = np.linspace(z_min, z_max, max(8, slices))
        x_grid, y_grid = np.meshgrid(xs, ys)
        func = lambdify((symbols("x"), symbols("y"), symbols("z")), expr, "numpy")

        fig = plt.figure(figsize=(11, 8), dpi=self._bounded_int("plot_dpi", 140, 72, 320), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        contour_count = 0
        for z_value in zs:
            z_grid = np.full_like(x_grid, z_value)
            values = self._as_grid(func(x_grid, y_grid, z_grid), x_grid.shape)
            values[~np.isfinite(values)] = np.nan
            if np.all(np.isnan(values)):
                continue
            value_min = float(np.nanmin(values))
            value_max = float(np.nanmax(values))
            if value_min > 0 or value_max < 0:
                continue
            ax.contour(
                x_grid,
                y_grid,
                values,
                levels=[0],
                zdir="z",
                offset=float(z_value),
                colors=self._text("plot_primary_color", "#2563EB"),
                linewidths=max(0.4, self._bounded_float("plot_line_width", 2.0, 0.1, 10.0) * 0.45),
                alpha=0.58,
            )
            contour_count += 1
        if contour_count == 0:
            plt.close(fig)
            raise ValueError("Implicit 3D equation has no zero-level slices in the requested range.")

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_zlim(z_min, z_max)
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.set_title(title or f"${latex(expr)} = 0$", fontsize=14)
        ax.view_init(
            elev=self._bounded_float("plot_3d_elev", 25.0, -90.0, 90.0),
            azim=self._bounded_float("plot_3d_azim", -60.0, -360.0, 360.0),
        )
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制隐式三维曲面 {latex(expr)} = 0。")

    @_close_new_figures_on_error
    def plot_vectors_3d(
        self,
        vectors: str,
        *,
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        zlabel: str = "",
    ) -> PlotResult:
        self._ensure_ready()
        vector_defs = [item.strip() for item in re.split(r"[;；\n]+", vectors or "") if item.strip()]
        if not vector_defs:
            raise ValueError("Please provide at least one 3D vector definition.")
        max_vectors = self._bounded_int("plot_max_vectors", PLOT_DEFAULT_MAX_VECTORS, 1, 64)
        if len(vector_defs) > max_vectors:
            raise ValueError(f"At most {max_vectors} 3D vectors can be plotted together.")
        parsed = [self._parse_vector_3d(item) for item in vector_defs]

        render_key = self._cache_key("plot_vectors_3d", vectors, title, xlabel, ylabel, zlabel)
        target_path = self.temp_dir / f"plot_vectors_3d_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, f"已绘制 {len(parsed)} 个三维向量。")

        fig = plt.figure(figsize=(11, 8), dpi=self._bounded_int("plot_dpi", 140, 72, 320), facecolor="white", constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        all_x: list[float] = []
        all_y: list[float] = []
        all_z: list[float] = []
        for index, item in enumerate(parsed, start=1):
            sx, sy, sz = item["start"]
            ex, ey, ez = item["end"]
            dx, dy, dz = ex - sx, ey - sy, ez - sz
            label = item["label"] or f"v{index}"
            color = item["color"]
            ax.quiver(
                sx,
                sy,
                sz,
                dx,
                dy,
                dz,
                color=color,
                arrow_length_ratio=0.14,
                linewidth=self._bounded_float("plot_line_width", 2.0, 0.1, 10.0),
                label=label,
            )
            ax.scatter([ex], [ey], [ez], color=color, s=24, alpha=0.9)
            ax.text(ex, ey, ez, f" {label}", color=color, fontsize=9)
            all_x.extend([sx, ex])
            all_y.extend([sy, ey])
            all_z.extend([sz, ez])

        self._set_3d_data_limits(ax, np.asarray(all_x), np.asarray(all_y), np.asarray(all_z))
        self._style_3d_axes(ax, xlabel or "x", ylabel or "y", zlabel or "z")
        ax.legend(fontsize=9, loc="upper left")
        ax.set_title(title or "3D vectors", fontsize=14)
        ax.view_init(
            elev=self._bounded_float("plot_3d_elev", 25.0, -90.0, 90.0),
            azim=self._bounded_float("plot_3d_azim", -60.0, -360.0, 360.0),
        )
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, f"已绘制 {len(parsed)} 个三维向量。")

    @_close_new_figures_on_error
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
        self._ensure_ready()
        expr_x = self._parse_expr(x_expression, variables=("x", "y"))
        expr_y = self._parse_expr(y_expression, variables=("x", "y"))
        x_min, x_max = self._parse_range(x_range, self._text("plot_default_vector_range", "-5,5"))
        y_min, y_max = self._parse_range(y_range, f"{x_min},{x_max}")
        density = self._bounded_int("plot_vector_field_density", 29, 8, 100)
        render_key = self._cache_key("plot_vector_field", x_expression, y_expression, x_range, y_range, title)
        target_path = self.temp_dir / f"plot_vector_field_{render_key}.png"
        if self._cached(target_path):
            return PlotResult(target_path, "已绘制二维向量场。")

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

        fig, ax = self._make_2d_figure()
        quiver = ax.quiver(
            x_grid,
            y_grid,
            u_vals,
            v_vals,
            magnitude,
            cmap=self._text("plot_vector_field_cmap", "plasma"),
            scale=self._bounded_float("plot_vector_field_scale", 30.0, 1.0, 1000.0),
            width=self._bounded_float("plot_vector_field_width", 0.003, 0.0001, 0.05),
            alpha=0.86,
            pivot="mid",
        )
        fig.colorbar(quiver, ax=ax, label="|F|")
        self._style_2d_axes(ax, xlabel or "x", ylabel or "y")
        ax.set_title(title or f"$F=({latex(expr_x)}, {latex(expr_y)})$", fontsize=14)
        self._save_and_close(fig, target_path)
        return PlotResult(target_path, "已绘制二维向量场。")

    def split_expressions(self, text: str) -> list[str]:
        separators = {",", ";", "；", "\n"}
        items: list[str] = []
        current: list[str] = []
        depth = 0
        for char in (text or "").replace("，", ","):
            if char in "([{":
                depth += 1
            elif char in ")]}" and depth > 0:
                depth -= 1
            if char in separators and depth == 0:
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

    def _parse_vector_3d(self, raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            raise ValueError("Empty vector definition.")

        color = self._plot_colors()[0]
        label = ""
        if ":" in text:
            parts = [part.strip() for part in text.split(":")]
            text = parts[0]
            for extra in parts[1:]:
                if not extra:
                    continue
                color_value = self._parse_color(extra)
                if color_value:
                    color = color_value
                else:
                    label = extra

        if "->" in text:
            start_text, end_text = text.split("->", 1)
        else:
            start_text, end_text = "0,0,0", text
        start = self._parse_point_3d(start_text)
        end = self._parse_point_3d(end_text)
        if all(math.isclose(a, b) for a, b in zip(start, end)):
            raise ValueError(f"Zero-length 3D vector: {raw!r}.")
        return {"start": start, "end": end, "color": color, "label": label}

    def _parse_point_3d(self, raw: str) -> tuple[float, float, float]:
        text = (raw or "").strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        parts = self.split_expressions(text)
        if len(parts) != 3:
            raise ValueError(f"Expected a 3D point 'x,y,z', got {raw!r}.")
        values = [float(sp.N(self._parse_expr(part, variables=()))) for part in parts]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Point contains non-finite coordinates: {raw!r}.")
        return values[0], values[1], values[2]

    def _parse_color(self, raw: str) -> str:
        text = (raw or "").strip()
        named = {
            "红": "#F44336",
            "red": "#F44336",
            "蓝": "#2196F3",
            "blue": "#2196F3",
            "绿": "#4CAF50",
            "green": "#4CAF50",
            "橙": "#FF9800",
            "orange": "#FF9800",
            "紫": "#9C27B0",
            "purple": "#9C27B0",
            "灰": "#9E9E9E",
            "gray": "#9E9E9E",
            "黑": "#000000",
            "black": "#000000",
            "青": "#06B6D4",
            "cyan": "#06B6D4",
            "黄": "#FACC15",
            "yellow": "#FACC15",
        }
        lowered = text.lower()
        if lowered in named:
            return named[lowered]
        if re.match(r"^#[0-9A-Fa-f]{6}$", text):
            return text
        if lowered in {"magenta", "brown", "pink", "lime", "navy", "teal"}:
            return lowered
        return ""

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

    def _strip_equation_lhs(self, expression: str, allowed_lhs: tuple[str, ...]) -> str:
        text = (expression or "").strip()
        if "=" not in text:
            return text
        lhs, rhs = text.split("=", 1)
        normalized_lhs = re.sub(r"\s+", "", lhs).lower()
        allowed = {re.sub(r"\s+", "", item).lower() for item in allowed_lhs}
        return rhs.strip() if normalized_lhs in allowed else text

    def _parse_expr(self, expression: str, *, variables: tuple[str, ...]) -> sp.Expr:
        self._ensure_ready()
        text = self._preprocess_expr(expression)
        max_length = self._bounded_int(
            "plot_max_expression_length",
            PLOT_DEFAULT_MAX_EXPRESSION_LENGTH,
            64,
            10_000,
        )
        if len(text) > max_length:
            raise ValueError(f"Expression is too long (maximum {max_length} characters).")
        self._validate_expression(text)
        locals_dict = self._locals_for(variables)
        try:
            parsed = sympify(text, locals=locals_dict)
        except Exception as exc:
            raise ValueError(f"Invalid mathematical expression: {exc}") from exc
        if not isinstance(parsed, sp.Expr):
            raise TypeError("Expression must evaluate to a scalar mathematical expression.")

        allowed_symbols = set(variables)
        unknown_symbols = {str(item) for item in parsed.free_symbols if str(item) not in allowed_symbols}
        if unknown_symbols:
            names = ", ".join(sorted(unknown_symbols))
            raise ValueError(f"Unknown variable(s): {names}.")

        unknown_functions = {
            getattr(item.func, "__name__", str(item.func))
            for item in parsed.atoms(sp.Function)
            if getattr(item.func, "__name__", str(item.func)) not in PLOT_ALLOWED_FUNCTIONS
        }
        if unknown_functions:
            names = ", ".join(sorted(unknown_functions))
            raise ValueError(f"Unsupported function(s): {names}.")

        max_ops = self._bounded_int("plot_max_expression_ops", 250, 16, 10_000)
        if int(sp.count_ops(parsed)) > max_ops:
            raise ValueError(f"Expression is too complex (maximum {max_ops} operations).")
        for power in parsed.atoms(sp.Pow):
            exponent = power.exp
            if exponent.is_integer and exponent.is_number:
                try:
                    if abs(int(exponent)) > self._bounded_int("plot_max_power", 1000, 8, 1_000_000):
                        raise ValueError("Expression power is too large.")
                except (TypeError, ValueError, OverflowError):
                    raise ValueError("Expression power is invalid or too large.") from None
        return parsed

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
            "atan2": sp.atan2,
            "sinh": sp.sinh,
            "cosh": sp.cosh,
            "tanh": sp.tanh,
            "cot": sp.cot,
            "sec": sp.sec,
            "csc": sp.csc,
            "acot": sp.acot,
            "asec": sp.asec,
            "acsc": sp.acsc,
            "exp": sp.exp,
            "log": sp.log,
            "log10": lambda value: sp.log(value, 10),
            "ln": sp.log,
            "sqrt": sp.sqrt,
            "sinc": sp.sinc,
            "abs": sp.Abs,
            "Abs": sp.Abs,
            "Max": sp.Max,
            "Min": sp.Min,
            "Heaviside": sp.Heaviside,
            "Piecewise": sp.Piecewise,
            "sign": sp.sign,
            "floor": sp.floor,
            "ceiling": sp.ceiling,
            "factorial": sp.factorial,
            "erf": sp.erf,
            "pi": sp.pi,
            "E": sp.E,
            "e": sp.E,
            "I": sp.I,
            "oo": sp.oo,
            "zoo": sp.zoo,
            "nan": sp.nan,
        }
        for name in variables:
            allowed[name] = symbols(name)
        return allowed

    def _evaluate_1d(self, expr: sp.Expr, values: np.ndarray, *, variable: sp.Symbol) -> np.ndarray:
        func = lambdify(variable, expr, "numpy")
        result = func(values)
        result_array = np.asarray(result)
        if result_array.shape == ():
            scalar = result_array
            if np.iscomplexobj(scalar) and abs(complex(scalar)) > 1e-10:
                raise ValueError("Expression produced non-real values.")
            result = np.full_like(values, float(np.real(scalar)), dtype=float)
        return self._real_array(result)

    def _finite_pair(self, x_values: np.ndarray, y_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mask = np.isfinite(x_values) & np.isfinite(y_values)
        return x_values[mask], y_values[mask]

    def _as_grid(self, value: Any, shape: tuple[int, ...]) -> np.ndarray:
        grid = self._real_array(value)
        if grid.shape == ():
            return np.full(shape, float(grid), dtype=float)
        if grid.shape != shape:
            return np.broadcast_to(grid, shape).astype(float)
        return grid

    def _real_array(self, value: Any) -> np.ndarray:
        """Convert numerical output without silently discarding an imaginary part."""

        array = np.asarray(value)
        if np.iscomplexobj(array):
            imaginary = np.asarray(np.abs(np.imag(array)), dtype=float)
            finite_imaginary = imaginary[np.isfinite(imaginary)]
            if finite_imaginary.size and float(np.max(finite_imaginary)) > 1e-10:
                raise ValueError("Expression produced non-real values.")
            array = np.real(array)
        try:
            return np.asarray(array, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("Expression did not produce numeric values.") from exc

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
        max_span = self._bounded_float("plot_max_range_span", PLOT_DEFAULT_MAX_RANGE_SPAN, 1.0, 1_000_000.0)
        if end - start > max_span:
            raise ValueError(f"Range span is too large (maximum {max_span:g}).")
        return start, end

    def _make_2d_figure(self) -> tuple[Any, Any]:
        fig, ax = plt.subplots(
            figsize=(
                self._bounded_float("plot_figure_width_in", 10.0, 3.0, 24.0),
                self._bounded_float("plot_figure_height_in", 6.0, 3.0, 24.0),
            ),
            dpi=self._bounded_int("plot_dpi", 140, 72, 320),
            constrained_layout=True,
        )
        return fig, ax

    def _style_2d_axes(self, ax: Any, xlabel: str, ylabel: str) -> None:
        ax.grid(True, alpha=self._bounded_float("plot_grid_alpha", 0.28, 0.0, 1.0), linestyle="--")
        ax.axhline(y=0, color="#0F172A", linewidth=0.8, alpha=0.75)
        ax.axvline(x=0, color="#0F172A", linewidth=0.8, alpha=0.75)
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)

    def _style_3d_axes(self, ax: Any, xlabel: str, ylabel: str, zlabel: str) -> None:
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_zlabel(zlabel, fontsize=10)
        ax.grid(True, alpha=self._bounded_float("plot_grid_alpha", 0.28, 0.0, 1.0), linestyle="--")

    def _set_3d_data_limits(
        self,
        ax: Any,
        x_values: np.ndarray,
        y_values: np.ndarray,
        z_values: np.ndarray,
    ) -> None:
        for setter, values in (
            (ax.set_xlim, x_values),
            (ax.set_ylim, y_values),
            (ax.set_zlim, z_values),
        ):
            finite_values = values[np.isfinite(values)]
            if len(finite_values) == 0:
                continue
            lower = float(np.min(finite_values))
            upper = float(np.max(finite_values))
            if math.isclose(lower, upper):
                padding = max(abs(lower) * 0.05, 1.0)
            else:
                padding = (upper - lower) * 0.06
            setter(lower - padding, upper + padding)

    def _save_and_close(self, fig: Any, target_path: Path, *, tight: bool = True) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"dpi": self._bounded_int("plot_dpi", 140, 72, 320), "facecolor": "white"}
        if tight:
            kwargs["bbox_inches"] = "tight"
        try:
            fig.savefig(target_path, **kwargs)
        except Exception:
            target_path.unlink(missing_ok=True)
            raise
        finally:
            plt.close(fig)
        self._trim_cache(target_path)

    def _cached(self, target_path: Path) -> bool:
        if self._bool("enable_cache", True) and target_path.is_file():
            try:
                if target_path.stat().st_size > 0:
                    target_path.touch()
                    return True
                target_path.unlink(missing_ok=True)
            except OSError as exc:
                self._debug("plot cache validation failed path=%s error=%s", target_path, exc)
        return False

    def _cache_key(self, *parts: Any) -> str:
        raw = repr((PLOT_CACHE_VERSION, self._cache_config_signature(), parts)).encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()[:20]

    def _cache_config_signature(self) -> tuple[Any, ...]:
        keys = (
            "plot_dpi",
            "plot_figure_width_in",
            "plot_figure_height_in",
            "plot_polar_figure_size_in",
            "plot_line_width",
            "plot_grid_alpha",
            "plot_primary_color",
            "plot_palette",
            "plot_parametric_color",
            "plot_polar_color",
            "plot_3d_cmap",
            "plot_3d_alpha",
            "plot_3d_elev",
            "plot_3d_azim",
            "plot_3d_parametric_cmap",
            "plot_3d_contour_projection",
            "plot_implicit_show_aux_contours",
            "plot_vector_field_cmap",
            "plot_vector_field_normalize",
            "plot_vector_field_scale",
            "plot_vector_field_width",
            "plot_font_family",
            "plot_sample_points",
            "plot_parametric_sample_points",
            "plot_implicit_grid_density",
            "plot_implicit_3d_grid_density",
            "plot_implicit_3d_slices",
            "plot_3d_grid_density",
            "plot_vector_field_density",
            "plot_max_functions",
            "plot_3d_max_surfaces",
            "plot_max_vectors",
            "plot_default_x_range",
            "plot_default_implicit_range",
            "plot_default_3d_range",
            "plot_default_implicit_3d_range",
            "plot_default_spherical_theta_range",
            "plot_default_spherical_phi_range",
            "plot_default_theta_range",
            "plot_default_t_range",
            "plot_default_3d_t_range",
            "plot_default_vector_range",
            "plot_max_expression_length",
            "plot_max_expression_ops",
            "plot_max_power",
            "plot_max_range_span",
        )
        return tuple((key, get_config_value(self._config, key, None)) for key in keys)

    def _trim_cache(self, protected: Path | None = None) -> None:
        """Apply a bounded LRU-like policy to plot PNGs after each render."""

        max_files = self._bounded_int(
            "plot_cache_max_files",
            PLOT_DEFAULT_CACHE_MAX_FILES,
            1,
            500,
        )
        max_bytes = int(
            self._bounded_float(
                "plot_cache_max_bytes",
                PLOT_DEFAULT_CACHE_MAX_MB * 1024 * 1024,
                1 * 1024 * 1024,
                10 * 1024 * 1024 * 1024,
            )
        )
        files = [path for path in self._temp_dir.glob("plot_*.png") if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime)
        total_bytes = sum(path.stat().st_size for path in files)
        while files and (len(files) > max_files or total_bytes > max_bytes):
            candidate = files.pop(0)
            if protected is not None and candidate == protected:
                files.append(candidate)
                if all(item == protected for item in files):
                    break
                continue
            try:
                size = candidate.stat().st_size
                candidate.unlink(missing_ok=True)
                total_bytes -= size
            except FileNotFoundError:
                continue
            except OSError as exc:
                self._debug("plot cache eviction failed path=%s error=%s", candidate, exc)

    def release(self) -> None:
        """Release pyplot figures when the plugin is unloaded."""

        if not _BACKEND_READY or plt is None:
            return
        with MATPLOTLIB_RENDER_LOCK:
            plt.close("all")

    def _bounded_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = self._int(key, default)
        return min(max(value, minimum), maximum)

    def _bounded_float(self, key: str, default: float, minimum: float, maximum: float) -> float:
        value = self._float(key, default)
        if not math.isfinite(value):
            value = default
        return min(max(value, minimum), maximum)

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
