## Features

- Scan QR to connect WhatsApp
- Real-time login status updates (WebSocket)
- Send WhatsApp messages from a web UI
- View chat history and active chats
- Auto-restart Node.js process if needed

## Tech Stack

- FastAPI (Python)
- whatsapp-web.js (Node.js)
- WebSockets
- Express.js
- HTML/JS Frontend

## Install dependencies

```bash
pip install fastapi uvicorn requests
```
```bash
npm install whatsapp-web.js express qrcode
```

## Run application

```
python main.py

node whatsapp_qr.js
```
or
```
uvicorn main:app --reload
```

## Endpoint Glossary

| Endpoint           | Method | Description               |
| ------------------ | ------ | ------------------------- |
| `/start`           | GET    | Initialize WhatsApp login |
| `/status`          | GET    | Get login status          |
| `/qr`              | GET    | Get QR code image         |
| `/send-message`    | POST   | Send a message            |
| `/chats`           | GET    | List active chats         |
| `/chats/{contact}` | GET    | Get chat history          |
