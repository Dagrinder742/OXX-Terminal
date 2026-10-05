from flask import Flask, jsonify
import threading
import time

app = Flask(__name__)

# Simulate telemetry errors
telemetry_errors = [
    "Error 1",
    "Error 2",
    "Error 3",
]

# Simulate rendering backend
render_backend = "Webhook"

# Thread to simulate rendering
render_thread = None

def render_backend_thread():
    global render_backend
    while True:
        # Simulate rendering
        print(f"Rendering backend: {render_backend}")
        time.sleep(10)

# Check and hot swap rendering backend
def check_and_hot_swap():
    global render_backend
    for error in telemetry_errors:
        print(f"Detected error: {error}")
        # Simulate error handling
        time.sleep(2)
        print("Error handled, switching to alternative backend.")
        render_backend = "Webhook" if render_backend == "Webhook" else "Local"

# Start the rendering thread
render_thread = threading.Thread(target=render_backend_thread)
render_thread.start()

@app.route('/')
def index():
    global render_backend
    return jsonify({"render_backend": render_backend, "status": "Healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
