from __future__ import annotations

from typing import Any


CONFIG_KEY_GROUPS: dict[str, str] = {
    "auto_render_enabled": "basic_settings",
    "auto_render_prompt_enabled": "basic_settings",
    "math_keywords": "basic_settings",
    "debug_logging_enabled": "basic_settings",
    "image_math_tool_prompt_enabled": "llm_prompt_settings",
    "image_math_tool_awareness_prompt": "llm_prompt_settings",
    "image_math_auto_render_prompt": "llm_prompt_settings",
    "expression_latexify_backend": "llm_prompt_settings",
    "allow_llm_latexify_fallback": "llm_prompt_settings",
    "llm_render_layout_prompt_enabled": "llm_prompt_settings",
    "llm_render_layout_prompt": "llm_prompt_settings",
    "llm_render_layout_mode": "llm_prompt_settings",
    "formula_tool_supports_markdown_content": "llm_prompt_settings",
    "normalize_escaped_newlines_enabled": "llm_prompt_settings",
    "auto_wrap_bare_latex_enabled": "llm_prompt_settings",
    "send_pre_reply_before_manual_render": "pre_reply_settings",
    "send_pre_reply_before_tool_render": "pre_reply_settings",
    "pre_reply_use_llm": "pre_reply_settings",
    "pre_reply_system_prompt": "pre_reply_settings",
    "pre_reply_user_prompt": "pre_reply_settings",
    "pre_reply_fallback_text_formula": "pre_reply_settings",
    "pre_reply_fallback_text_solution": "pre_reply_settings",
    "render_backend": "render_engine_settings",
    "local_browser_executable": "render_engine_settings",
    "linux_disable_browser_sandbox": "render_engine_settings",
    "enable_cache": "render_engine_settings",
    "temp_retention_hours": "render_engine_settings",
    "cleanup_on_initialize": "render_engine_settings",
    "cleanup_before_render": "render_engine_settings",
    "prewarm_renderer": "render_engine_settings",
    "render_timeout_ms": "render_engine_settings",
    "render_wait_until": "render_engine_settings",
    "viewport_width": "render_engine_settings",
    "viewport_height": "render_engine_settings",
    "device_scale_factor": "render_engine_settings",
    "render_dpi_scale": "render_engine_settings",
    "manual_solver_step_limit": "render_engine_settings",
    "mathjax_cdn_url": "render_engine_settings",
    "send_image_transport": "image_delivery_settings",
    "send_image_max_bytes": "image_delivery_settings",
    "send_image_max_side": "image_delivery_settings",
    "send_image_jpeg_quality": "image_delivery_settings",
    "default_style": "card_style_settings",
    "default_accent_color": "card_style_settings",
    "render_text_color": "card_style_settings",
    "render_muted_text_color": "card_style_settings",
    "render_page_background_css": "card_style_settings",
    "render_card_background_css": "card_style_settings",
    "title_font_size_px": "card_style_settings",
    "subtitle_font_size_px": "card_style_settings",
    "body_font_size_px": "card_style_settings",
    "body_line_height": "card_style_settings",
    "formula_font_scale": "card_style_settings",
    "page_padding_px": "card_style_settings",
    "card_radius_px": "card_style_settings",
    "section_radius_px": "card_style_settings",
    "section_gap_px": "card_style_settings",
    "content_max_width_px": "card_style_settings",
    "geometry_render_enabled": "geometry_settings",
    "geometry_tool_prompt_enabled": "geometry_settings",
    "geometry_tool_awareness_prompt": "geometry_settings",
    "image_geometry_auto_render_prompt_enabled": "geometry_settings",
    "image_geometry_auto_render_prompt": "geometry_settings",
    "geometry_solver_prompt_enabled": "geometry_settings",
    "geometry_solver_prompt": "geometry_settings",
    "geometry_section_enabled": "geometry_settings",
    "geometry_position_mode": "geometry_settings",
    "geometry_section_position": "geometry_settings",
    "geometry_skip_blank_scene_enabled": "geometry_settings",
    "geometry_skip_blank_image_enabled": "geometry_settings",
    "geometry_retry_without_viewport_on_blank": "geometry_settings",
    "geometry_section_label": "geometry_settings",
    "geometry_caption_enabled": "geometry_settings",
    "geometry_section_default_caption": "geometry_settings",
    "geometry_keywords": "geometry_settings",
    "geometry_figure_width_in": "geometry_style_settings",
    "geometry_figure_height_in": "geometry_style_settings",
    "geometry_dpi": "geometry_style_settings",
    "geometry_padding_ratio": "geometry_style_settings",
    "geometry_min_span": "geometry_style_settings",
    "geometry_line_width": "geometry_style_settings",
    "geometry_point_size": "geometry_style_settings",
    "geometry_label_font_size": "geometry_style_settings",
    "geometry_annotation_font_size": "geometry_style_settings",
    "geometry_font_family": "geometry_style_settings",
    "geometry_background_color": "geometry_style_settings",
    "geometry_transparent_background": "geometry_style_settings",
    "geometry_primary_color": "geometry_style_settings",
    "geometry_auxiliary_color": "geometry_style_settings",
    "geometry_highlight_color": "geometry_style_settings",
    "geometry_subtle_color": "geometry_style_settings",
    "geometry_fill_color": "geometry_style_settings",
    "geometry_fill_alpha": "geometry_style_settings",
    "geometry_point_color": "geometry_style_settings",
    "geometry_text_color": "geometry_style_settings",
    "geometry_circle_color": "geometry_style_settings",
    "geometry_angle_color": "geometry_style_settings",
    "geometry_default_angle_radius": "geometry_style_settings",
    "geometry_angle_radius_step": "geometry_style_settings",
    "plot_tool_prompt_enabled": "plot_settings",
    "plot_tool_awareness_prompt": "plot_settings",
    "plot_in_solution_card_enabled": "plot_settings",
    "plot_solution_card_prompt": "plot_settings",
    "plot_solver_prompt": "plot_settings",
    "plot_section_label": "plot_settings",
    "plot_section_position": "plot_settings",
    "plot_caption_enabled": "plot_settings",
    "plot_auto_caption_enabled": "plot_settings",
    "plot_keywords": "plot_settings",
    "plot_dpi": "plot_settings",
    "plot_default_x_range": "plot_settings",
    "plot_default_implicit_range": "plot_settings",
    "plot_default_3d_range": "plot_settings",
    "plot_default_theta_range": "plot_settings",
    "plot_default_t_range": "plot_settings",
    "plot_default_3d_t_range": "plot_settings",
    "plot_default_vector_range": "plot_settings",
    "plot_sample_points": "plot_settings",
    "plot_parametric_sample_points": "plot_settings",
    "plot_implicit_grid_density": "plot_settings",
    "plot_3d_grid_density": "plot_settings",
    "plot_vector_field_density": "plot_settings",
    "plot_line_width": "plot_settings",
    "plot_grid_alpha": "plot_settings",
    "plot_3d_cmap": "plot_settings",
    "plot_3d_alpha": "plot_settings",
    "plot_3d_elev": "plot_settings",
    "plot_3d_azim": "plot_settings",
    "plot_font_family": "plot_settings",
}


_MISSING = object()


def get_config_value(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default

    group_key = CONFIG_KEY_GROUPS.get(key)
    legacy_value = _lookup(config, key, _MISSING)
    nested_value = _MISSING

    if group_key:
        group = _lookup(config, group_key, _MISSING)
        if isinstance(group, dict):
            nested_value = group.get(key, _MISSING)

    if legacy_value is not _MISSING:
        if nested_value is _MISSING:
            return legacy_value
        if legacy_value != default and nested_value == default:
            return legacy_value

    if nested_value is not _MISSING:
        return nested_value
    if legacy_value is not _MISSING:
        return legacy_value
    return default


def _lookup(config: Any, key: str, default: Any) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        return config[key]
    except (KeyError, TypeError):
        return default
