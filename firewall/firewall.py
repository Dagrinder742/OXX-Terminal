import socket
import sys

# Configuration
BIND_HOST = '127.0.0.1'
BIND_PORT = 8080
TARGET_HOST = '127.0.0.1'
TARGET_PORT = 9000  # Where safe traffic gets forwarded

# Simple Blocklist (IP addresses or subnets)
BLOCKED_IPS = {'192.168.1.100', '10.0.0.99'}

def run_firewall_proxy():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((BIND_HOST, BIND_PORT))
    server_socket.listen(5)
    
    print(f"[*] Python Firewall active on {BIND_HOST}:{BIND_PORT}")
    
    try:
        while True:
            client_socket, client_address = server_socket.accept()
            client_ip = client_address[0]
            
            # 1. Rule Evaluation
            if client_ip in BLOCKED_IPS:
                print(f"[BLOCKED] Connection attempt denied from restricted IP: {client_ip}")
                client_socket.close()
                continue
                
            print(f"[ALLOWED] Connection accepted from: {client_ip}")
            
            # 2. Forward traffic to destination (Simplified single-connection handler)
            try:
                target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                target_socket.connect((TARGET_HOST, TARGET_PORT))
                
                # In a production script, you would use select/asyncio here 
                # to pipe data bidirectionally between client_socket and target_socket.
                
            except Exception as e:
                print(f"[ERROR] Failed to reach target backend: {e}")
            finally:
                client_socket.close()
                
    except KeyboardInterrupt:
        print("\n[*] Shutting down Python firewall.")
    finally:
        server_socket.close()

if __name__ == '__main__':
    run_firewall_proxy()

