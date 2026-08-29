# -*- coding: utf-8 -*-
"""EHSİM uygulama adı ve masaüstü simgesi için ortak yardımcılar."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import tkinter as tk
from typing import Any


APP_NAME = "EHSİM"
APP_ID = "tr.com.ehsim.vmodel"
ICON_RELATIVE_PATH = Path("assets") / "ehsim_app_icon.png"


def resource_path(relative_path: str | Path) -> Path:
    """Kaynak koddan ve PyInstaller paketinden çalışan mutlak yolu döndürür.

    Bu dosya Faz 7'de proje kökünden core/ alt paketine taşındı; PyInstaller
    dışı (kaynaktan çalışan) durumda proje köküne çıkmak için bir üst dizine
    (.parent.parent) çıkıyoruz — davranış (assets/ klasörünü kökte bulmak)
    taşımadan önceki haliyle aynı kalsın diye.
    """
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle_root / Path(relative_path)


def _set_macos_process_name(name: str) -> bool:
    """Paketlenmemiş Python çalıştırmalarında macOS süreç adını değiştirir."""
    if sys.platform != "darwin":
        return False
    try:
        ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/Foundation.framework/Foundation"
        )
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send_no_arg = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(("objc_msgSend", objc))
        send_object = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(("objc_msgSend", objc))
        send_text = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
        )(("objc_msgSend", objc))

        process_info = send_no_arg(
            objc.objc_getClass(b"NSProcessInfo"),
            objc.sel_registerName(b"processInfo"),
        )
        ns_name = send_text(
            objc.objc_getClass(b"NSString"),
            objc.sel_registerName(b"stringWithUTF8String:"),
            name.encode("utf-8"),
        )
        send_object(
            process_info, objc.sel_registerName(b"setProcessName:"), ns_name
        )
        return True
    except Exception:
        return False


def _set_windows_app_id() -> bool:
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return True
    except Exception:
        return False


def prepare_process_identity() -> None:
    """Tk/NSApplication oluşturulmadan önce işletim sistemi kimliğini hazırlar."""
    _set_macos_process_name(APP_NAME)
    _set_windows_app_id()


def apply_app_identity(window: Any) -> tk.PhotoImage | None:
    """Pencere başlığı, süreç adı ve varsayılan uygulama ikonunu EHSİM yapar."""
    prepare_process_identity()
    window.title(APP_NAME)
    try:
        window.iconname(APP_NAME)
    except tk.TclError:
        pass
    try:
        # Tk iç uygulama adları küçük harfle başlamalıdır.
        window.tk.call("tk", "appname", "ehsim")
    except tk.TclError:
        pass

    icon_path = resource_path(ICON_RELATIVE_PATH)
    if not icon_path.exists():
        return None
    try:
        icon = tk.PhotoImage(master=window, file=str(icon_path))
        window.iconphoto(True, icon)
        # Tk görüntüsünün çöp toplayıcı tarafından silinmesini önle.
        window._ehsim_app_icon = icon
        return icon
    except (OSError, tk.TclError):
        return None


__all__ = [
    "APP_ID", "APP_NAME", "ICON_RELATIVE_PATH", "apply_app_identity",
    "prepare_process_identity", "resource_path",
]
