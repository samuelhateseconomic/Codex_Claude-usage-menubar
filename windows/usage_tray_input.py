"""Windows tray activation adapter; importing it never imports a GUI backend."""
import os

# Windows notification codes used by the pinned pystray 0.19.5 backend.
LEFT_BUTTON_UP = 0x0202
RIGHT_BUTTON_UP = 0x0205


def menu_icon_class(icon_class, *, windows=None):
    """Open the existing native popup on either click; preserve other events.

    pystray's Windows backend routes right-button release through its native
    menu and left-button release through the default action. This local subclass
    reuses the menu path without modifying the dependency or duplicating menus.
    Non-Windows and test/alternate backends retain their existing behavior.
    """
    if windows is None:
        windows = os.name == 'nt'
    if not windows or not hasattr(icon_class, '_on_notify'):
        return icon_class

    class ClickMenuIcon(icon_class):
        # pystray derives backend-option names from the concrete class module.
        __module__ = icon_class.__module__

        def _on_notify(self, wparam, lparam):
            if lparam == LEFT_BUTTON_UP:
                lparam = RIGHT_BUTTON_UP
            return super()._on_notify(wparam, lparam)

    return ClickMenuIcon
