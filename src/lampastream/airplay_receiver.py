"""Manager-owned receiver ingress with exclusive standby/analysis read ownership."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class AirPlayReceiver:
    """Keep the sole FIFO reader alive while another player owns the lights.

    A closed read end produces EPIPE in an already-playing receiver. A blocked
    pipe can stall its output too. Standby drains decoded audio without analysing
    it. Acquisition joins that reader before the canonical worker can read;
    release happens only after that worker has stopped. Failed joins retain all
    ownership and descriptors for a safe retry.
    """

    def __init__(self, source):
        self.source = source
        self.opened = False
        self.leased = False
        self._stop = threading.Event()
        self._thread = None
        self._error = None

    def start(self):
        if not self.opened:
            self.source.open()
            self.opened = True
        if self.leased or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(target=self._drain, name="airplay-standby", daemon=True)
        self._thread.start()

    def _drain(self):
        try:
            while not self._stop.is_set():
                self.source.read()
                self._stop.wait(0.002)
        except Exception as error:
            self._error = error
            log.exception("Standby receiver reader failed")

    def _join(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError(
                    "Receiver reader is still retiring; retry without closing its source"
                )
            self._thread = None

    def acquire(self):
        self._join()
        if self._error is not None:
            raise RuntimeError("Receiver reader failed") from self._error
        self.leased = True
        return self.source

    def release(self):
        self.leased = False
        self.start()

    def close(self):
        if self.leased:
            raise RuntimeError("Analysis still owns receiver source; retry teardown first")
        self._join()
        if self.opened:
            self.source.close()
            self.opened = False
