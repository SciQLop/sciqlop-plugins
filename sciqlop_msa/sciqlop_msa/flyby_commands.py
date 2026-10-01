"""Command palette entries to jump a plot panel to an MSA flyby."""
from .flybys import flyby_by_label, flybys, jump, next_flyby, previous_flyby

_NEW_PANEL = "__new__"  # what the palette's PanelArg sends for "New panel"


def _panel(name: str):
    from SciQLop.user_api.plot import create_plot_panel, plot_panel

    return create_plot_panel() if name == _NEW_PANEL else plot_panel(name)


def jump_to_flyby(flyby: str = "", panel: str = ""):
    target_flyby, target_panel = flyby_by_label(flyby), _panel(panel)
    if target_flyby is not None and target_panel is not None:
        jump(target_panel, target_flyby)


def _step(panel: str, pick):
    target_panel = _panel(panel)
    if target_panel is None:
        return
    target_flyby = pick(target_panel.time_range.center())
    if target_flyby is not None:
        jump(target_panel, target_flyby)


def jump_to_next_flyby(panel: str = ""):
    _step(panel, next_flyby)


def jump_to_previous_flyby(panel: str = ""):
    _step(panel, previous_flyby)


def panel_menu_entries(panel) -> list:
    """Right-click menu of a panel: next/previous flyby from where it is, then every flyby."""
    centre = panel.time_range.center()
    steps = [(f"{direction}: {f.label}", f) for direction, f in
             (("Next", next_flyby(centre)), ("Previous", previous_flyby(centre))) if f is not None]
    choices = steps + [(f.label, f) for f in flybys()]
    return [(label, lambda f=f: jump(panel, f)) for label, f in choices]


def register_flyby_commands(registry) -> None:
    from SciQLop.components.command_palette.arg_types import PanelArg
    from SciQLop.components.command_palette.backend.registry import CommandArg, Completion, PaletteCommand

    class FlybyArg(CommandArg):
        def completions(self, context: dict) -> list:
            return [Completion(value=f.label, display=f.label) for f in flybys()]

    keywords = ["msa", "bepicolombo", "flyby", "mercury", "venus"]
    for command in (
        PaletteCommand(id="msa.flyby.jump", name="Jump to MSA flyby",
                       description="Show a BepiColombo flyby with MSA data in a panel",
                       callback=jump_to_flyby, args=[FlybyArg(name="flyby"), PanelArg()], keywords=keywords),
        PaletteCommand(id="msa.flyby.next", name="Next MSA flyby",
                       description="Jump a panel to the MSA flyby after the one it shows",
                       callback=jump_to_next_flyby, args=[PanelArg()], keywords=keywords),
        PaletteCommand(id="msa.flyby.previous", name="Previous MSA flyby",
                       description="Jump a panel to the MSA flyby before the one it shows",
                       callback=jump_to_previous_flyby, args=[PanelArg()], keywords=keywords),
    ):
        registry.register(command)
