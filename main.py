import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import subprocess
import os
import time
import signal
import asyncio
import requests
from typing import Optional

# Node.js API endpoint
NODE_API = os.getenv("NODE_API", "http://localhost:3001")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()
wa_process = None

def check_qr():
    return os.path.exists("static/whatsapp_qr.png")

async def check_login():
    flag_path = os.path.join("static", "login_success.flag")
    if os.path.exists(flag_path):
        return True
    return False

def check_node_server():
    """Check if Node.js server is running"""
    try:
        response = requests.get(f"{NODE_API}/status", timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

async def ensure_server_running():
    """Make sure server is running, if not start it"""
    global wa_process
    
    # First check if Node server is responding
    if check_node_server():
        return True
        
    # If server not responding, but process exists, kill it
    if wa_process is not None:
        try:
            os.kill(wa_process.pid, signal.SIGTERM)
            await asyncio.sleep(1)
        except ProcessLookupError:
            pass
        wa_process = None
    
    # Start new Node.js process
    if wa_process is None:
        # Clean old files
        for f in ["static/whatsapp_qr.png", "static/login_success.flag"]:
            if os.path.exists(f):
                os.remove(f)
        
        wa_process = subprocess.Popen(
            ["node", "whatsapp_qr.js"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # Wait a bit for server to start
        await asyncio.sleep(3)
        return check_node_server()
    
    return False

async def process_watcher():
    """Monitor the Node.js process and restart if needed"""
    global wa_process
    while True:
        try:
            # Check if server is running
            server_running = check_node_server()
            
            # Check login status
            logged_in = await check_login()
            
            if logged_in:
                # If logged in, broadcast to all clients
                await manager.broadcast("login_success")
            
            # If server not running and not logged in, try to restart
            if not server_running and not logged_in:
                await ensure_server_running()
                
        except Exception as e:
            print(f"Error in process watcher: {e}")
            
        await asyncio.sleep(5)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Wait for any message from client
            await websocket.receive_text()
            
            logged_in = await check_login()
            qr_available = check_qr()
            node_running = check_node_server()
            
            # Send status back to client
            await websocket.send_json({
                "qr_available": qr_available,
                "logged_in": logged_in,
                "server_running": node_running
            })
            
            # Short wait to avoid tight loop
            await asyncio.sleep(0.5)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.on_event("startup")
async def startup_event():
    # Start the watcher task
    asyncio.create_task(process_watcher())
    
    # Make sure Node.js server is running at startup
    await ensure_server_running()

@app.get("/start", summary="Initialize WhatsApp login")
async def start_login():
    """Start or restart the WhatsApp login process"""
    if await ensure_server_running():
        return {"status": "initialized", "server_running": True}
    return {"status": "error", "server_running": False, "message": "Could not start Node.js server"}

@app.get("/qr", response_class=FileResponse, summary="Get QR code image")
async def get_qr():
    """Get the WhatsApp QR code image"""
    if check_qr():
        return "static/whatsapp_qr.png"
    
    # Try to start the server if QR not available
    if await ensure_server_running():
        # Wait briefly for QR to be generated
        await asyncio.sleep(2)
        if check_qr():
            return "static/whatsapp_qr.png"
            
    raise HTTPException(status_code=404, detail="QR not generated yet")

@app.get("/status", summary="Check login status")
async def get_status():
    """Check the WhatsApp login status"""
    node_running = check_node_server()
    logged_in = await check_login()
    qr_available = check_qr()
    
    return {
        "logged_in": logged_in,
        "qr_available": qr_available,
        "server_running": node_running
    }

@app.post("/send-message")
async def send_message(recipient: str, message: str):
    """Send a WhatsApp message to a specific recipient"""
    # Ensure the Node.js server is running
    if not await ensure_server_running():
        raise HTTPException(status_code=503, detail="WhatsApp API server not available")
    
    try:
        response = requests.post(
            f"{NODE_API}/send-message",
            json={"recipient": recipient, "message": message},
            timeout=10
        )
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chats")
async def list_chats():
    """Get a list of active WhatsApp chats"""
    # Ensure the Node.js server is running
    if not await ensure_server_running():
        raise HTTPException(status_code=503, detail="WhatsApp API server not available")
    
    try:
        response = requests.get(f"{NODE_API}/get-chats", timeout=10)
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chats/{contact}")
async def get_chat_history(contact: str, limit: int = 100):
    """Get chat history with a specific contact"""
    # Ensure the Node.js server is running
    if not await ensure_server_running():
        raise HTTPException(status_code=503, detail="WhatsApp API server not available")
    
    try:
        response = requests.get(
            f"{NODE_API}/get-chat-history/{contact}",
            params={"limit": limit},
            timeout=10
        )
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    """Return the WhatsApp UI"""
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <title>WhatsApp Integration</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    line-height: 1.6;
                }
                .container {
                    max-width: 800px;
                    margin: 0 auto;
                }
                h1 {
                    color: #075E54;
                }
                button {
                    background-color: #128C7E;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 16px;
                    margin: 10px 0;
                }
                button:hover {
                    background-color: #075E54;
                }
                #status {
                    margin: 20px 0;
                    padding: 15px;
                    border-radius: 5px;
                    background-color: #f9f9f9;
                }
                #qr-container {
                    margin: 20px 0;
                    text-align: center;
                }
                #qr-container img {
                    max-width: 300px;
                    border: 1px solid #ddd;
                }
                .hidden {
                    display: none;
                }
                #message-form {
                    margin-top: 20px;
                    padding: 15px;
                    background-color: #f9f9f9;
                    border-radius: 5px;
                }
                input, textarea {
                    width: 100%;
                    padding: 8px;
                    margin: 5px 0 15px;
                    box-sizing: border-box;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                }
                textarea {
                    height: 100px;
                    resize: vertical;
                }
                #send-result {
                    margin-top: 15px;
                    font-weight: bold;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>WhatsApp Integration</h1>
                
                <div id="login-section">
                    <button onclick="startLogin()">Connect WhatsApp</button>
                    <div id="status">Checking status...</div>
                    <div id="qr-container" class="hidden"></div>
                </div>
                
                <div id="message-form" class="hidden">
                    <h2>Send Message</h2>
                    <div>
                        <label for="recipient">Recipient (phone number with country code):</label>
                        <input type="text" id="recipient" placeholder="+1234567890">
                    </div>
                    <div>
                        <label for="message">Message:</label>
                        <textarea id="message" placeholder="Enter your message here"></textarea>
                    </div>
                    <button onclick="sendMessage()">Send Message</button>
                    <div id="send-result"></div>
                </div>
            </div>
            
            <script>
                // WebSocket connection
                let ws = new WebSocket(`ws://${window.location.host}/ws`);
                let statusCheckInterval;
                
                // Check initial status when page loads
                window.onload = function() {
                    checkStatus();
                    
                    // Set up WebSocket
                    ws.onopen = function() {
                        console.log("WebSocket connected");
                        sendWSPing();
                    };
                    
                    ws.onclose = function() {
                        console.log("WebSocket disconnected");
                        // Try to reconnect
                        setTimeout(function() {
                            ws = new WebSocket(`ws://${window.location.host}/ws`);
                        }, 3000);
                    };
                    
                    ws.onmessage = function(event) {
                        if (event.data === "login_success") {
                            updateUIForLogin(true);
                            return;
                        }
                        
                        try {
                            const data = JSON.parse(event.data);
                            updateStatusDisplay(data);
                        } catch (e) {
                            console.error("Error parsing WebSocket message:", e);
                        }
                    };
                };
                
                // Ping the WebSocket periodically to get status updates
                function sendWSPing() {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send("ping");
                        setTimeout(sendWSPing, 3000);
                    }
                }
                
                // Start the login process
                function startLogin() {
                    fetch('/start')
                        .then(response => response.json())
                        .then(data => {
                            console.log("Login process started:", data);
                            document.getElementById('status').innerHTML = "Starting WhatsApp connection...";
                            // Check status every few seconds
                            clearInterval(statusCheckInterval);
                            statusCheckInterval = setInterval(checkStatus, 3000);
                        })
                        .catch(error => {
                            console.error('Error starting login:', error);
                            document.getElementById('status').innerHTML = 
                                '❌ Error: Could not start WhatsApp connection';
                        });
                }
                
                // Check the current login status
                function checkStatus() {
                    fetch('/status')
                        .then(response => response.json())
                        .then(data => {
                            updateStatusDisplay(data);
                        })
                        .catch(error => {
                            console.error('Error checking status:', error);
                            document.getElementById('status').innerHTML = 
                                '❌ Error connecting to server';
                        });
                }
                
                // Update the UI based on status response
                function updateStatusDisplay(data) {
                    const statusDiv = document.getElementById('status');
                    const qrContainer = document.getElementById('qr-container');
                    
                    if (!data.server_running) {
                        statusDiv.innerHTML = '❌ WhatsApp server not running. Try clicking "Connect WhatsApp"';
                        statusDiv.style.color = 'red';
                        qrContainer.classList.add('hidden');
                        return;
                    }
                    
                    if (data.logged_in) {
                        updateUIForLogin(true);
                        return;
                    }
                    
                    if (data.qr_available) {
                        updateQR();
                        statusDiv.innerHTML = '⌛ Scan the QR code with your WhatsApp app to login';
                        statusDiv.style.color = 'orange';
                        qrContainer.classList.remove('hidden');
                    } else {
                        statusDiv.innerHTML = '⌛ Waiting for QR code generation...';
                        statusDiv.style.color = 'orange';
                        qrContainer.classList.add('hidden');
                    }
                }
                
                // Update the QR code image
                function updateQR() {
                    const qrContainer = document.getElementById('qr-container');
                    const qrUrl = '/qr?t=' + new Date().getTime(); // Add timestamp to prevent caching
                    
                    qrContainer.innerHTML = `<img src="${qrUrl}" alt="WhatsApp QR Code">`;
                }
                
                // Update UI when login is successful
                function updateUIForLogin(success) {
                    const statusDiv = document.getElementById('status');
                    const qrContainer = document.getElementById('qr-container');
                    const messageForm = document.getElementById('message-form');
                    
                    if (success) {
                        statusDiv.innerHTML = '✅ WhatsApp connected successfully!';
                        statusDiv.style.color = 'green';
                        qrContainer.classList.add('hidden');
                        messageForm.classList.remove('hidden');
                        clearInterval(statusCheckInterval);
                    } else {
                        statusDiv.innerHTML = '❌ WhatsApp connection failed';
                        statusDiv.style.color = 'red';
                        messageForm.classList.add('hidden');
                    }
                }
                
                // Send a WhatsApp message
                function sendMessage() {
                    const recipient = document.getElementById('recipient').value.trim();
                    const message = document.getElementById('message').value.trim();
                    const resultDiv = document.getElementById('send-result');
                    
                    if (!recipient || !message) {
                        resultDiv.innerHTML = "Please enter both recipient and message";
                        resultDiv.style.color = 'red';
                        return;
                    }
                    
                    const params = new URLSearchParams({
                        recipient: recipient,
                        message: message
                    });
                    
                    resultDiv.innerHTML = "Sending message...";
                    resultDiv.style.color = 'blue';
                    
                    fetch('/send-message?' + params.toString(), {
                        method: 'POST'
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            resultDiv.innerHTML = "✅ Message sent successfully!";
                            resultDiv.style.color = 'green';
                            document.getElementById('message').value = ''; // Clear message field
                        } else {
                            resultDiv.innerHTML = `❌ Error: ${data.message || 'Failed to send message'}`;
                            resultDiv.style.color = 'red';
                        }
                    })
                    .catch(error => {
                        console.error('Error sending message:', error);
                        resultDiv.innerHTML = "❌ Error: Could not send message";
                        resultDiv.style.color = 'red';
                    });
                }
            </script>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
