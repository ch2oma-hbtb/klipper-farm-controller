"""ค้นหาเครื่องพิมพ์ Klipper/Moonraker ใน LAN โดยสแกน port 7125"""
import asyncio
import ipaddress

import httpx

from .config import DEFAULT_MOONRAKER_PORT, HTTP_TIMEOUT


async def _probe(http: httpx.AsyncClient, ip: str, port: int, sem: asyncio.Semaphore):
    async with sem:
        try:
            conn = asyncio.open_connection(ip, port)
            _, writer = await asyncio.wait_for(conn, timeout=0.7)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            return None
        # พอร์ตเปิด — ยืนยันว่าเป็น Moonraker จริง
        try:
            r = await http.get(f"http://{ip}:{port}/server/info", timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            result = r.json().get("result", {})
            if "klippy_connected" not in result and "moonraker_version" not in result:
                return None
            name = None
            try:
                ri = await http.get(f"http://{ip}:{port}/machine/system_info", timeout=HTTP_TIMEOUT)
                name = (ri.json().get("result", {}).get("system_info", {}) or {}).get("cpu_info", {}).get("hostname")
            except Exception:
                pass
            return {
                "host": ip,
                "port": port,
                "moonraker_version": result.get("moonraker_version", ""),
                "klippy_state": result.get("klippy_state", ""),
                "hostname": name or "",
            }
        except Exception:
            return None


async def scan_network(cidr: str, port: int = DEFAULT_MOONRAKER_PORT, max_hosts: int = 1024) -> list[dict]:
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(h) for h in net.hosts()]
    if len(hosts) > max_hosts:
        raise ValueError(f"subnet ใหญ่เกินไป ({len(hosts)} hosts) — จำกัดที่ {max_hosts} (เช่น /22 หรือเล็กกว่า)")
    sem = asyncio.Semaphore(128)
    async with httpx.AsyncClient() as http:
        results = await asyncio.gather(*(_probe(http, ip, port, sem) for ip in hosts))
    return [r for r in results if r]
