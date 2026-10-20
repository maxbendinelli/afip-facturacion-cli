#!/usr/bin/env python3
"""
Lanzador de la Interfaz Gráfica Web de ARCA / AFIP Facturación.
Inicia el servidor local FastAPI y abre automáticamente el navegador web.
"""
import os
import sys
import time
import socket
import threading
import webbrowser
import uvicorn


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def open_browser(url: str) -> None:
    time.sleep(1.2)
    # Intentar abrir en Windows si estamos bajo WSL
    if "microsoft" in os.uname().release.lower() or os.path.exists("/proc/version"):
        try:
            os.system(f"cmd.exe /c start {url} 2>/dev/null")
            return
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    host = "127.0.0.1"
    port = 8000

    # Buscar puerto disponible si 8000 está ocupado
    while is_port_in_use(port, host):
        port += 1

    url = f"http://{host}:{port}"
    print("=" * 65)
    print("  🚀 ARCA / AFIP Facturación Electrónica - Interfaz Web")
    print(f"  🌐 Servidor local: {url}")
    print("  💡 Presione Ctrl+C en esta terminal para detener el servidor")
    print("=" * 65)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    uvicorn.run(
        "web_server:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
