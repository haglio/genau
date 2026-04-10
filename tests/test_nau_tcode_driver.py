from __future__ import annotations

from nau.funscript import Funscript
from nau.tcode_driver import (
    FunscriptTCodeDriver,
    UdpTCodeSink,
    format_tcode_command,
)


class TestFormatTCodeCommand:
    def test_basic_format(self):
        assert format_tcode_command("L0", 5000, 33) == "L05000I33"

    def test_clamps_position(self):
        assert format_tcode_command("L0", 10500, 33) == "L09999I33"
        assert format_tcode_command("L0", -1, 33) == "L00000I33"


class FakeSink:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, command: str) -> None:
        self.sent.append(command)

    def close(self) -> None:
        pass


class TestFunscriptTCodeDriver:
    def _make_fs(self):
        return Funscript(actions=[(0, 0), (1000, 100)])

    def test_sends_interpolated_position(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.update(500, self._make_fs(), now=0.0)

        assert len(sink.sent) == 1
        assert sink.sent[0] == "L05000I33"

    def test_sends_zero_at_start(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.update(0, self._make_fs(), now=0.0)

        assert sink.sent[0] == "L00000I33"

    def test_sends_max_at_end(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink)

        driver.update(1000, self._make_fs(), now=0.0)

        assert sink.sent[0] == "L09999I33"

    def test_rate_limits(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink, min_interval=1.0 / 30)
        fs = self._make_fs()

        driver.update(0, fs, now=0.0)
        driver.update(100, fs, now=0.01)  # 10ms later, too soon

        assert len(sink.sent) == 1

    def test_sends_after_interval(self):
        sink = FakeSink()
        driver = FunscriptTCodeDriver(sink, min_interval=1.0 / 30)
        fs = self._make_fs()

        driver.update(0, fs, now=0.0)
        driver.update(500, fs, now=0.05)  # 50ms later, past 33ms interval

        assert len(sink.sent) == 2
