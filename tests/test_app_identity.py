# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from PIL import Image

import app_identity


class _FakeTk:
    def __init__(self):
        self.calls = []

    def call(self, *args):
        self.calls.append(args)


class _FakeWindow:
    def __init__(self):
        self.tk = _FakeTk()
        self.title_value = None
        self.icon_name = None
        self.icon_value = None

    def title(self, value):
        self.title_value = value

    def iconname(self, value):
        self.icon_name = value

    def iconphoto(self, default, value):
        self.icon_value = (default, value)


class AppIdentityTests(unittest.TestCase):
    def test_application_name_and_icon_asset(self):
        self.assertEqual(app_identity.APP_NAME, "EHSİM")
        icon_path = app_identity.resource_path(app_identity.ICON_RELATIVE_PATH)
        self.assertTrue(icon_path.is_file())
        with Image.open(icon_path) as icon:
            self.assertEqual(icon.size, (1024, 1024))
            self.assertEqual(icon.format, "PNG")
            self.assertEqual(icon.mode, "RGBA")
            alpha = icon.getchannel("A")
            self.assertEqual(
                [
                    alpha.getpixel((0, 0)),
                    alpha.getpixel((1023, 0)),
                    alpha.getpixel((0, 1023)),
                    alpha.getpixel((1023, 1023)),
                ],
                [0, 0, 0, 0],
            )
            self.assertEqual(alpha.getpixel((512, 512)), 255)

    def test_identity_is_applied_to_tk_window(self):
        window = _FakeWindow()
        fake_icon = object()
        with (
            patch.object(app_identity, "_set_macos_process_name", return_value=True),
            patch.object(app_identity, "_set_windows_app_id", return_value=False),
            patch.object(app_identity.tk, "PhotoImage", return_value=fake_icon),
        ):
            result = app_identity.apply_app_identity(window)

        self.assertIs(result, fake_icon)
        self.assertEqual(window.title_value, "EHSİM")
        self.assertEqual(window.icon_name, "EHSİM")
        self.assertIn(("tk", "appname", "ehsim"), window.tk.calls)
        self.assertEqual(window.icon_value, (True, fake_icon))


if __name__ == "__main__":
    unittest.main()
