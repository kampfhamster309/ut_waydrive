#!/usr/bin/env python3
"""Forward a TCP port (for desk testing): tcp-forward.py <listen_ip> <port> <target_ip> [target_port]"""
import socket, sys, threading

def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    for s in (a, b):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

lip, port, tip = sys.argv[1], int(sys.argv[2]), sys.argv[3]
tport = int(sys.argv[4]) if len(sys.argv) > 4 else port
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((lip, port)); srv.listen(2)
print(f"forwarding {lip}:{port} -> {tip}:{tport}", flush=True)
while True:
    c, addr = srv.accept()
    print("client", addr, flush=True)
    try:
        t = socket.create_connection((tip, tport), timeout=5); t.settimeout(None)
    except OSError as e:
        print("target down:", e, flush=True); c.close(); continue
    for s in (c, t):
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    threading.Thread(target=pipe, args=(c, t), daemon=True).start()
    threading.Thread(target=pipe, args=(t, c), daemon=True).start()
