"""The shared look (alertmesh/style.py): the theme the apps and the desktop launcher use,
and the stylesheet's colours. How the pages look is checked by eye (PROGRESS.md, Phase 14).
"""
import re
from pathlib import Path

import toml

import desktop
from alertmesh import style
from alertmesh.wire import Severity

CONFIG = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def flatten(table: dict, prefix: str = "") -> dict[str, object]:
    flat = {}
    for name, value in table.items():
        if isinstance(value, dict):
            flat.update(flatten(value, f"{prefix}{name}."))
        else:
            flat[f"{prefix}{name}"] = value
    return flat


def test_config_file_holds_the_same_theme_as_the_desktop_apps():
    config = {k: v for k, v in flatten(toml.load(CONFIG)).items() if k.startswith("theme.")}
    assert config == {f"{section}.{name}": value for section, options in style.THEME.items()
                      for name, value in options.items()}


def test_the_page_follows_the_system_not_forced_light():
    config = flatten(toml.load(CONFIG))
    args = desktop.streamlit_args(8765, desktop.PAGES["phone"])
    assert "theme.base" not in config and not any(a.startswith("--theme.base=") for a in args)
    # A light and a dark set: Streamlit follows the system's setting.
    assert "--theme.light.primaryColor=#007AFF" in args and "--theme.dark.primaryColor=#0A84FF" in args
    assert f"--theme.light.font={style.FONT}" in args


def test_system_typeface_never_monospace():
    for section in ("theme.light", "theme.dark"):
        font = style.THEME[section]["font"]
        assert font.startswith("-apple-system") and "Segoe UI" in font and "mono" not in font.lower()


def test_iphone_colours_light_and_dark():
    # ThemePalette.alertMesh, ChatBubbleStyle, severity fill and text colours (docs/desktop-design.md).
    assert style.TOKENS["blue"] == ("#007AFF", "#0A84FF")
    assert style.TOKENS["card"] == ("#F2F2F7", "#1C1C1E")
    assert style.TOKENS["own"] == ("#0066DD", "#0A6CFF")
    assert style.TOKENS["other"] == ("#E9E9EB", "#26252A")
    assert style.TOKENS["red"] == ("#BF1A1A", "#BF1A1A")
    assert style.TOKENS["red-text"] == ("#B01414", "#FF6B6B")
    assert style.TOKENS["watch"] == ("#D16600", "#FF9426") and style.TOKENS["watch-text"] == ("#9A3D00", "#FF9E4D")
    assert style.TOKENS["advice"] == ("#B88A00", "#FFD633") and style.TOKENS["advice-text"] == ("#8A6200", "#FFD84D")
    assert style.TOKENS["clear"] == ("#1E7B34", "#30D158")


def test_every_colour_has_a_dark_partner_in_the_stylesheet():
    light, dark = re.findall(r":root\{([^}]*)\}", style.CSS)[:2]
    names = set(re.findall(r"--am-([\w-]+):", dark))
    assert names == set(style.TOKENS) and names <= set(re.findall(r"--am-([\w-]+):", light))


def test_every_level_has_a_fill_text_and_bar_class():
    for severity in Severity:
        level = style.LEVEL[severity]
        for kind in ("fill", "t", "bar", "border"):
            assert f".am-{kind}-{level}{{" in style.CSS
        assert style.symbol(severity).startswith("<svg")


def test_the_stylesheet_has_no_hard_coded_theme_colour():
    """Colours come from variables, so dark mode swaps them; only the text on a solid
    warning fill is fixed (white on red, black on orange and yellow, as on the iPhone)."""
    rules = style.CSS.split("@media")[1].split("}}", 1)[1]
    assert set(re.findall(r"#[0-9A-Fa-f]{3,6}\b", rules)) <= {"#fff", "#000"}


def test_chat_runs_put_the_name_on_the_first_bubble_and_the_time_on_the_last():
    minute = 60_000
    messages = [("jun", 0), ("jun", minute), ("you", 2 * minute), ("jun", 3 * minute), ("jun", 20 * minute)]
    assert style.runs(messages) == [(True, False), (False, True), (True, True), (True, True), (True, True)]


def test_bubbles_yours_on_the_right_theirs_named():
    html = style.bubbles([(False, "jun", "Jun", "Is the bridge open?", 0), (True, "you", "You", "Closed <b>", 1)])
    assert '<div class="am-msg"><span class="am-from">Jun</span><span class="am-bub">Is the bridge open?</span>' in html
    assert '<div class="am-msg am-out am-gap"><span class="am-bub">Closed &lt;b&gt;</span>' in html
