# coding: utf-8
import socket
import threading
import json
import base64
import hashlib
import struct

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jugon Mic</title>
  <style>
    body { background: #111; color: #fff; font-family: sans-serif; text-align: center; padding: 20px; }
    input { font-size: 18px; padding: 10px; width: 80%; margin: 10px auto; border-radius: 8px; border: none; }
    button { font-size: 20px; padding: 14px 28px; background: #00d2ff; color: #000; font-weight: bold; border: none; border-radius: 10px; cursor: pointer; }
    #log { margin-top: 20px; font-size: 18px; color: #0f0; min-height: 50px; }
  </style>
</head>
<body>
  <h2>📢 Jugon Mic</h2>
  <input id="p" placeholder="Gamertag"><br>
  <button id="b" onclick="start()">START MIC</button>
  <div id="log">Ready</div>

  <script>
    let ws, rec;
    function start() {
      const p = document.getElementById("p").value.trim();
      if (!p) return alert("Enter Gamertag");
      
      ws = new WebSocket("ws://" + location.host + "/ws/mic");
      ws.onopen = () => { document.getElementById("log").innerText = "Connected! Speak now."; };
      ws.onclose = () => { document.getElementById("log").innerText = "Disconnected."; };

      window.SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!window.SpeechRecognition) {
        alert("Speech Recognition not supported in this browser.");
        return;
      }
      rec = new SpeechRecognition();
      rec.continuous = true;
      rec.interimResults = false;
      rec.lang = "ja-JP";

      rec.onresult = (e) => {
        const text = e.results[e.results.length - 1][0].transcript.trim();
        document.getElementById("log").innerText = "Heard: " + text;
        if (ws && ws.readyState === 1) {
          ws.send(JSON.stringify({ player: p, text: text }));
        }
      };

      rec.onend = () => rec.start();
      rec.start();
      document.getElementById("b").disabled = true;
      document.getElementById("b").innerText = "Listening...";
    }
  </script>
</body>
</html>"""

clients = set()
lock = threading.Lock()

def make_ws_frame(msg):
    data = msg.encode("utf-8")
    length = len(data)
    if length <= 125:
        return struct.pack("!BB", 129, length) + data
    elif length <= 65535:
        return struct.pack("!BBH", 129, 126, length) + data
    else:
        return struct.pack("!BBQ", 129, 127, length) + data

def send_cmd(cmd_line):
    pkt = {
        "header": {
            "version": 1,
            "requestId": "a0000000-0000-0000-0000-000000000001",
            "messagePurpose": "commandRequest",
            "messageType": "commandRequest"
        },
        "body": {
            "version": 1,
            "commandLine": cmd_line,
            "origin": {"type": "player"}
        }
    }
    raw = make_ws_frame(json.dumps(pkt))
    with lock:
        dead = []
        for c in list(clients):
            try:
                c.sendall(raw)
            except:
                dead.append(c)
        for d in dead:
            clients.discard(d)

def handle_client(conn, addr):
    global clients
    try:
        data = conn.recv(4096)
        if not data:
            conn.close()
            return
        headers = data.decode("utf-8", "ignore").split("\r\n")
        path = headers[0].split()[1] if len(headers[0].split()) > 1 else "/"
        
        ws_key = None
        for h in headers:
            if h.lower().startswith("sec-websocket-key:"):
                ws_key = h.split(":", 1)[1].strip()
                break

        # HTTP ブラウザアクセス
        if not ws_key:
            res = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(HTML.encode('utf-8'))}\r\n"
                "Connection: close\r\n\r\n"
                + HTML
            )
            conn.sendall(res.encode("utf-8"))
            conn.close()
            return

        # WebSocket ハンドシェイク
        accept = base64.b64encode(hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("utf-8")).digest()).decode("utf-8")
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        conn.sendall(handshake.encode("utf-8"))

        if "/ws/mic" in path:
            # Safari からの音声受信
            while True:
                buf = conn.recv(2)
                if not buf or len(buf) < 2:
                    break
                masked = (buf[1] & 128) != 0
                plen = buf[1] & 127
                if plen == 126:
                    plen = struct.unpack("!H", conn.recv(2))[0]
                elif plen == 127:
                    plen = struct.unpack("!Q", conn.recv(8))[0]
                mask = conn.recv(4) if masked else None
                raw = conn.recv(plen)
                msg_bytes = bytes(b ^ mask[i % 4] for i, b in enumerate(raw)) if masked else raw
                try:
                    payload = json.loads(msg_bytes.decode("utf-8", "ignore"))
                    p = payload.get("player")
                    t = payload.get("text")
                    if t:
                        print(f">> [VOICE] {p}: {t}")
                        send_cmd(f"scriptevent jugon:voice {p}:{t}")
                except:
                    pass
        else:
            # マイクラ接続確立
            with lock:
                clients.add(conn)
            print(">> [★ MC CONNECTED & VERIFIED!]")
            send_cmd("say §a[呪言サーバー] 接続成功！リンク完了しました！")
            while True:
                buf = conn.recv(1024)
                if not buf:
                    break
    except:
        pass
    finally:
        with lock:
            clients.discard(conn)
        conn.close()

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()

    print(f"\n==========================================")
    print(f"URL: http://localhost:8080")
    print(f"CMD: /connect {ip}:8080")
    print(f"==========================================\n")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 8080))
    srv.listen(10)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()

