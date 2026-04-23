import pytest
from myapp.models import ServerConfig


def test_server_config_creation():
    config = ServerConfig(host="localhost", port=8080)
    assert config.host == "localhost"
    assert config.port == 8080


def test_server_config_to_dict():
    config = ServerConfig(host="localhost", port=9000, debug=True)
    d = config.to_dict()
    assert d["port"] == 9000
    assert d["debug"] is True


def test_server_config_validation_fails():
    # INTENTIONAL FAILURE: invalid port raises ValueError, test expects True
    config = ServerConfig(host="localhost", port=99999)
    assert config.validate() is True
