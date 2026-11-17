"""A local wall clock that keeps ticking independently of account polling."""

from datetime import datetime

from textual.widgets import Static


class HeaderClock(Static):
    def __init__(self):
        super().__init__(id="clock", markup=False)

    def on_mount(self) -> None:
        self.update_time()
        self.set_interval(1, self.update_time)

    def update_time(self) -> None:
        now = datetime.now().astimezone()
        self.update(now.strftime("%H:%M:%S %Z"))
