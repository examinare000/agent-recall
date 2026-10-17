"""`recall serve --http`（streamable-http トランスポート）の単体テスト。

常駐マシン上で recall を HTTP 公開し、VPN 越しに複数端末から同じ記憶庫を引く経路の検証。
実サーバは起動せず、argparse のサンチネル・優先順位解決の純関数・run() への引数の
渡し方だけを見る。ホスト名・IP は文書用の例示値（RFC 5737 の 192.0.2.0/24 等）。
"""

from __future__ import annotations

import importlib

import pytest

from recall import cli, config
from recall.cli import build_parser
from recall.server import build_transport_security


class _FakeMcpServer:
    def __init__(self) -> None:
        self.run_calls: list[str | None] = []
        self.run_kwargs: list[dict] = []

    def run(self, transport: str | None = None, **kwargs) -> None:
        self.run_calls.append(transport)
        self.run_kwargs.append(kwargs)


class TestServeParser:
    def test_flags_default_to_none_sentinel(self):
        args = build_parser().parse_args(["serve"])
        assert args.http is None
        assert args.host is None
        assert args.port is None
        assert args.allowed_host is None
        assert args.stdio is False

    def test_flags_can_be_set(self):
        args = build_parser().parse_args(
            [
                "serve",
                "--http",
                "--host",
                "192.0.2.10",
                "--port",
                "9000",
                "--allowed-host",
                "host-a.example.ts.net:9000",
                "--allowed-host",
                "host-a",
            ]
        )
        assert args.http is True
        assert args.host == "192.0.2.10"
        assert args.port == 9000
        assert args.allowed_host == ["host-a.example.ts.net:9000", "host-a"]


class TestResolveServeSettings:
    def _args(self, **overrides):
        base = {"http": None, "host": None, "port": None, "allowed_host": None, "stdio": False}
        base.update(overrides)
        return build_parser().parse_args(["serve"]).__class__(**base)

    def test_env_fallback_when_flags_unset(self):
        s = cli.resolve_serve_settings(
            self._args(),
            env_http_enabled=True,
            env_host="192.0.2.1",
            env_port=1234,
            env_allowed_hosts=["a:1234"],
        )
        assert (s.http, s.host, s.port, s.allowed_hosts) == (True, "192.0.2.1", 1234, ["a:1234"])

    def test_flags_win_over_env(self):
        s = cli.resolve_serve_settings(
            self._args(http=True, host="127.0.0.1", port=1, allowed_host=["x"]),
            env_http_enabled=False,
            env_host="192.0.2.1",
            env_port=1234,
            env_allowed_hosts=["a"],
        )
        assert (s.http, s.host, s.port, s.allowed_hosts) == (True, "127.0.0.1", 1, ["x"])

    def test_stdio_flag_wins_over_http_flag_and_env(self):
        s = cli.resolve_serve_settings(
            self._args(http=True, stdio=True),
            env_http_enabled=True,
            env_host="h",
            env_port=1,
            env_allowed_hosts=[],
        )
        assert s.http is False


class TestBindWarning:
    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "192.0.2.10"])
    def test_none_for_single_interface(self, host):
        assert cli._bind_warning(host) is None

    @pytest.mark.parametrize("host", ["0.0.0.0", "::"])
    def test_warns_for_all_interfaces(self, host):
        warning = cli._bind_warning(host)
        assert warning is not None and "全インターフェース" in warning


class TestServeDispatch:
    @pytest.fixture
    def fake_server(self, monkeypatch):
        fake = _FakeMcpServer()
        monkeypatch.setattr(cli, "_build_service", lambda *a, **kw: object())
        monkeypatch.setattr(cli, "create_server", lambda service: fake)
        return fake

    def test_default_is_stdio_without_transport_kwargs(self, fake_server, capsys, monkeypatch):
        monkeypatch.delenv("RECALL_HTTP_ENABLED", raising=False)
        monkeypatch.setattr(cli.config, "HTTP_ENABLED", False)
        cli.main(["serve"])
        assert fake_server.run_calls == [None]
        assert fake_server.run_kwargs == [{}]
        assert capsys.readouterr().err == ""

    def test_http_passes_host_port_and_transport_security(self, fake_server):
        cli.main(
            [
                "serve",
                "--http",
                "--host",
                "192.0.2.10",
                "--port",
                "9000",
                "--allowed-host",
                "host-a.example.ts.net:9000",
            ]
        )
        assert fake_server.run_calls == ["streamable-http"]
        kw = fake_server.run_kwargs[0]
        assert kw["host"] == "192.0.2.10" and kw["port"] == 9000
        # bind 先自身 + 追加指定が許可ホストになる（DNS リバインディング保護は有効のまま）
        sec = kw["transport_security"]
        assert sec.enable_dns_rebinding_protection is True
        assert sec.allowed_hosts == [
            "192.0.2.10:9000",
            "192.0.2.10",
            "host-a.example.ts.net:9000",
        ]

    def test_ipv6_bind_allows_bracketed_host_header(self, fake_server):
        # IPv6 の Host ヘッダは `[::1]:8768` 形式。ブラケット無しの `::1:8768` では一致しない。
        cli.main(["serve", "--http", "--host", "::1", "--port", "8768"])
        sec = fake_server.run_kwargs[0]["transport_security"]
        assert sec.allowed_hosts == ["[::1]:8768", "[::1]"]

    def test_env_http_enabled_triggers_http_without_flag(self, fake_server, monkeypatch):
        monkeypatch.setattr(cli.config, "HTTP_ENABLED", True)
        cli.main(["serve"])
        assert fake_server.run_calls == ["streamable-http"]

    def test_all_interfaces_bind_prints_warning(self, fake_server, capsys):
        cli.main(["serve", "--http", "--host", "0.0.0.0"])
        assert "全インターフェース" in capsys.readouterr().err


class TestHttpConfigEnv:
    @pytest.fixture(autouse=True)
    def _restore_config(self, monkeypatch):
        # reload は module 属性を env 由来に書き換える。monkeypatch の env を戻した後に
        # もう一度 reload して、他テストへ値が漏れないようにする。
        yield
        monkeypatch.undo()
        importlib.reload(config)

    def test_defaults(self, monkeypatch):
        for key in (
            "RECALL_HTTP_ENABLED",
            "RECALL_HTTP_HOST",
            "RECALL_HTTP_PORT",
            "RECALL_ALLOWED_HOSTS",
        ):
            monkeypatch.delenv(key, raising=False)
        cfg = importlib.reload(config)
        assert (cfg.HTTP_ENABLED, cfg.HTTP_HOST, cfg.HTTP_PORT, cfg.ALLOWED_HOSTS) == (
            False,
            "127.0.0.1",
            8768,
            [],
        )

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("RECALL_HTTP_ENABLED", "true")
        monkeypatch.setenv("RECALL_HTTP_HOST", "192.0.2.10")
        monkeypatch.setenv("RECALL_HTTP_PORT", "9000")
        monkeypatch.setenv("RECALL_ALLOWED_HOSTS", "host-a.example.ts.net:9000, host-a,,")
        cfg = importlib.reload(config)
        assert (cfg.HTTP_ENABLED, cfg.HTTP_HOST, cfg.HTTP_PORT) == (True, "192.0.2.10", 9000)
        assert cfg.ALLOWED_HOSTS == ["host-a.example.ts.net:9000", "host-a"]

    def test_invalid_port_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RECALL_HTTP_PORT", "abc")
        cfg = importlib.reload(config)
        assert cfg.HTTP_PORT == 8768


class TestBuildTransportSecurity:
    def test_hosts_and_origins_derived_from_one_list(self):
        sec = build_transport_security(["192.0.2.10:8768", "host-a.example.ts.net:8768"])
        assert sec.enable_dns_rebinding_protection is True
        assert sec.allowed_hosts == ["192.0.2.10:8768", "host-a.example.ts.net:8768"]
        assert sec.allowed_origins == [
            "http://192.0.2.10:8768",
            "http://host-a.example.ts.net:8768",
        ]


class TestHealthRoute:
    """GET /health は systemd 等の死活監視用の無認証エンドポイント。

    custom_route は Host 検査の外にあるため、公開する情報は status/version の 2 つのみ。
    """

    def test_returns_only_status_and_version(self):
        import importlib.metadata

        from starlette.testclient import TestClient

        from recall.server import create_server

        app = create_server(object()).streamable_http_app()
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": importlib.metadata.version("agent-recall"),
        }
