#!/usr/bin/env/python3
from struct import Struct
from collections import deque

MARK = b'\x55\x55'
MARK_LEN = len(MARK)
INT = Struct('i')


sock_data = {}
temp_data = {}


class _udp_to_tcp():

    def __init__(self, udp_sock):
        self.udp_sock = udp_sock

    def recv(self, n):
        return self.udp_sock.recvfrom(n)[0]


def recv_command_udp(udp_socket):
    return recv_command_from(_udp_to_tcp(udp_socket))


def recv_command_from(socket):
    res = _recv_command_from(socket)

    while res == 'need_more':
        res = _recv_command_from(socket)
    return res


def _recv_command_from(socket):
    if socket not in sock_data:
        sock_data[socket] = deque([])
    elif len(sock_data[socket]):
        return sock_data[socket].pop()

    # find message markers
    def recv(n):
        recvd = socket.recv(n)
        if not recvd:
            raise ConnectionAbortedError('Client disconnected.')
        return recvd

    recvd = recv(1024)
    recvd = recvd.split(MARK)

    recvd_len = len(recvd)

    rest, new = recvd[0], recvd[1:]

    if recvd_len == 1:
        if rest[-1] == MARK[0]:
            if recv(1)[0] == MARK[1]:
                new.append(b'')

    if rest and temp_data.get(socket, 'nothing') != 'nothing':
        new = [temp_data[socket] + rest] + new
        temp_data[socket] = 'nothing'

    for msg in new:
        i = INT.size
        if len(msg) < i + 1:
            temp_data[socket] = msg
            return 'need_more'

        args_length = INT.unpack(msg[:i])[0]
        command = msg[i: i + 1]

        args = msg[i + 1: i + 1 + args_length]

        if len(args) < args_length:
            temp_data[socket] = msg
            return 'need_more'

        sock_data[socket].appendleft((command, args))

        extra = msg[i + 1 + args_length:]
        if extra and extra[-1] == MARK[0]:
            if recv(1)[0] == MARK[1]:
                temp_data[socket] = b''

    return 'need_more'


def make_command(command, args=None):
    # type check
    if not args:
        args = b''
    if isinstance(args, str):
        args = args.encode('utf-8')
    elif isinstance(args, bytes):
        pass
    else:
        raise TypeError('"args" should be instance of str or bytes')

    if len(command) > 1:
        raise ValueError(
            'command == one byte in range 00-ff, not %s' % command)

    args_length = len(args)

    if isinstance(command, str):
        command = bytes(command, 'ascii')

    # compulsory bytes
    message = MARK + INT.pack(args_length) + command

    if args_length:
        message += args

    return message
