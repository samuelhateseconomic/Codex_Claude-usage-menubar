"""Tray input routing; native dispatch is exercised without displaying a popup."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usage_tray_input import menu_icon_class,LEFT_BUTTON_UP,RIGHT_BUTTON_UP


class InputRouting(unittest.TestCase):
    def test_left_and_right_release_use_same_menu_with_original_parameters(self):
        class Backend:
            def __init__(self):self.events=[];self.handler=self._on_notify
            def _on_notify(self,wparam,lparam):
                self.events.append((wparam,lparam));return 'backend-result'
        icon=menu_icon_class(Backend,windows=True)()
        self.assertEqual(icon.handler(37,LEFT_BUTTON_UP),'backend-result')
        self.assertEqual(icon.handler(38,RIGHT_BUTTON_UP),'backend-result')
        self.assertEqual(icon.events,[(37,RIGHT_BUTTON_UP),(38,RIGHT_BUTTON_UP)])

    def test_hover_press_keyboard_and_other_notifications_pass_through(self):
        class Backend:
            def _on_notify(self,wparam,lparam):return wparam,lparam
        icon=menu_icon_class(Backend,windows=True)()
        for event in (0x0200,0x0201,0x0203,0x0204,0x007b,0x0400):
            with self.subTest(event=event):self.assertEqual(icon._on_notify(99,event),(99,event))

    def test_non_windows_and_alternate_backends_are_unchanged(self):
        class Backend:
            def _on_notify(self,wparam,lparam):pass
        class Alternate:pass
        self.assertIs(menu_icon_class(Backend,windows=False),Backend)
        self.assertIs(menu_icon_class(Alternate,windows=True),Alternate)

    def test_import_does_not_load_gui_libraries(self):
        script=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import usage_tray_input;assert not any(k in sys.modules for k in ("pystray","PIL","tkinter"))',str(script)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0)


@unittest.skipUnless(os.name=='nt','Windows native backend')
class NativeDispatch(unittest.TestCase):
    def setUp(self):
        from pystray._win32 import Icon
        from pystray._util import win32
        self.win32=win32
        self.assertEqual(LEFT_BUTTON_UP,win32.WM_LBUTTONUP)
        self.assertEqual(RIGHT_BUTTON_UP,win32.WM_RBUTTONUP)
        self.action=Mock()
        class Backend:
            def __init__(self,action):
                self._hwnd=101;self._menu_hwnd=102
                self._menu_handle=(103,[action])
                self.handler=self._on_notify
            def __call__(self):raise AssertionError('Do not activate the default action on left click')
            def _on_notify(self,wparam,lparam):return Icon._on_notify(self,wparam,lparam)
        self.icon=menu_icon_class(Backend,windows=True)(self.action)
        self.foreground=self.enterContext(patch.object(win32,'SetForegroundWindow'))
        self.cursor=self.enterContext(patch.object(win32,'GetCursorPos'))
        self.popup=self.enterContext(patch.object(win32,'TrackPopupMenuEx',return_value=1))

    def test_actual_constructor_keeps_backend_options_and_routes_notifications_to_adapter(self):
        from pystray._win32 import Icon
        adapted=menu_icon_class(Icon,windows=True)
        with patch.object(Icon,'_register_class',return_value=1),patch.object(Icon,'_release_icon'):
            icon=adapted('input-fixture',win32_fixture=True)
            try:
                self.assertEqual(icon._options,{'fixture':True})
                self.assertIs(icon._message_handlers[self.win32.WM_NOTIFY].__func__,adapted._on_notify)
            finally:
                del icon

    def test_left_click_uses_native_popup_and_selected_callback(self):
        self.icon.handler(0,LEFT_BUTTON_UP)
        self.foreground.assert_called_once_with(101)
        self.cursor.assert_called_once()
        self.popup.assert_called_once()
        self.action.assert_called_once_with(self.icon)

    def test_right_click_retains_native_popup_and_selected_callback(self):
        self.icon.handler(0,RIGHT_BUTTON_UP)
        self.popup.assert_called_once()
        self.action.assert_called_once_with(self.icon)

    def test_open_and_cancel_does_not_activate_any_action(self):
        self.popup.return_value=0
        self.icon.handler(0,LEFT_BUTTON_UP)
        self.popup.assert_called_once()
        self.action.assert_not_called()

    def test_hover_does_not_open_popup_or_invoke_action(self):
        self.icon.handler(0,0x0200)
        self.foreground.assert_not_called()
        self.cursor.assert_not_called()
        self.popup.assert_not_called()
        self.action.assert_not_called()
