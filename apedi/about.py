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
    dialog.set_copyright("© 2026 Amadeusz Prus (aprus)")
    dialog.set_license(_(
        "Released under the MIT License. See the LICENSE file shipped with "
        "Apedi for the full text."
    ))
    dialog.set_wrap_license(True)
    dialog.set_authors(["Amadeusz Prus (aprus)"])
    dialog.set_logo_icon_name("pl.aprus.apedi")
    dialog.set_transient_for(parent)
    dialog.set_modal(True)
    dialog.add_credit_section(
        _("Support"),
        [
            "☕  Ko-fi  https://ko-fi.com/aprus",
            "☕  buycoffee.to  https://buycoffee.to/aprus",
        ],
    )
    dialog.present()
