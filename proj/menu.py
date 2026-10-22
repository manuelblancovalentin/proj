"""`proj configmenu`: an interactive editor for one environment's metadata.

Runs only from the private menu runtime (see menu_runtime.py), because it
needs Textual. The left panel lists what can be configured; choosing an entry
opens a dialog. The right panel shows project.toml exactly as it will be
saved, with unsaved lines highlighted. Escape always closes a dialog without
changes; on the main screen it leaves, but asks first when there are unsaved
changes, and Escape in that question means "stay".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    OptionList,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from .config import load_config
from .discovery import resolve
from .errors import ProjError
from .menu_state import MenuState, format_hook, parse_hook

ENTRIES = (
    ("description", "Description"),
    ("root", "Project root"),
    ("manager", "Python manager"),
    ("python", "Python environment"),
    ("hooks:startup", "Startup hooks"),
    ("hooks:shutdown", "Shutdown hooks"),
    ("modules:compiler", "Compiler modules"),
    ("modules:toolchain", "Toolchain modules"),
    ("modules:application", "Application modules"),
    ("modules:project", "Project modules"),
    ("save", "Save changes"),
)
RECOMMENDED = {"description", "python", "modules:toolchain", "modules:compiler"}


# --- dialogs ---------------------------------------------------------------


class Dialog(ModalScreen):
    """Base dialog: Escape closes it and returns to the main menu unchanged."""

    BINDINGS = [Binding("escape", "cancel", "Back", priority=True)]

    def action_cancel(self) -> None:
        self.dismiss(None)

    def status(self, message: str, error: bool = False) -> None:
        label = self.query_one("#status", Label)
        label.update(Text(message, style="bold red" if error else "dim"))


class TextDialog(Dialog):
    def __init__(self, title: str, help_text: str, value: str, apply: Callable[[str], None]):
        super().__init__()
        self.title_text = title
        self.help_text = help_text
        self.value = value
        self.apply = apply

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(self.title_text, style="bold"), classes="dialog-title")
            yield Label(Text(self.help_text, style="dim"))
            yield Input(value=self.value, id="value")
            yield Label("", id="status")
            with Horizontal(classes="buttons"):
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    @on(Input.Submitted, "#value")
    @on(Button.Pressed, "#apply")
    def submit(self) -> None:
        try:
            self.apply(self.query_one("#value", Input).value)
        except ProjError as exc:
            self.status(str(exc), error=True)
            return
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(None)


class ScanningDialog(Dialog):
    """A dialog whose choices come from a slow scan, with a Rescan button."""

    def scan(self) -> None:
        self.status("Scanning…")
        self.run_scan()

    @work(thread=True, exclusive=True)
    def run_scan(self) -> None:
        try:
            result = self.load()
        except ProjError as exc:
            self.app.call_from_thread(self.scan_failed, str(exc))
            return
        self.app.call_from_thread(self.scanned, result)

    def load(self):
        raise NotImplementedError

    def scanned(self, result) -> None:
        raise NotImplementedError

    def scan_failed(self, message: str) -> None:
        self.status(message, error=True)

    @on(Button.Pressed, "#rescan")
    def rescan_pressed(self) -> None:
        self.app.cache.pop(self.cache_key, None)
        self.scan()

    @on(Button.Pressed, "#cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(None)


class ManagerDialog(ScanningDialog):
    cache_key = "managers"

    def __init__(self, current: str):
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text("Python manager", style="bold"), classes="dialog-title")
            yield Label(Text("The tool whose shell function activates this project's Python environment.", style="dim"))
            yield OptionList(id="choices")
            yield Label("", id="status")
            with Horizontal(classes="buttons"):
                yield Button("Rescan", id="rescan")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        cached = self.app.cache.get(self.cache_key)
        if cached is None:
            self.scan()
        else:
            self.scanned(cached)

    def load(self):
        return self.app.state.scan_managers()

    def scanned(self, managers: dict[str, str | None]) -> None:
        self.app.cache[self.cache_key] = managers
        choices = self.query_one("#choices", OptionList)
        choices.clear_options()
        for manager, executable in managers.items():
            found = Text(executable, style="green") if executable else Text("not found", style="red")
            mark = "● " if manager == self.current else "  "
            choices.add_option(Option(Text.assemble(mark, (manager, "bold"), "  ", found), id=manager))
        names = list(managers)
        choices.highlighted = names.index(self.current) if self.current in names else 0
        choices.focus()
        found = sum(1 for executable in managers.values() if executable)
        self.status(f"{found} of {len(managers)} managers found on PATH")

    @on(OptionList.OptionSelected, "#choices")
    def chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class PythonDialog(ScanningDialog):
    NONE = "\0none"

    def __init__(self, manager: str, current: str):
        super().__init__()
        self.manager = manager
        self.current = current
        self.cache_key = ("python", manager)
        self.environments: dict[str, Path] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(f"Python environment ({self.manager})", style="bold"), classes="dialog-title")
            yield Label(Text("Existing environments of this manager. proj never creates or changes them.", style="dim"))
            yield OptionList(id="choices")
            yield Label("", id="status")
            with Horizontal(classes="buttons"):
                yield Button("Rescan", id="rescan")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        cached = self.app.cache.get(self.cache_key)
        if cached is None:
            self.scan()
        else:
            self.scanned(cached)

    def load(self):
        return self.app.state.scan_python_environments()

    def scanned(self, environments: dict[str, Path]) -> None:
        self.app.cache[self.cache_key] = environments
        self.environments = environments
        choices = self.query_one("#choices", OptionList)
        choices.clear_options()
        choices.add_option(Option(Text("(none)", style="italic"), id=self.NONE))
        highlight = 0
        for index, (name, prefix) in enumerate(sorted(environments.items()), start=1):
            current = self.current in (name, str(prefix))
            if current:
                highlight = index
            mark = "● " if current else "  "
            choices.add_option(
                Option(Text.assemble(mark, (name, "bold"), "  ", (str(prefix), "dim")), id=name)
            )
        choices.highlighted = highlight
        choices.focus()
        self.status(f"{len(environments)} environments found")

    @on(OptionList.OptionSelected, "#choices")
    def chosen(self, event: OptionList.OptionSelected) -> None:
        name = event.option.id
        if name == self.NONE:
            self.dismiss(("", None))
        else:
            self.dismiss((name, self.environments.get(name)))


class HooksDialog(Dialog):
    BINDINGS = [
        Binding("escape", "cancel", "Back", priority=True),
        Binding("delete", "remove", "Remove"),
    ]

    def __init__(self, phase: str, hooks: list[list[str]]):
        super().__init__()
        self.phase = phase
        self.hooks = [list(argv) for argv in hooks]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(f"{self.phase.title()} hooks", style="bold"), classes="dialog-title")
            when = "after activation" if self.phase == "startup" else "before deactivation"
            yield Label(Text(f"Commands run in the project root {when}, in order, without a shell.", style="dim"))
            yield OptionList(id="hooks")
            yield Input(placeholder="Add a command, e.g. ./scripts/check --fast", id="command")
            yield Label("", id="status")
            with Horizontal(classes="buttons"):
                yield Button("Remove selected", id="remove")
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.refresh_hooks()
        self.query_one("#command", Input).focus()

    def refresh_hooks(self) -> None:
        listing = self.query_one("#hooks", OptionList)
        listing.clear_options()
        for argv in self.hooks:
            listing.add_option(Option(format_hook(argv)))
        if not self.hooks:
            self.status("No hooks yet. Type a command below and press Enter.")

    @on(Input.Submitted, "#command")
    def add(self, event: Input.Submitted) -> None:
        try:
            argv = parse_hook(event.value)
        except ProjError as exc:
            self.status(str(exc), error=True)
            return
        self.hooks.append(argv)
        event.input.value = ""
        self.refresh_hooks()
        self.status(f"Added: {format_hook(argv)}")

    @on(Button.Pressed, "#remove")
    def action_remove(self) -> None:
        index = self.query_one("#hooks", OptionList).highlighted
        if index is None or index >= len(self.hooks):
            self.status("Highlight a hook to remove first.", error=True)
            return
        removed = self.hooks.pop(index)
        self.refresh_hooks()
        self.status(f"Removed: {format_hook(removed)}")

    @on(Button.Pressed, "#apply")
    def apply(self) -> None:
        self.dismiss(self.hooks)

    @on(Button.Pressed, "#cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(None)


class ModulesDialog(ScanningDialog):
    cache_key = "modules"

    def __init__(self, category: str, configured: list[str]):
        super().__init__()
        self.category = category
        self.configured = list(configured)
        self.selected = set(configured)
        self.available: list[str] = []
        self.custom: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(f"{self.category.title()} modules", style="bold"), classes="dialog-title")
            yield Label(
                Text(
                    "Type to filter; Enter selects the only match, or adds a name Lmod does not list. "
                    "Tab moves to the list, where Space toggles.",
                    style="dim",
                )
            )
            yield Input(placeholder="Filter modules…", id="filter")
            yield SelectionList(id="modules")
            yield Label("", id="status")
            with Horizontal(classes="buttons"):
                yield Button("Rescan", id="rescan")
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#filter", Input).focus()
        cached = self.app.cache.get(self.cache_key)
        if cached is None:
            self.scan()
        else:
            self.scanned(cached)

    def load(self):
        return self.app.state.scan_modules()

    def scanned(self, modules: list[str]) -> None:
        self.app.cache[self.cache_key] = modules
        self.available = modules
        self.rebuild()
        self.status(f"{len(modules)} modules available from Lmod; {len(self.selected)} selected")

    def scan_failed(self, message: str) -> None:
        self.available = []
        self.rebuild()
        self.status(f"{message}. You can still type module names and press Enter.", error=True)

    def candidates(self) -> list[str]:
        names = list(self.available)
        for name in (*self.configured, *self.custom):
            if name not in names:
                names.append(name)
        return names

    def rebuild(self) -> None:
        text = self.query_one("#filter", Input).value.strip().lower()
        listing = self.query_one("#modules", SelectionList)
        listing.clear_options()
        known = set(self.available)
        for name in self.candidates():
            if text and text not in name.lower():
                continue
            prompt = Text(name)
            if name not in known:
                prompt.append("  not listed by Lmod", style="yellow")
            listing.add_option(Selection(prompt, name, name in self.selected))
        if listing.option_count:
            listing.highlighted = 0

    def visible(self) -> list[str]:
        text = self.query_one("#filter", Input).value.strip().lower()
        return [name for name in self.candidates() if text in name.lower()]

    @on(Input.Changed, "#filter")
    def filtered(self) -> None:
        self.rebuild()

    @on(Input.Submitted, "#filter")
    def add_custom(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not name:
            self.query_one("#modules", SelectionList).focus()
            return
        matches = self.visible()
        if name not in self.candidates() and len(matches) == 1:
            name = matches[0]
        elif name not in self.candidates():
            self.custom.append(name)
        self.selected.add(name)
        event.input.value = ""
        self.rebuild()
        self.status(f"Selected {name}")

    @on(SelectionList.SelectedChanged, "#modules")
    def toggled(self, event: SelectionList.SelectedChanged) -> None:
        listing = event.selection_list
        visible = {listing.get_option_at_index(index).value for index in range(listing.option_count)}
        self.selected = (self.selected - visible) | set(listing.selected)
        self.status(f"{len(self.selected)} selected")

    def result(self) -> list[str]:
        # Keep the configured order, then add new choices in list order.
        kept = [name for name in self.configured if name in self.selected]
        added = [name for name in self.candidates() if name in self.selected and name not in kept]
        return kept + added

    @on(Button.Pressed, "#apply")
    def apply(self) -> None:
        self.dismiss(self.result())


class LeaveDialog(Dialog):
    """Asked when leaving with unsaved changes. Escape and Enter both stay."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="narrow"):
            yield Label(Text("Unsaved changes", style="bold"), classes="dialog-title")
            yield Label("Leave without saving them?")
            yield Label("", id="status")
            with Horizontal(classes="buttons"):
                yield Button("No, stay", variant="primary", id="stay")
                yield Button("Save and quit", variant="success", id="save")
                yield Button("Quit without saving", variant="error", id="discard")

    def on_mount(self) -> None:
        self.query_one("#stay", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss("stay")

    @on(Button.Pressed)
    def chosen(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)


# --- main screen -------------------------------------------------------------


class EntryItem(ListItem):
    def __init__(self, key: str, label: Label):
        super().__init__(label)
        self.key = key


class ConfigMenu(App):
    TITLE = "proj configmenu"
    CSS = """
    #body { height: 1fr; }
    #left { width: 1fr; min-width: 44; border: round $accent; }
    #right { width: 1fr; border: round $secondary; }
    #identity { padding: 0 1 1 1; height: auto; border-bottom: hkey $accent 50%; margin-bottom: 1; }
    #banner { padding: 0 1; color: $warning; height: auto; }
    #entries { height: 1fr; }
    #entries > ListItem { padding: 0 1; }
    #preview { padding: 0 1; }
    Dialog { align: center middle; }
    #dialog {
        width: 80%; max-width: 110; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    #dialog.narrow { width: 64; }
    #dialog OptionList, #dialog SelectionList { height: auto; max-height: 18; margin: 1 0; }
    #dialog Input { margin: 1 0 0 0; }
    #dialog Label { width: 100%; }
    .dialog-title { margin-bottom: 1; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    """
    BINDINGS = [
        Binding("escape", "leave", "Quit"),
        Binding("ctrl+q", "leave", "Quit", priority=True, show=False),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("enter", "edit", "Edit"),
    ]

    def __init__(self, state: MenuState):
        super().__init__()
        self.state = state
        self.cache: dict = {}
        self.saved_any = False
        self.sub_title = state.name

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static(id="identity")
                if self.state.read_only_reason:
                    yield Static(f"Read-only: {self.state.read_only_reason}", id="banner")
                yield ListView(
                    *(EntryItem(key, Label(id=f"label-{key.replace(':', '-')}")) for key, _ in ENTRIES),
                    id="entries",
                )
            with VerticalScroll(id="right"):
                yield Static(id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#left").border_title = "Configure"
        identity = Table.grid(padding=(0, 2))
        identity.add_column(style="bold cyan", no_wrap=True)
        identity.add_column()
        for label, value in self.state.identity():
            identity.add_row(label, value)
        self.query_one("#identity", Static).update(identity)
        self.refresh_view()
        self.query_one("#entries", ListView).focus()

    # --- rendering ------------------------------------------------------

    def summary(self, key: str) -> Text:
        state = self.state
        if key == "description":
            value = state.description
        elif key == "root":
            value = state.root
        elif key == "manager":
            value = state.manager
        elif key == "python":
            value = state.python_environment
        elif key.startswith("hooks:"):
            hooks = state.hooks(key.split(":", 1)[1])
            value = "; ".join(format_hook(argv) for argv in hooks)
        elif key.startswith("modules:"):
            value = ", ".join(state.modules(key.split(":", 1)[1]))
        else:
            if state.read_only_reason:
                return Text("read-only", style="dim")
            return Text("unsaved changes", style="bold yellow") if state.dirty else Text("nothing to save", style="dim")
        if value:
            return Text(value)
        if key in RECOMMENDED:
            return Text("not set (recommended)", style="italic yellow")
        return Text("not set", style="dim italic")

    def refresh_view(self) -> None:
        for key, title in ENTRIES:
            label = self.query_one(f"#label-{key.replace(':', '-')}", Label)
            line = Text.assemble((f"{title:<22}", "bold"), self.summary(key))
            label.update(line)
        state = self.state
        right = self.query_one("#right")
        right.border_title = "project.toml" + (" • unsaved changes" if state.dirty else "")
        problem = state.validate()
        right.border_subtitle = f"✖ {problem}" if problem else "✔ valid"
        self.query_one("#preview", Static).update(
            Syntax(
                state.preview(),
                "toml",
                theme="ansi_dark",
                line_numbers=True,
                highlight_lines=state.changed_lines(),
                word_wrap=True,
                background_color="default",
            )
        )

    # --- actions --------------------------------------------------------

    def action_edit(self) -> None:
        entries = self.query_one("#entries", ListView)
        if self.screen is self.screen_stack[0] and entries.highlighted_child is not None:
            self.open(entries.highlighted_child.key)

    @on(ListView.Selected, "#entries")
    def selected(self, event: ListView.Selected) -> None:
        self.open(event.item.key)

    def open(self, key: str) -> None:
        state = self.state

        def changed(result) -> None:
            if result is not None:
                self.refresh_view()

        if key == "description":
            self.push_screen(
                TextDialog("Description", "A short summary shown by proj list and proj info.", state.description, state.set_description),
                changed,
            )
        elif key == "root":
            self.push_screen(
                TextDialog("Project root", "The directory proj changes to on activation. It must exist.", state.root, state.set_root),
                changed,
            )
        elif key == "manager":
            def set_manager(manager) -> None:
                if manager:
                    state.set_manager(manager)
                    self.refresh_view()
            self.push_screen(ManagerDialog(state.manager), set_manager)
        elif key == "python":
            def set_python(choice) -> None:
                if choice is not None:
                    state.set_python_environment(*choice)
                    self.refresh_view()
            self.push_screen(PythonDialog(state.manager, state.python_environment), set_python)
        elif key.startswith("hooks:"):
            phase = key.split(":", 1)[1]
            def set_hooks(hooks) -> None:
                if hooks is not None:
                    state.set_hooks(phase, hooks)
                    self.refresh_view()
            self.push_screen(HooksDialog(phase, state.hooks(phase)), set_hooks)
        elif key.startswith("modules:"):
            category = key.split(":", 1)[1]
            def set_modules(modules) -> None:
                if modules is not None:
                    state.set_modules(category, modules)
                    self.refresh_view()
            self.push_screen(ModulesDialog(category, state.modules(category)), set_modules)
        elif key == "save":
            self.action_save()

    def action_save(self) -> bool:
        if not self.state.dirty:
            self.notify("Nothing to save.")
            return True
        try:
            self.state.save()
        except ProjError as exc:
            self.notify(str(exc), title="Not saved", severity="error", timeout=8)
            return False
        self.saved_any = True
        self.refresh_view()
        if os.environ.get("PROJ_ACTIVE") == self.state.name:
            self.notify("Saved. Reactivate the environment to apply the changes.", title="Saved")
        else:
            self.notify("Saved.", title="Saved")
        return True

    def action_leave(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        if not self.state.dirty:
            self.exit()
            return

        def decided(choice) -> None:
            if choice == "discard":
                self.exit()
            elif choice == "save" and self.action_save():
                self.exit()

        self.push_screen(LeaveDialog(), decided)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: proj configmenu [--env NAME]", file=sys.stderr)
        return 2
    try:
        config = load_config()
        state = MenuState(config, resolve(config, argv[0]))
    except ProjError as exc:
        print(f"proj: {exc}", file=sys.stderr)
        return 2
    app = ConfigMenu(state)
    app.run()
    if app.saved_any:
        print(f"proj: saved {state.project.metadata_path}")
        if os.environ.get("PROJ_ACTIVE") == state.name:
            print(f"proj: run `proj deactivate && proj activate {state.name}` to apply the changes")
    return 0
