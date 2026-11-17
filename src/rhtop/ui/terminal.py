"""Best-effort Unix pointer control, scoped to the dashboard's terminal screen."""

from textual.drivers.linux_driver import LinuxDriver

# Kitty OSC 22: push the standard arrow, then pop it before leaving the UI.
# Unsupported terminals ignore these sequences. No terminal settings are saved.
ARROW_POINTER = "\x1b]22;>default\x1b\\"
RESTORE_POINTER = "\x1b]22;<\x1b\\"


class ArrowPointerDriver(LinuxDriver):
    _pointer_active = False

    def start_application_mode(self) -> None:
        super().start_application_mode()
        if not self._pointer_active:
            self.write(ARROW_POINTER)
            self.flush()
            self._pointer_active = True

    def stop_application_mode(self) -> None:
        try:
            if self._pointer_active:
                self.write(RESTORE_POINTER)
        finally:
            self._pointer_active = False
            # Also handles suspend/resume, including the plain OAuth URL view.
            super().stop_application_mode()
