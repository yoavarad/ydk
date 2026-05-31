"""Rich Console singleton. All output goes through this."""

from rich.console import Console

# Singleton — import this everywhere for consistent output
console = Console()
err_console = Console(stderr=True)
