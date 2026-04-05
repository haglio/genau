"""Voice control module for Genau standalone mode.

Uses Vosk (offline speech recognition) with a restricted grammar to
recognize voice commands and write them to the command file, where
the refresh controller picks them up via consume_command_file.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

VOICE_COMMANDS: dict[str, str] = {
    "pause": "PAUSE",
    "play": "RESUME",
    "resume": "RESUME",
    "slow down": "SPEED_DOWN",
    "speed down": "SPEED_DOWN",
    "speed up": "SPEED_UP",
    "amp down": "AMPLITUDE_DOWN",
    "amp up": "AMPLITUDE_UP",
    "center down": "CENTER_DOWN",
    "center up": "CENTER_UP",
    "cycle shape": "CYCLE_SHAPE",
    "cruise control": "TOGGLE_CRUISE",
    "cruise on": "CRUISE_ON",
    "cruise off": "CRUISE_OFF",
    "previous clip": "PREV",
    "next clip": "NEXT",
}

_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "one hundred": 100,
}

for _word, _value in _NUMBER_WORDS.items():
    VOICE_COMMANDS[f"amp {_word}"] = f"AMP {_value}"
    VOICE_COMMANDS[f"center {_word}"] = f"CENTER {_value}"
    VOICE_COMMANDS[f"speed {_word}"] = f"SPEED {_value}"

try:
    import vosk
    import sounddevice as sd
except Exception:
    vosk = None  # type: ignore[assignment]
    sd = None  # type: ignore[assignment]

VOICE_AVAILABLE: bool = vosk is not None and sd is not None

logger = logging.getLogger(__name__)


def parse_vosk_result(
    raw_json: str,
    commands: dict[str, str],
    threshold: float,
) -> str | None:
    """Parse a Vosk recognizer result and return the mapped command, or None.

    Returns None if the text is empty, unknown, or if average per-word
    confidence is below *threshold*.  When Vosk omits confidence data
    (common in grammar mode), the phrase is accepted.
    """
    data = json.loads(raw_json)
    text = data.get("text", "").strip()
    if not text or text == "[unk]":
        return None
    command = commands.get(text)
    if command is None:
        return None
    words = data.get("result")
    if words:
        avg_conf = sum(w.get("conf", 0) for w in words) / len(words)
        if avg_conf < threshold:
            return None
    return command


def build_grammar(commands: dict[str, str]) -> str:
    """Build a Vosk grammar JSON string from command phrase keys."""
    phrases = sorted(commands.keys())
    phrases.append("[unk]")
    return json.dumps(phrases)


class VoiceListener:
    """Listens for voice commands and writes them to the Genau command file."""

    def __init__(
        self,
        *,
        commands: dict[str, str],
        cmd_file: Path | str,
        model_path: str,
        confidence_threshold: float = 0.7,
        device_index: int | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self.commands = commands
        self.cmd_file = Path(cmd_file)
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.device_index = device_index
        self.sample_rate = sample_rate
        self._stop = threading.Event()

    def _write_command(self, command: str) -> None:
        """Write a command to the Genau command file."""
        self.cmd_file.write_text(command, encoding="utf-8")

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._stop.set()

    def run(self) -> None:
        """Blocking listen loop — call from a daemon thread."""
        if not VOICE_AVAILABLE:
            raise ImportError("vosk and sounddevice are required for voice control")

        import queue as _queue

        audio_q: _queue.Queue[bytes] = _queue.Queue()

        def _callback(indata, frames, _time_info, status):
            if status:
                logger.debug("audio status: %s", status)
            audio_q.put(bytes(indata))

        try:
            model = vosk.Model(model_name=self.model_path)
            grammar = build_grammar(self.commands)
            rec = vosk.KaldiRecognizer(model, self.sample_rate, grammar)
            logger.info(
                "Voice control listening (model=%s, rate=%d, device=%s)",
                self.model_path, self.sample_rate, self.device_index,
            )

            with sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=8000,
                dtype="int16",
                channels=1,
                device=self.device_index,
                callback=_callback,
            ):
                while not self._stop.is_set():
                    try:
                        data = audio_q.get(timeout=0.5)
                    except _queue.Empty:
                        continue
                    if rec.AcceptWaveform(data):
                        result = rec.Result()
                        command = parse_vosk_result(
                            result, self.commands, self.confidence_threshold,
                        )
                        if command:
                            logger.info("Voice command: %s", command)
                            self._write_command(command)

            logger.info("Voice control stopped")
        except Exception:
            logger.exception("Voice control thread crashed")
