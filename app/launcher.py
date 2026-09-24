import socket
import threading
import time
import webbrowser
import uvicorn


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=lambda: (time.sleep(.8), webbrowser.open(url)), daemon=True).start()
    print(f"BoodschappenWijzer is gestart op {url}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
