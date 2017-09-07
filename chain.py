#!/usr/bin/env python3

import socket as sk
import argparse as arp
import sfml
import math
import os

from time import sleep, time
from collections import deque
from select import select
from threading import Thread
from multiprocessing import Process, Value, Queue, Manager
from proto import recv_command_udp, make_command
from pi import Pi
from sfml import sf
from command import COMMAND


def log(msg):
    print(msg)


def twograms(iterable):
    last = None
    i = 0
    for elem in iterable:
        if i != 0:
            yield (last, elem)
        last = elem
        i = 1


def vlen(v):
    x, y = v
    return math.sqrt(x * x + y * y)


class SyncPi(Pi):
    """
        We can manually rewrite fields that need to be synchronized :)
    """

    def __init__(self):
        self._s_ltt = Value('d', 0)
        super(SyncPi, self).__init__()

    @property
    def ltt(self):
        return self._s_ltt.value

    @ltt.setter
    def ltt(self, value):
        self._s_ltt.value = value


class PiCloth(sf.CircleShape):

    def __init__(self, pi, rad):
        sf.CircleShape.__init__(self, rad)
        self.pi = pi
        self.rad = rad

    @property
    def rad(self):
        return self.radius

    @rad.setter
    def rad(self, value):
        self.radius = value
        self.origin = sf.Vector2(value, value)

    def draw(self, window, glstates):
        sf.CircleShape.draw(self, window, glstates)

    def under(self, vector):
        return vlen(self.position - vector) <= self.rad

    def resolve_color(self, time, maxbound):
        if self.pi.ltt <= 0:
            self.fill_color = sf.Color(255, 100, 100)
        else:
            color = (1 - max(time - self.pi.ltt, 0) / maxbound)
            g = int(round(color ** 3 * 255))
            self.fill_color = sf.Color(60, g, 50)


def rotate(v, angle):
    x, y = v
    return sf.Vector2(
        x * math.sin(angle) + y * math.cos(angle),
        x * -math.cos(angle) + y * math.sin(angle))


def spawn_pis(config_pairs):
    pis = {}
    for this, nxt in config_pairs:
        pi = SyncPi()
        pi.configure_this('127.0.0.1', this)
        pi.configure_next('127.0.0.1', nxt)
        pis[this] = pi
    return pis


def place_in_circle(clothes, winsize):
    m = min(winsize.x, winsize.y) / 2
    l = len(clothes)
    min_angle = 1 / l * math.pi * 2
    for i, cloth in enumerate(clothes):
        angle = min_angle * i

        cloth.rad = min_angle * m / 4
        vector = rotate(sf.Vector2(1, 0), angle) * (m - cloth.rad - 10)
        cloth.position += vector


def play_with_selected(selected):
    move_bytes = b''.join((
        [b'', b'w'][sf.Keyboard.is_key_pressed(sf.Keyboard.W)],
        [b'', b'a'][sf.Keyboard.is_key_pressed(sf.Keyboard.A)],
        [b'', b's'][sf.Keyboard.is_key_pressed(sf.Keyboard.S)],
        [b'', b'd'][sf.Keyboard.is_key_pressed(sf.Keyboard.D)]
    ))

    if move_bytes:
        selected.pi.local_events.put((COMMAND.MOVE, move_bytes))


def get_cloth_under(clothes, v):
    for c in clothes:
        if c.under(v):
            return c
    return None


def mainloop(pis):

    size = sf.Vector2(1024, 600)
    vmode = sf.VideoMode(1024, 600)
    view = sf.View()
    view.size = size
    view.center = sf.Vector2(0, 0)
    window = sf.RenderWindow(vmode, "tokenring", sf.Style.FULLSCREEN)
    window.framerate_limit = 60
    window.view = view

    clothes = [PiCloth(pi, 30) for p, pi in sorted(pis.items())]
    place_in_circle(clothes, size)

    selected_player = None
    observable_cloth = None
    world = None

    brush = sf.CircleShape(10)

    while window.is_open:
        for event in window.events:
            if event == sf.Event.CLOSED:
                window.close()
            if event == sf.Event.MOUSE_BUTTON_PRESSED:
                if event['button'] == sfml.window.Button.RIGHT:
                    v = sf.Vector2(event['x'], event['y']) - size / 2
                    oc = get_cloth_under(clothes, v)
                    if oc:
                        observable_cloth = oc

        t = time()
        maxtime = max(t - c.pi.ltt for c in clothes if c.pi.ltt > 0)

        mp = sf.Mouse.get_position(window)
        mp -= size / 2

        selected_player = None
        for c in clothes:
            c.resolve_color(t, maxtime)
            if c.under(mp):
                selected_player = c

        if observable_cloth:
            observable_cloth.fill_color = sf.Color.BLUE
            world = observable_cloth.pi.world

        if selected_player:
            selected_player.fill_color = sf.Color.YELLOW
            play_with_selected(selected_player)

        window.clear(sf.Color.BLACK)

        for c in clothes:
            window.draw(c)

        if world:
            for id, (x, y) in world.items():
                id = int.from_bytes(id, 'big')
                brush.position = sf.Vector2(x, y) * 5
                window.draw(brush)

        window.display()

    list(map(Pi.stop, pis.values()))


def novisualise_mainloop(pis):
    while True:
        try:
            sleep(0.1)
        except KeyboardInterrupt:
            print("^C")
            list(map(Pi.stop, pis.values()))
            return


def main(args):
    portrange = range(args.initial_port, args.initial_port + args.ncount)
    portrange = list(portrange)
    portrange.append(portrange[0])

    sync_manager = Manager()

    log(f"This instances will be spawned: {portrange}")

    def hire_pi(pi):
        try:
            with pi:
                pi.work()
        except KeyboardInterrupt:
            print(f"{os.getpid()}: ^C")

    pis = spawn_pis(twograms(portrange))
    for pi in pis.values():
        pi.world = sync_manager.dict()
        pi.vector = tuple
        Process(target=hire_pi, args=(pi,)).start()

    sleep(0.1)
    initiator = sk.socket(sk.AF_INET, sk.SOCK_DGRAM)
    initiator.sendto(make_command(COMMAND.TOKEN), ('127.0.0.1', portrange[0]))

    mainloop(pis)
    return


def parse_args():
    parser = arp.ArgumentParser()
    aa = parser.add_argument

    def uint(x):
        if x > 0:
            return x
        else:
            raise ValueError(x)

    aa("initial_port", type=int)
    aa("ncount", type=int, nargs='?', default=3)

    return parser.parse_args()

if __name__ == '__main__':
    main(parse_args())
