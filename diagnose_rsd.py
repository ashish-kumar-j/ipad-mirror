"""
Run this after starting the tunnel:
  sudo python3 -m pymobiledevice3 remote start-tunnel --script-mode
Then:
  python3 diagnose_rsd.py <host> <port>
"""
import asyncio, sys

async def main(host, port):
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
    print(f"Connecting to RSD at {host}:{port} ...")
    async with RemoteServiceDiscoveryService((host, port)) as rsd:
        print(f"Connected — iOS {rsd.product_version}  UDID: {rsd.udid}")
        print(f"Lockdown available: {rsd.lockdown is not None}")

        services = rsd.peer_info.get("Services", {})
        print(f"\nTotal RSD services: {len(services)}")
        for name in sorted(services):
            port_n = services[name].get("Port", "?")
            print(f"  {name:60s} port={port_n}")

        if rsd.lockdown:
            print("\nLockdown values (product):")
            try:
                val = await rsd.lockdown.get_value(None, "ProductVersion")
                print(" ProductVersion:", val)
            except Exception as e:
                print(" error:", e)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 diagnose_rsd.py <host> <port>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
