server_url = "http://localhost:8080"  # target for task4 rename


class ServerConfig:
    def __init__(self, host, port, debug=False, url=None):
        self.host = host
        self.port = port
        self.debug = debug
        self.url = url or server_url
        print(f"Config created for {self.url}")  # target for print→logging task

    def to_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "debug": self.debug,
            "url": self.url,
        }

    def validate(self):
        # TODO: validate host format
        if not self.host:
            raise ValueError("host is required")
        if not (1 <= self.port <= 65535):
            raise ValueError(f"Invalid port: {self.port}")
        return True
