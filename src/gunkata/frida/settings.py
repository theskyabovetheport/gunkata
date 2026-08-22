"""Environment-resolved settings for provisioning and connecting to frida-server."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FridaSettings(BaseSettings):
    """How frida-server is provisioned, run, and connected to.

    Attributes:
        device_path: Where the frida-server binary lives on the device.
        port: Loopback TCP port frida-server binds on the device.
        start_timeout_seconds: How long to wait for a launched frida-server to
            start answering pidof before giving up.
        stop_grace_seconds: How long to wait for a killed frida-server to exit
            before escalating to SIGKILL.
        poll_interval_seconds: How often to re-check pidof while awaiting
            either of the state changes above.
        connect_timeout_seconds: How long FridaServer.get_device waits for the
            device to appear and its server to answer before giving up.
        connect_poll_seconds: How often FridaServer.get_device re-probes
            server readiness while waiting.
        autodownload_server_binary: Whether ServerRepo may fetch a missing
            frida-server release archive from frida's GitHub releases
            instead of refusing.
        assume_running: Whether FridaServer should trust that frida-server is
            already running rather than probe the device for it. See
            FridaServer's class docstring for the consequences.

    Design:
        Same shape as SuBinary: one BaseSettings per concern, built explicitly
        wherever a caller needs frida config, rather than each FridaServer
        method restating its own copy of these defaults -- the single
        identity a value like ``port`` or ``connect_timeout_seconds`` should
        carry.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    device_path: str = Field(
        "/data/local/tmp/frida-server", validation_alias="GUNKATA_FRIDA_DEVICE_PATH"
    )
    port: int = Field(27042, validation_alias="GUNKATA_FRIDA_PORT")
    start_timeout_seconds: float = Field(
        10.0, validation_alias="GUNKATA_FRIDA_START_TIMEOUT_SECONDS"
    )
    stop_grace_seconds: float = Field(
        3.0, validation_alias="GUNKATA_FRIDA_STOP_GRACE_SECONDS"
    )
    poll_interval_seconds: float = Field(
        0.1, validation_alias="GUNKATA_FRIDA_POLL_INTERVAL_SECONDS"
    )
    connect_timeout_seconds: float = Field(
        10.0, validation_alias="GUNKATA_FRIDA_CONNECT_TIMEOUT_SECONDS"
    )
    connect_poll_seconds: float = Field(
        0.25, validation_alias="GUNKATA_FRIDA_CONNECT_POLL_SECONDS"
    )
    autodownload_server_binary: bool = Field(
        False, validation_alias="GUNKATA_FRIDA_AUTODOWNLOAD_SERVER_BINARY"
    )
    assume_running: bool = Field(
        False, validation_alias="GUNKATA_FRIDA_ASSUME_RUNNING"
    )
