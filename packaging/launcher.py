"""Entry point for the packaged app.

Double-clicking the built executable runs this with no arguments, which starts
`cutup app` (open library, serve, open the browser). Passing arguments falls
through to the normal CLI, so the same binary is also `PigskinCutter diagnostics`
etc. for support.
"""

import sys

from cutup.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("app")
    main()
