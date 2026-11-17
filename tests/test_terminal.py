import pytest
from textual.drivers.linux_driver import LinuxDriver

from rhtop.ui.terminal import ARROW_POINTER, RESTORE_POINTER, ArrowPointerDriver


class RecordingDriver(ArrowPointerDriver):
    def __init__(self):
        self.operations = []

    def write(self, data):
        self.operations.append(data)

    def flush(self):
        pass


def test_arrow_pointer_is_scoped_to_application_mode_and_restored_on_suspend(monkeypatch):
    monkeypatch.setattr(
        LinuxDriver, "start_application_mode", lambda self: self.operations.append("start")
    )
    monkeypatch.setattr(
        LinuxDriver, "stop_application_mode", lambda self: self.operations.append("stop")
    )
    monkeypatch.setattr(LinuxDriver, "close", lambda self: None)
    driver = RecordingDriver()
    driver.start_application_mode()
    driver.suspend_application_mode()
    driver.resume_application_mode()
    driver.stop_application_mode()
    assert driver.operations == ["start", ARROW_POINTER, RESTORE_POINTER, "stop"] * 2
    assert not driver._pointer_active


def test_terminal_cleanup_still_runs_if_pointer_restore_fails(monkeypatch):
    monkeypatch.setattr(
        LinuxDriver, "stop_application_mode", lambda self: self.operations.append("stop")
    )
    driver = RecordingDriver()
    driver._pointer_active = True

    def fail_write(data):
        raise OSError("synthetic terminal failure")

    monkeypatch.setattr(driver, "write", fail_write)
    with pytest.raises(OSError):
        driver.stop_application_mode()
    assert driver.operations == ["stop"]
    assert not driver._pointer_active
