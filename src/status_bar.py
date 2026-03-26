"""macOS menu bar status item using PyObjC.

Replaces rumps with a lightweight NSStatusItem that:
- Left-click: toggles the main window
- Right-click: shows a minimal native menu
"""

import objc
from typing import Callable

import AppKit
from Foundation import NSObject
from PyObjCTools import AppHelper


class StatusBarDelegate(NSObject):
    """Handles status bar button clicks and menu actions."""

    def init(self):
        self = objc.super(StatusBarDelegate, self).init()
        if self is None:
            return None
        self._toggle_window = None
        self._toggle_recording = None
        self._quit = None
        self._recording = False
        self._record_item = None
        self._status_item = None
        return self

    @objc.python_method
    def configure(self, toggle_window_fn, toggle_recording_fn, quit_fn):
        self._toggle_window = toggle_window_fn
        self._toggle_recording = toggle_recording_fn
        self._quit = quit_fn

    @objc.python_method
    def set_recording(self, is_recording):
        self._recording = is_recording
        if self._record_item:
            title = "Stop Recording" if is_recording else "Start Recording"
            self._record_item.setTitle_(title)

    def statusBarClicked_(self, sender):
        event = AppKit.NSApp.currentEvent()
        if event and event.type() == AppKit.NSEventTypeRightMouseUp:
            self._showMenu_(sender)
        else:
            if self._toggle_window:
                self._toggle_window()

    def _showMenu_(self, sender):
        menu = AppKit.NSMenu.alloc().init()

        self._record_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Stop Recording" if self._recording else "Start Recording",
            "recordClicked:",
            "",
        )
        self._record_item.setTarget_(self)
        menu.addItem_(self._record_item)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quitClicked:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        self._status_item.popUpStatusItemMenu_(menu)

    def recordClicked_(self, sender):
        if self._toggle_recording:
            self._toggle_recording()

    def quitClicked_(self, sender):
        if self._quit:
            self._quit()


class StatusBarController:
    """Controls the macOS menu bar status item."""

    def __init__(
        self,
        toggle_window_fn: Callable,
        toggle_recording_fn: Callable,
        quit_fn: Callable,
    ):
        self._toggle_window_fn = toggle_window_fn
        self._toggle_recording_fn = toggle_recording_fn
        self._quit_fn = quit_fn
        self._delegate = None
        self._status_item = None

    def setup(self):
        """Create the status bar item. Must be called after the event loop starts."""
        AppHelper.callAfter(self._create_status_item)

    def _create_status_item(self):
        status_bar = AppKit.NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        self._status_item.setTitle_("\U0001f399")

        self._delegate = StatusBarDelegate.alloc().init()
        self._delegate.configure(
            self._toggle_window_fn,
            self._toggle_recording_fn,
            self._quit_fn,
        )
        self._delegate._status_item = self._status_item

        button = self._status_item.button()
        button.setTarget_(self._delegate)
        button.setAction_(objc.selector(self._delegate.statusBarClicked_, signature=b"v@:@"))
        button.sendActionOn_(
            AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp
        )

    def set_title(self, title: str):
        """Update the status bar text. Thread-safe."""
        def update():
            if self._status_item:
                self._status_item.setTitle_(title)
        AppHelper.callAfter(update)

    def set_recording(self, is_recording: bool):
        """Update the recording state for the right-click menu."""
        if self._delegate:
            self._delegate.set_recording(is_recording)
