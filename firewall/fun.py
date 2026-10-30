import socket
import select
import sys
import time

# Configuration
FIREWALL_HOST = '127.0.0.1'
FIREWALL_PORT = 8080       # Port your Benchmark/Agent talks to
LLM_SERVER_HOST = '127.0.0.1'
LLM_SERVER_PORT = 8081     # Port your llama-server is listening on

# Strict, high-risk execution commands to guard against
DANGEROUS_PAYLOADS = [b"os.system(", b"subprocess.Popen(", b"rm -rf /", b"__import__('os')"]

GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def log_packet(direction, source_ip, data_preview, status):
    timestamp = time.strftime("%H:%M:%S")
    hex_preview = data_preview[:8].hex().upper() if data_preview else "00000000"
    size = len(data_preview)
    line = (f"{CYAN}[{timestamp}]{RESET} {direction} | IP: {source_ip:<12} | "
            f"BYTES: {size:<4} | HEX: 0x{hex_preview} | STATUS: {status}")
    print(line)

def forward_stream(client_sock, backend_sock):
    """Resilient bi-directional streaming pipe that won't cut off LLM token generation."""
    client_sock.setblocking(False)
    backend_sock.setblocking(False)
    
    sockets = [client_sock, backend_sock]
    
    try:
        while True:
            # Wait up to 15 seconds for socket activity (gives the model time to generate)
            readable, _, exceptional = select.select(sockets, [], sockets, 15.0)
            if exceptional or not readable:
                break
            
            for sock in readable:
                try:
                    data = sock.recv(4096)
                    if not data:
                        return  # Connection closed cleanly by peer
                    
                    if sock is client_sock:
                        backend_sock.sendall(data)
                    else:
                        client_sock.sendall(data)
                except (BlockingIOError, ConnectionResetError):
                    continue
    except Exception:
        pass

def handle_client(client_socket, client_addr):
    client_ip = client_addr[0]
    
    try:
        client_socket.setblocking(False)
        ready = select.select([client_socket], [], [], 2.0)
        
        if not ready[0]:
            client_socket.close()
            return
            
        initial_data = client_socket.recv(4096)
        if not initial_data:
            client_socket.close()
            return

        # 1. Firewall Security Check
        is_threat = any(pattern in initial_data for pattern in DANGEROUS_PAYLOADS)

        if is_threat:
            log_packet("INBOUND ", client_ip, initial_data, f"{RED}[DROPPED - HARMFUL PAYLOAD DETECTED]{RESET}")
            forbidden_response = (
                b"HTTP/1.1 403 Forbidden\r\n"
                b"Content-Type: application/json\r\n"
                b"Connection: close\r\n\r\n"
                b'{"error": "Firewall Blocked: Dangerous execution pattern detected"}'
            )
            client_socket.sendall(forbidden_response)
            client_socket.close()
            return

        log_packet("INBOUND ", client_ip, initial_data, f"{GREEN}[ALLOWED -> FORWARDING BENCHMARK]{RESET}")

        # 2. Connect to actual llama-server on port 8081
        backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend_socket.connect((LLM_SERVER_HOST, LLM_SERVER_PORT))
        backend_socket.sendall(initial_data)

        # 3. Open the persistent streaming pipe
        forward_stream(client_socket, backend_socket)

        backend_socket.close()
        client_socket.close()

    except Exception as e:
        print(f"{YELLOW}[!] Error in client handler: {e}{RESET}")
        client_socket.close()

def start_firewall():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((FIREWALL_HOST, FIREWALL_PORT))
    server.listen(10)
    
    print(f"{GREEN}[*] Resilient Matrix Firewall Active on {FIREWALL_HOST}:{FIREWALL_PORT}{RESET}")
    print(f"{CYAN}[*] Forwarding approved benchmark traffic to {LLM_SERVER_HOST}:{LLM_SERVER_PORT}{RESET}\n")

    try:
        while True:
            client_socket, client_addr = server.accept()
            handle_client(client_socket, client_addr)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[*] Shutting down firewall.{RESET}")
    finally:
        server.close()

if __name__ == "__main__":
    start_firewall()

