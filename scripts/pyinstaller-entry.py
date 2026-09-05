"""Entry point for the frozen app.

`python -m claude_usage_bar` runs the package's own `__main__`, which uses a relative
import; PyInstaller runs its entry script as a top-level module, where that import has
no parent package. This file is that entry.
"""

from claude_usage_bar.app import main

main()
