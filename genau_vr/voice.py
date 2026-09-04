"""Voice control — Vosk offline speech recognition.

Copied from Genau's voice.py.
"""
from __future__ import annotations

import json
import logging
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
    "louder": "VOLUME_UP",
    "quieter": "VOLUME_DOWN",
    "quit": "QUIT",
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
    import sounddevice as sd
    import vosk
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
    phrases = sorted(commands.keys())
    phrases.append("[unk]")
    return json.dumps(phrases)


class VoiceListener:
    """Un-stoppable by design: :meth:`run` is handed to a daemon thread and the
    listener itself is dropped, so the loop ends when the process does and the
    audio stream is torn down with it."""

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

    def _write_command(self, command: str) -> None:
        self.cmd_file.write_text(command, encoding="utf-8")

    def run(self) -> None:
        if not VOICE_AVAILABLE:
            raise ImportError("vosk and sounddevice are required for voice control")

        import queue as _queue

        audio_q: _queue.Queue[bytes] = _queue.Queue()

        def _callback(indata, frames, _time_info, status):  # noqa: ARG001 (sounddevice's signature)
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
                while True:
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
        except Exception:
            logger.exception("Voice control thread crashed")
