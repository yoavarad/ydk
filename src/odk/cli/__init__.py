"""CLI wiring — register all subcommands on the root app."""

from odk.cli.catalog_cmd import catalog_app
from odk.cli.change_cmd import change_app
from odk.cli.component_cmd import component_app
from odk.cli.config_cmd import config_app
from odk.cli.docs_cmd import docs_app
from odk.cli.doctor_cmd import doctor_command
from odk.cli.ignite_cmd import ignite_command
from odk.cli.init_cmd import init_command
from odk.cli.main import app
from odk.cli.memory_cmd import memory_app
from odk.cli.scaffold_cmd import scaffold_app
from odk.cli.spec_cmd import spec_app
from odk.cli.task_cmd import task_app
from odk.cli.test_cmd import test_app
from odk.cli.todo_cmd import todo_app
from odk.cli.verify_cmd import verify_app
from odk.cli.visual_cmd import visual_app
from odk.cli.watch_cmd import watch_app

app.add_typer(catalog_app, name="catalog")
app.add_typer(change_app, name="change")
app.add_typer(component_app, name="component")
app.add_typer(config_app, name="config")
app.add_typer(docs_app, name="docs")
app.add_typer(memory_app, name="memory")
app.add_typer(scaffold_app, name="scaffold")
app.add_typer(spec_app, name="spec")
app.add_typer(task_app, name="task")
app.add_typer(test_app, name="test")
app.add_typer(todo_app, name="todo")
app.command("doctor")(doctor_command)
app.command("ignite")(ignite_command)
app.command("init")(init_command)
app.add_typer(verify_app, name="verify")
app.add_typer(visual_app, name="visual")
app.add_typer(watch_app, name="watch")

__all__ = ["app"]
