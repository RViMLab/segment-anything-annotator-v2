"""Compatibility launcher: video annotation now uses the current GUI and shortcuts."""

import sys

from annotator import main


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--review" not in arguments:
        arguments = ["--video", *arguments]
    sys.exit(main(arguments))
