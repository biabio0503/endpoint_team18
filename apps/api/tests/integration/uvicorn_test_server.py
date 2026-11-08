import socket
import threading
import time
import uvicorn


class TestServer:
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(128)
        self.server_port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_level='error'))
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [self.socket]}, daemon=True)
        self.thread.start()
        for _ in range(500):
            if self.server.started:
                return
            time.sleep(.01)
        raise RuntimeError('Uvicorn failed to start')

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()
