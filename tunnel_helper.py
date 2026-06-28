"""
Standalone tunnel helper – bundled inside the .app by PyInstaller.
Called as:  sudo <path>/tunnel_helper  (macOS)
            <path>/tunnel_helper.exe   (Windows, already admin via UAC)
Outputs:    HOST PORT  (one line to stdout) then blocks until killed.

Avoids CLI imports (inquirer3/readchar) which fail without dist-info in bundles.
"""
import asyncio
import sys


async def _run_macos():
    """macOS: use Bonjour-discovered CoreDeviceTunnelService."""
    from pymobiledevice3.remote.tunnel_service import get_core_device_tunnel_services
    from pymobiledevice3.remote.module_imports import MAX_IDLE_TIMEOUT, start_tunnel
    from pymobiledevice3.remote.common import TunnelProtocol

    services = await get_core_device_tunnel_services()
    if not services:
        print("ERROR: no iOS device found via USB", flush=True)
        sys.exit(1)

    async with start_tunnel(services[0], secrets=None,
                            max_idle_timeout=MAX_IDLE_TIMEOUT,
                            protocol=TunnelProtocol.TCP) as result:
        print(f"{result.address} {result.port}", flush=True)
        await result.client.wait_closed()


async def _run_windows():
    """Windows: use usbmux lockdown + CoreDeviceTunnelProxy (TCP, no wintun needed)."""
    from pymobiledevice3.usbmux import select_devices_by_connection_type
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.remote.tunnel_service import CoreDeviceTunnelProxy, TunnelProtocol
    from pymobiledevice3.remote.module_imports import MAX_IDLE_TIMEOUT, start_tunnel

    devs = await select_devices_by_connection_type("USB")
    if not devs:
        print("ERROR: no iOS device found via USB", flush=True)
        sys.exit(1)

    lockdown = await create_using_usbmux(serial=devs[0].serial)
    service = await CoreDeviceTunnelProxy.create(lockdown)

    async with start_tunnel(service, secrets=None,
                            max_idle_timeout=MAX_IDLE_TIMEOUT,
                            protocol=TunnelProtocol.TCP) as result:
        print(f"{result.address} {result.port}", flush=True)
        await result.client.wait_closed()


def main():
    try:
        if sys.platform == "win32":
            asyncio.run(_run_windows())
        else:
            asyncio.run(_run_macos())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
