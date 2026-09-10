import sys
from pathlib import Path

_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
	sys.path.insert(0, _PLUGIN_DIR)

from hermes_chathub_connector import register

__all__ = ["register"]
