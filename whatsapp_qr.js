const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const fs = require('fs');
const path = require('path');
const express = require('express');

const app = express();
app.use(express.json());
const port = process.env.NODE_PORT || 3001;

let isReady = false;
let clientInitialized = false;

// Initialize the WhatsApp client
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: { 
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

// Start Express server immediately
const httpServer = app.listen(port, '0.0.0.0', () => {
    console.log(`WhatsApp API running on port ${port}`);
});

// API endpoint to send a message
app.post('/send-message', async (req, res) => {
    if (!isReady) {
        return res.status(400).json({ 
            success: false, 
            message: 'WhatsApp client not ready. Please login first.'
        });
    }

    try {
        const { recipient, message } = req.body;
        if (!recipient || !message) {
            return res.status(400).json({ 
                success: false, 
                message: 'Both recipient and message are required'
            });
        }

        // Format the recipient number (ensure it has the correct format)
        let formattedNumber = recipient;
        if (!formattedNumber.includes('@c.us')) {
            formattedNumber = `${formattedNumber.replace(/[^\d]/g, '')}@c.us`;
        }

        // Check if contact exists
        const contact = await client.getContactById(formattedNumber);
        if (!contact) {
            return res.status(404).json({ 
                success: false, 
                message: 'Contact not found'
            });
        }

        // Send the message
        const sentMessage = await client.sendMessage(formattedNumber, message);
        return res.json({ 
            success: true, 
            message: 'Message sent successfully',
            messageId: sentMessage.id._serialized
        });
    } catch (error) {
        console.error('Error sending message:', error);
        return res.status(500).json({ 
            success: false, 
            message: 'Failed to send message',
            error: error.message
        });
    }
});

// API endpoint to get all chats
app.get('/get-chats', async (req, res) => {
    if (!isReady) {
        return res.status(400).json({ 
            success: false, 
            message: 'WhatsApp client not ready. Please login first.'
        });
    }

    try {
        const chats = await client.getChats();
        const simplifiedChats = chats.map(chat => ({
            id: chat.id._serialized,
            name: chat.name,
            isGroup: chat.isGroup,
            unreadCount: chat.unreadCount
        }));
        
        return res.json({
            success: true,
            chats: simplifiedChats
        });
    } catch (error) {
        console.error('Error fetching chats:', error);
        return res.status(500).json({ 
            success: false, 
            message: 'Failed to fetch chats',
            error: error.message
        });
    }
});

// API endpoint to get chat history with a contact
app.get('/get-chat-history/:contact', async (req, res) => {
    if (!isReady) {
        return res.status(400).json({ 
            success: false, 
            message: 'WhatsApp client not ready. Please login first.'
        });
    }

    try {
        const { contact } = req.params;
        const limit = parseInt(req.query.limit) || 100;
        
        // Format the contact if needed
        let chatId = contact;
        if (!chatId.includes('@c.us') && !chatId.includes('@g.us')) {
            chatId = `${chatId.replace(/[^\d]/g, '')}@c.us`;
        }

        // Get the chat
        const chat = await client.getChatById(chatId);
        if (!chat) {
            return res.status(404).json({ 
                success: false, 
                message: 'Chat not found'
            });
        }

        // Load the messages
        const messages = await chat.fetchMessages({ limit });
        const formattedMessages = messages.map(msg => ({
            id: msg.id._serialized,
            body: msg.body,
            fromMe: msg.fromMe,
            timestamp: msg.timestamp,
            type: msg.type
        }));

        return res.json({
            success: true,
            contact: chatId,
            messages: formattedMessages
        });
    } catch (error) {
        console.error('Error fetching chat history:', error);
        return res.status(500).json({ 
            success: false, 
            message: 'Failed to fetch chat history',
            error: error.message
        });
    }
});

// API endpoint to check server status
app.get('/status', (req, res) => {
    res.json({
        success: true,
        clientInitialized,
        clientReady: isReady
    });
});

// WhatsApp client event handlers
client.on('qr', async (qr) => {
    const qrPath = path.join(__dirname, 'static', 'whatsapp_qr.png');
    await QRCode.toFile(qrPath, qr);
    console.log('QR code generated');
    
    // Mark client as initialized even if not fully ready
    clientInitialized = true;
});

client.on('ready', () => {
    console.log('Client is ready!');
    isReady = true;
    clientInitialized = true;
    
    // Create success flag file
    const flagPath = path.join(__dirname, 'static', 'login_success.flag');
    fs.writeFileSync(flagPath, '');
    console.log('Login success flag created');
});

client.on('disconnected', () => {
    console.log('Client disconnected');
    isReady = false;
});

// Initialize the client
client.initialize();
console.log('WhatsApp client initialization started');

// Handle graceful shutdown
process.on('SIGINT', () => {
    console.log('Shutting down WhatsApp API server...');
    if (httpServer) httpServer.close();
    process.exit();
});
