"""API smoke test with the mock robot running inside the same process (`ezra-udp serve --mock`)."""

from fastapi.testclient import TestClient

from drds_udp.server import create_app


def test_serve_with_builtin_mock():
    mock = dict(host="127.0.0.1", udp_port=0, dtls_port=0, tcp_port=0, tls_port=0, verbose=False)
    with TestClient(create_app(None, mock=mock)) as c:
        ports = c.get("/api/health").json()["mock"]
        assert set(ports) == {"udp", "dtls", "tcp", "tls"}
        r = c.post("/api/session/connect", json={"transport": "dtls", "host": "127.0.0.1", "port": ports["dtls"]})
        assert r.status_code == 200 and r.json()["state"] == "connected"
        r = c.post("/api/send", json={"command_id": "location_get"}).json()
        assert r["status"] == "ok" and "PosX" in r["response"]["items"]
        assert c.post("/api/session/disconnect").json()["state"] == "disconnected"


def test_serve_without_mock_reports_none():
    with TestClient(create_app(None)) as c:
        assert c.get("/api/health").json()["mock"] is None
