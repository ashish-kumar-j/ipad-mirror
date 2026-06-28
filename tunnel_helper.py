"""
Standalone tunnel helper – bundled inside the .app by PyInstaller.
Called as:  sudo <path>/tunnel_helper
Outputs:    HOST PORT  (one line to stdout) then blocks until killed.

Uses non-CLI pymobiledevice3 APIs directly to avoid importing inquirer3/readchar,
which fail when their dist-info is missing in the bundle.
"""
import asyncio
import sys


async def _run():
    from pymobiledevice3.remote.tunnel_service import get_core_device_tunnel_services
    from pymobiledevice3.remote.module_imports import MAX_IDLE_TIMEOUT, start_tunnel
    from pymobiledevice3.remote.common import TunnelProtocol

    services = await get_core_device_tunnel_services()
    if not services:
        print("ERROR: no iOS device found via USB", flush=True)
        sys.exit(1)

    service = services[0]
    async with start_tunnel(
        service,
        secrets=None,
        max_idle_timeout=MAX_IDLE_TIMEOUT,
        protocol=TunnelProtocol.TCP,
    ) as result:
        # script-mode: print host and port for the parent process to parse
        print(f"{result.address} {result.port}", flush=True)
        await result.client.wait_closed()


def main():
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
