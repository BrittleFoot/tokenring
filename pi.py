import socket as sk
from collections import deque
from multiprocessing import Value, Queue
from command import COMMAND
from select import select
from proto import recv_command_udp, make_command
from time import sleep, time


filters = (
    '1337',
    'world123'
)


def log(message):

    if all([filter in message for filter in filters]):
        print(message)


def read_available(socket):
    return select([socket], [], [], 0)[0]


class Pi:

    def __init__(self):
        self.this = None
        self.next = None
        self.id = None
        self.local_events = Queue()
        self.global_events = deque([])
        self.unhandled_events = []
        self.mq = deque([])
        self.token = False
        self.ltt = 0
        self.world = {}
        self.is_started = Value('b', False)
        self.event_handler = {
            COMMAND.MOVE: self.on_move
        }

    def log(self, message):
        log(f"{self.__class__.__name__}#{self.id}: {message}")

    def configure_this(self, host, port):
        self.this = sk.socket(sk.AF_INET, sk.SOCK_DGRAM)
        self.this.bind((host, port))
        self.id = port
        self.is_started.value = True
        self.vector = list

    def configure_next(self, host, port):
        self.next = sk.socket(sk.AF_INET, sk.SOCK_DGRAM)
        self.next.connect((host, port))

    def __enter__(self):
        self.is_started.value = True
        return self

    def work(self):

        while self.is_started.value:
            if read_available(self.this):
                command, args = recv_command_udp(self.this)
                self.process_command(command, args)

            self.transfer_messages()
            self.dispatch_local_events()

            self.update_world_state()
            self.draw()

    def process_command(self, command, args):
        if command == COMMAND.TOKEN:
            self.log(f"token catched!")
            self.token_catched_event()
            self.throw_token()
            return

        self.mq.append((command, args))
        self.global_events.append((command, args))

    def throw_token(self):
        self.apply_world_changes()

        self.next.send(make_command(COMMAND.TOKEN))
        self.log(f"token thrown!")

    def token_catched_event(self):
        t = time()
        if not self.ltt:
            self.log("it is my first time ^o^")
        else:
            self.log(f'token rtt is: {t - self.ltt}s')
        self.ltt = t

    def send_signed(self, command, bytes):
        return self.send_next(command, self.sign(bytes))

    def send_next(self, command, bytes):
        self.next.send(make_command(command, bytes))
        self.log(f"sent {command}:{bytes}")

    def sign(self, bytes):
        return self.id.to_bytes(2, 'big') + bytes

    def apply_world_changes(self):
        self.log(f"{len(self.global_events)} events to handle")
        self.unhandled_events = self.global_events
        self.global_events = deque([])

    def signed_by_me(self, bytes):
        if len(bytes) < 2:
            return False
        signature = bytes[:2]
        return signature == self.id.to_bytes(2, 'big')

    def unwrap(self, bytes):
        if len(bytes) < 2:
            return b'', bytes
        return bytes[:2], bytes[2:]

    def transfer_messages(self):
        while len(self.mq) > 0:
            cmd, args = self.mq.popleft()

            if self.signed_by_me(args):
                self.log("my message returned!")
                continue

            self.send_next(cmd, args)

    def dispatch_local_events(self):
        events = []
        try:
            while not self.local_events.empty():
                events.append(self.local_events.get(False))
        except Queue.Empty:
            pass

        for e in events:
            self.send_signed(*e)

    def update_world_state(self):
        for cmd, args in self.unhandled_events:
            signature, arg = self.unwrap(args)
            if signature not in self.world:
                self.world[signature] = self.vector((0, 0))

            self.event_handler[cmd](signature, args)

        self.unhandled_events = []

    def draw(self):
        self.log(f"world {self.world}")

    def stop(self):
        self.is_started.value = False

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.is_started.value = False
        if self.this is not None:
            self.this.close()
        if self.next is not None:
            self.next.close()
        self.log("socket closed")

    def on_move(self, signature, args):

        x, y = 0, 0
        x -= b'a' in args
        x += b'd' in args
        y -= b'w' in args
        y += b's' in args
        sx, sy = self.world[signature]

        self.world[signature] = self.vector((sx + x, sy + y))
