"""Socket RFCOMM integrado ao main loop do GLib, com fila de envio não bloqueante."""

from __future__ import annotations

import errno
import socket
from typing import Callable

from gi.repository import GLib

from ..i18n import _

_READ_SIZE = 4096
_MAX_QUEUE = 64 * 1024


class Link:
    """Recebe um fd já conectado (do BlueZ ou de `connect_rfcomm`) e troca bytes sem bloquear."""

    def __init__(
        self,
        fd: int,
        on_data: Callable[[bytes], None],
        on_closed: Callable[[str | None], None],
    ) -> None:
        self._sock = socket.socket(fileno=fd)
        self._sock.setblocking(False)
        self._on_data = on_data
        self._on_closed = on_closed
        self._out = bytearray()
        self._write_watch: int | None = None
        self._read_watch: int | None = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            self._sock.fileno(),
            GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self._on_readable,
        )

    @property
    def open(self) -> bool:
        return self._read_watch is not None

    def send(self, data: bytes) -> None:
        if not self.open:
            raise OSError(errno.ENOTCONN, _("Not connected to the earbuds"))
        if len(self._out) + len(data) > _MAX_QUEUE:
            raise OSError(errno.ENOBUFS, _("Send queue is full"))
        self._out.extend(data)
        self._flush()

    def close(self, reason: str | None = None, notify: bool = True) -> None:
        if not self.open:
            return
        self._teardown()
        if notify:
            self._on_closed(reason)

    def _flush(self) -> None:
        while self._out:
            try:
                sent = self._sock.send(self._out, socket.MSG_DONTWAIT)
            except BlockingIOError:
                break
            except OSError as exc:
                GLib.idle_add(self._fail, str(exc))
                return
            del self._out[:sent]
        if self._out and self._write_watch is None:
            self._write_watch = GLib.unix_fd_add_full(
                GLib.PRIORITY_DEFAULT, self._sock.fileno(), GLib.IOCondition.OUT, self._on_writable
            )

    def _on_writable(self, _fd, _condition) -> bool:
        self._write_watch = None
        self._flush()
        return GLib.SOURCE_REMOVE

    def _on_readable(self, _fd: int, condition: GLib.IOCondition) -> bool:
        if condition & GLib.IOCondition.IN:
            try:
                data = self._sock.recv(_READ_SIZE, socket.MSG_DONTWAIT)
            except BlockingIOError:
                return GLib.SOURCE_CONTINUE
            except OSError as exc:
                self._read_watch = None
                self._fail(str(exc))
                return GLib.SOURCE_REMOVE
            if data:
                self._on_data(data)
                return GLib.SOURCE_CONTINUE
            self._read_watch = None
            self._fail(_("The earbuds closed the connection"))
            return GLib.SOURCE_REMOVE
        self._read_watch = None
        self._fail(_("Connection lost"))
        return GLib.SOURCE_REMOVE

    def _fail(self, reason: str) -> bool:
        if self._sock.fileno() < 0:
            return GLib.SOURCE_REMOVE
        self._teardown()
        self._on_closed(reason)
        return GLib.SOURCE_REMOVE

    def _teardown(self) -> None:
        for attr in ("_read_watch", "_write_watch"):
            source = getattr(self, attr)
            if source is not None:
                GLib.source_remove(source)
                setattr(self, attr, None)
        self._out.clear()
        try:
            self._sock.close()
        except OSError:
            pass


def connect_rfcomm(
    address: str,
    channel: int,
    on_connected: Callable[[int], None],
    on_error: Callable[[str], None],
) -> None:
    """Conexão RFCOMM direta num canal conhecido, sem o Profile1 do BlueZ (diagnóstico)."""
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.setblocking(False)
    err = sock.connect_ex((address, channel))
    if err not in (0, errno.EINPROGRESS, errno.EAGAIN):
        sock.close()
        on_error(f"RFCOMM {address} canal {channel}: {errno.errorcode.get(err, err)}")
        return

    def on_writable(_fd: int, _condition: GLib.IOCondition) -> bool:
        result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if result:
            sock.close()
            on_error(f"RFCOMM {address} canal {channel}: {errno.errorcode.get(result, result)}")
        else:
            on_connected(sock.detach())
        return GLib.SOURCE_REMOVE

    GLib.unix_fd_add_full(
        GLib.PRIORITY_DEFAULT,
        sock.fileno(),
        GLib.IOCondition.OUT | GLib.IOCondition.ERR | GLib.IOCondition.HUP,
        on_writable,
    )
