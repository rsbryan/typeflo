from pathlib import Path
from queue import Queue
import logging
from threading import Thread
from time import perf_counter


class Worker(Thread):
    def __init__(self):
        super().__init__(name="typeflo-inference", daemon=True)
        self.commands = Queue()
        self.events = Queue()
        self.recorder = None
        self.pipeline = None

    def run(self):
        from .app import Pipeline
        from .audio import Recorder, read_wav

        microphone = None
        while True:
            command, payload = self.commands.get()
            try:
                if command == "quit":
                    if self.recorder:
                        self.recorder.close()
                    return
                if command == "load":
                    self.pipeline = Pipeline(payload, self.pipeline)
                    import mlx.core as mx

                    self.events.put(("ready", {"config": payload, "startup": self.pipeline.startup,
                                               "memory_gb": round(mx.get_active_memory() / 1e9, 2)}))
                elif command == "start":
                    session, pressed_at, config = payload
                    device = None if config.microphone == "default" else config.microphone
                    if self.recorder is None or microphone != config.microphone:
                        if self.recorder:
                            self.recorder.close()
                        self.recorder = Recorder(device)
                        microphone = config.microphone
                    self.recorder.start()
                    self.events.put(("started", (session, (perf_counter() - pressed_at) * 1000)))
                elif command == "stop":
                    session, released_at, held_ms = payload
                    samples = self.recorder.stop()
                    stopped = perf_counter()
                    result = self.pipeline.process(samples)
                    result.timings.update(capture_stop_ms=round((stopped - released_at) * 1000, 2),
                                          capture_hold_ms=round(held_ms, 2))
                    self.events.put(("result", (session, result, released_at, perf_counter())))
                elif command == "cancel":
                    if self.recorder:
                        self.recorder.stop()
                    self.events.put(("cancelled", payload))
                elif command == "benchmark":
                    samples = read_wav(Path(payload))
                    results = [self.pipeline.process(samples) for _ in range(3)]
                    self.events.put(("benchmark", results))
            except Exception as error:
                logging.exception("%s failed", command)
                self.events.put(("error", (command, str(error))))
