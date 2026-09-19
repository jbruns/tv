import socket
from typing import Any, Never, cast


class UnexpectedSocketError(RuntimeError):
    pass


class GuardedSocket(socket.socket):
    def __new__(cls, *args: object, **kwargs: object) -> Never:
        del cls, args, kwargs
        raise UnexpectedSocketError("unexpected socket use in offline test")


def reject_socket_use(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise UnexpectedSocketError("unexpected socket use in offline test")


def install() -> None:
    socket_module = cast(Any, socket)
    socket_module.socket = GuardedSocket
    socket_module.SocketType = GuardedSocket
    socket_module.create_connection = reject_socket_use
    socket_module.create_server = reject_socket_use
    socket_module.fromfd = reject_socket_use
    socket_module.socketpair = reject_socket_use
    if hasattr(socket, "fromshare"):
        socket_module.fromshare = reject_socket_use
