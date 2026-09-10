try:  # Hermes directory-form loader: imported as ``hermes_plugins.<slug>``.
    from .hermes_chathub_connector import register
except ImportError:  # pragma: no cover - pytest imports this file standalone
    # pytest treats the repo root as a package (this file) and imports it as a
    # top-level module; the relative import above cannot work then.
    from hermes_chathub_connector import register

__all__ = ["register"]
