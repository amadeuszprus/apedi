"""About dialog."""

from __future__ import annotations

import builtins

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from . import __version__


def present(parent: Gtk.Window) -> None:
    dialog = Gtk.AboutDialog()
    dialog.set_program_name("Apedi")
    dialog.set_version(__version__)
    dialog.set_comments(_("A fast, simple text editor with syntax highlighting and code formatting"))
    dialog.set_copyright("© 2026 aprus")
    dialog.set_license_type(Gtk.License.MIT_X11)
    dialog.set_authors(["aprus"])
    dialog.set_logo_icon_name("pl.aprus.apedi")
    dialog.set_transient_for(parent)
    dialog.set_modal(True)
    dialog.add_credit_section(
        _("Support"),
        ["☕  Buy me a coffee  https://buycoffee.to/aprus"],
    )
    dialog.present()
