"""Rich Console singleton. All output goes through this."""

import io
import sys

from rich.console import Console

# On Windows, stdout/stderr commonly default to a legacy codepage (e.g. cp1252)
# that can't encode the non-ASCII characters (checkmarks, etc.) rich prints,
# crashing with UnicodeEncodeError. Reconfigure to UTF-8 so writes never fail
# -- unmappable glyphs are replaced rather than raising. Only TextIOWrapper
# supports .reconfigure(); other stream types (e.g. some test harness
# replacements) are left alone.
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# legacy_windows=False skips rich's legacy win32 console renderer, which writes
# via a separate code path that bypasses the reconfigured stream encoding above.
console = Console(legacy_windows=False)
err_console = Console(stderr=True, legacy_windows=False)
