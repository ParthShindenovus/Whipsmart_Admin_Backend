# WebSocket Chat API - Frontend Implementation Guide

This guide provides comprehensive instructions for implementing WebSocket-based real-time chat in your frontend application.

## Table of Contents

1. [Overview](#overview)
2. [WebSocket Endpoint](#websocket-endpoint)
3. [Connection Setup](#connection-setup)
4. [Message Format](#message-format)
5. [Response Format](#response-format)
6. [Implementation Examples](#implementation-examples)
7. [Error Handling](#error-handling)
8. [Best Practices](#best-practices)

## Overview

The WebSocket API provides real-time bidirectional communication for chat functionality. It streams responses word-by-word, similar to the SSE streaming endpoint, but with better performance and lower latency.

**WebSocket URL:** `ws://your-domain.com/ws/chat/` (development)  
**WebSocket URL:** `wss://your-domain.com/ws/chat/` (production)

## WebSocket Endpoint

### Connection URL

```
ws://localhost:8000/ws/chat/  (Development)
wss://api.yourdomain.com/ws/chat/  (Production)
```

### Authentication

Currently, WebSocket connections don't require authentication headers. However, you must provide valid `session_id` and `visitor_id` in each message.

## Connection Setup

### JavaScript/TypeScript Example

```javascript
class ChatWebSocket {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.onMessageCallback = null;
        this.onErrorCallback = null;
        this.onCloseCallback = null;
    }

    connect() {
        try {
            this.ws = new WebSocket(this.url);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.reconnectAttempts = 0;
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                if (this.onErrorCallback) {
                    this.onErrorCallback(error);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                if (this.onCloseCallback) {
                    this.onCloseCallback();
                }
                this.attemptReconnect();
            };

        } catch (error) {
            console.error('Error creating WebSocket connection:', error);
        }
    }

    handleMessage(data) {
        switch (data.type) {
            case 'chunk':
                // Streaming chunk received
                if (this.onMessageCallback) {
                    this.onMessageCallback({
                        type: 'chunk',
                        chunk: data.chunk,
                        done: data.done,
                        messageId: data.message_id
                    });
                }
                break;
            
            case 'complete':
                // Response complete
                if (this.onMessageCallback) {
                    this.onMessageCallback({
                        type: 'complete',
                        responseId: data.response_id,
                        messageId: data.message_id,
                        conversationData: data.conversation_data,
                        complete: data.complete,
                        needsInfo: data.needs_info,
                        suggestions: data.suggestions
                    });
                }
                break;
            
            case 'error':
                // Error received
                if (this.onErrorCallback) {
                    this.onErrorCallback(new Error(data.error));
                }
                break;
        }
    }

    sendMessage(message, sessionId, visitorId) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            const payload = {
                type: 'chat_message',
                message: message,
                session_id: sessionId,
                visitor_id: visitorId
            };
            this.ws.send(JSON.stringify(payload));
        } else {
            console.error('WebSocket is not connected');
        }
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            setTimeout(() => {
                console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`);
                this.connect();
            }, this.reconnectDelay * this.reconnectAttempts);
        }
    }

    close() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    setOnMessage(callback) {
        this.onMessageCallback = callback;
    }

    setOnError(callback) {
        this.onErrorCallback = callback;
    }

    setOnClose(callback) {
        this.onCloseCallback = callback;
    }
}
```

## Message Format

### Sending a Chat Message

```json
{
    "type": "chat_message",
    "message": "What is a novated lease?",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "visitor_id": "660e8400-e29b-41d4-a716-446655440000"
}
```

**Required Fields:**
- `type`: Must be `"chat_message"`
- `message`: The user's message text
- `session_id`: Valid session UUID
- `visitor_id`: Valid visitor UUID

## Standardized Message Schema

All WebSocket messages follow a consistent schema for easy frontend integration. The schema includes common fields that may be `null` or omitted depending on the message type.

### Common Message Schema

```typescript
interface WebSocketMessage {
    type: 'chunk' | 'complete' | 'idle_warning' | 'session_end' | 'error' | 'connected';
    session_id: string | null;           // Session UUID
    message_id: string | null;            // User message ID (for responses)
    response_id: string | null;            // Assistant message ID
    message: string | null;                // Full message text (for complete messages)
    chunk: string | null;                  // Chunk text (for streaming)
    done: boolean;                         // Whether streaming is done
    complete: boolean;                     // Whether session is complete
    conversation_data: object | null;      // Session conversation data
    needs_info: boolean | null;            // Whether more info is needed
    suggestions: string[];                 // Suggested responses
    error: string | null;                  // Error message (if error)
    metadata: object;                      // Additional metadata
}
```

**Note:** Fields that are `null` or empty arrays are omitted from the message to keep payloads clean. Boolean fields (`done`, `complete`) are always included.

## Response Format

### Connection Confirmation (Type: `connected`)

Sent immediately after WebSocket connection is established:

```json
{
    "type": "connected",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "conversation_data": {
        "name": "John Doe",
        "email": "john@example.com"
    },
    "metadata": {
        "status": "connected"
    }
}
```

### Streaming Chunk (Type: `chunk`)

Received multiple times as the response is streamed:

```json
{
    "type": "chunk",
    "chunk": "word ",
    "done": false,
    "message_id": "770e8400-e29b-41d4-a716-446655440000"
}
```

### Complete Response (Type: `complete`)

Received once when streaming is complete:

```json
{
    "type": "complete",
    "response_id": "880e8400-e29b-41d4-a716-446655440000",
    "message_id": "770e8400-e29b-41d4-a716-446655440000",
    "conversation_data": {},
    "complete": false,
    "needs_info": null,
    "suggestions": [
        "What are the benefits?",
        "How do I get started?",
        "What vehicles are available?"
    ]
}
```

### Idle Warning (Type: `idle_warning`)

Sent after 2 minutes of inactivity:

```json
{
    "type": "idle_warning",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "G'day! Are you still there? I'm here if you need anything!",
    "response_id": "990e8400-e29b-41d4-a716-446655440000",
    "metadata": {
        "type": "idle_warning",
        "timeout_seconds": 120
    }
}
```

### Session End (Type: `session_end`)

Sent after 4 minutes of inactivity (2 minutes after idle warning):

```json
{
    "type": "session_end",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "No worries! I'll end this session for now. Feel free to come back anytime if you need help!",
    "response_id": "aa0e8400-e29b-41d4-a716-446655440000",
    "complete": true,
    "conversation_data": {},
    "metadata": {
        "type": "session_end",
        "reason": "idle_timeout",
        "timeout_seconds": 240
    }
}
```

### Error Response (Type: `error`)

```json
{
    "type": "error",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "error": "Session not found",
    "metadata": {
        "error_type": "processing_error"
    }
}
```

## Implementation Examples

### React Example

```jsx
import React, { useState, useEffect, useRef } from 'react';

const ChatComponent = ({ sessionId, visitorId }) => {
    const [messages, setMessages] = useState([]);
    const [currentResponse, setCurrentResponse] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const wsRef = useRef(null);

    useEffect(() => {
        // Initialize WebSocket connection
        const ws = new ChatWebSocket('ws://localhost:8000/ws/chat/');
        
        ws.setOnMessage((data) => {
            if (data.type === 'chunk') {
                setCurrentResponse(prev => prev + data.chunk);
            } else if (data.type === 'complete') {
                // Add complete message to messages array
                setMessages(prev => [...prev, {
                    id: data.responseId,
                    role: 'assistant',
                    content: currentResponse,
                    suggestions: data.suggestions
                }]);
                setCurrentResponse('');
                setIsStreaming(false);
            }
        });

        ws.setOnError((error) => {
            console.error('WebSocket error:', error);
            setIsStreaming(false);
        });

        ws.connect();
        wsRef.current = ws;

        return () => {
            ws.close();
        };
    }, [sessionId, visitorId]);

    const sendMessage = (message) => {
        if (wsRef.current && !isStreaming) {
            setIsStreaming(true);
            setMessages(prev => [...prev, {
                id: Date.now().toString(),
                role: 'user',
                content: message
            }]);
            wsRef.current.sendMessage(message, sessionId, visitorId);
        }
    };

    return (
        <div className="chat-container">
            <div className="messages">
                {messages.map(msg => (
                    <div key={msg.id} className={`message ${msg.role}`}>
                        {msg.content}
                    </div>
                ))}
                {isStreaming && (
                    <div className="message assistant streaming">
                        {currentResponse}
                        <span className="cursor">|</span>
                    </div>
                )}
            </div>
            <input
                type="text"
                onKeyPress={(e) => {
                    if (e.key === 'Enter' && !isStreaming) {
                        sendMessage(e.target.value);
                        e.target.value = '';
                    }
                }}
                disabled={isStreaming}
            />
        </div>
    );
};

export default ChatComponent;
```

### Vue.js Example

```vue
<template>
    <div class="chat-container">
        <div class="messages">
            <div
                v-for="message in messages"
                :key="message.id"
                :class="['message', message.role]"
            >
                {{ message.content }}
            </div>
            <div v-if="isStreaming" class="message assistant streaming">
                {{ currentResponse }}<span class="cursor">|</span>
            </div>
        </div>
        <input
            v-model="inputMessage"
            @keypress.enter="sendMessage"
            :disabled="isStreaming"
        />
    </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue';

export default {
    props: {
        sessionId: String,
        visitorId: String
    },
    setup(props) {
        const messages = ref([]);
        const currentResponse = ref('');
        const isStreaming = ref(false);
        const inputMessage = ref('');
        let ws = null;

        onMounted(() => {
            ws = new ChatWebSocket('ws://localhost:8000/ws/chat/');
            
            ws.setOnMessage((data) => {
                if (data.type === 'chunk') {
                    currentResponse.value += data.chunk;
                } else if (data.type === 'complete') {
                    messages.value.push({
                        id: data.responseId,
                        role: 'assistant',
                        content: currentResponse.value,
                        suggestions: data.suggestions
                    });
                    currentResponse.value = '';
                    isStreaming.value = false;
                }
            });

            ws.setOnError((error) => {
                console.error('WebSocket error:', error);
                isStreaming.value = false;
            });

            ws.connect();
        });

        onUnmounted(() => {
            if (ws) {
                ws.close();
            }
        });

        const sendMessage = () => {
            if (ws && !isStreaming.value && inputMessage.value.trim()) {
                isStreaming.value = true;
                messages.value.push({
                    id: Date.now().toString(),
                    role: 'user',
                    content: inputMessage.value
                });
                ws.sendMessage(inputMessage.value, props.sessionId, props.visitorId);
                inputMessage.value = '';
            }
        };

        return {
            messages,
            currentResponse,
            isStreaming,
            inputMessage,
            sendMessage
        };
    }
};
</script>
```

### Vanilla JavaScript Example

```html
<!DOCTYPE html>
<html>
<head>
    <title>WebSocket Chat</title>
    <style>
        .chat-container {
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }
        .messages {
            height: 400px;
            overflow-y: auto;
            border: 1px solid #ccc;
            padding: 10px;
            margin-bottom: 10px;
        }
        .message {
            margin-bottom: 10px;
            padding: 8px;
            border-radius: 4px;
        }
        .message.user {
            background-color: #e3f2fd;
            text-align: right;
        }
        .message.assistant {
            background-color: #f5f5f5;
        }
        .message.streaming {
            font-style: italic;
        }
        .cursor {
            animation: blink 1s infinite;
        }
        @keyframes blink {
            0%, 50% { opacity: 1; }
            51%, 100% { opacity: 0; }
        }
        input {
            width: 100%;
            padding: 10px;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <div class="chat-container">
        <div id="messages" class="messages"></div>
        <input
            type="text"
            id="messageInput"
            placeholder="Type your message..."
        />
    </div>

    <script>
        // Include ChatWebSocket class here (from above)
        
        const sessionId = 'YOUR_SESSION_ID';
        const visitorId = 'YOUR_VISITOR_ID';
        const ws = new ChatWebSocket('ws://localhost:8000/ws/chat/');
        const messagesDiv = document.getElementById('messages');
        const messageInput = document.getElementById('messageInput');
        let currentResponse = '';
        let isStreaming = false;

        ws.setOnMessage((data) => {
            if (data.type === 'chunk') {
                currentResponse += data.chunk;
                updateStreamingMessage();
            } else if (data.type === 'complete') {
                addMessage('assistant', currentResponse);
                currentResponse = '';
                isStreaming = false;
            }
        });

        ws.setOnError((error) => {
            console.error('WebSocket error:', error);
            addMessage('system', `Error: ${error.message}`);
            isStreaming = false;
        });

        ws.connect();

        function addMessage(role, content) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}`;
            messageDiv.textContent = content;
            messagesDiv.appendChild(messageDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function updateStreamingMessage() {
            const existingStreaming = document.querySelector('.message.streaming');
            if (existingStreaming) {
                existingStreaming.textContent = currentResponse + '|';
            } else {
                isStreaming = true;
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message assistant streaming';
                messageDiv.textContent = currentResponse + '|';
                messagesDiv.appendChild(messageDiv);
            }
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !isStreaming && messageInput.value.trim()) {
                addMessage('user', messageInput.value);
                ws.sendMessage(messageInput.value, sessionId, visitorId);
                messageInput.value = '';
            }
        });
    </script>
</body>
</html>
```

## Error Handling

### Common Errors

1. **"Session not found"**
   - Ensure the session_id is valid and exists
   - Create a new session if needed

2. **"Session is not active"**
   - Session may have been completed or deleted
   - Create a new session

3. **"Session has expired"**
   - Sessions expire after 24 hours
   - Create a new session

4. **"Visitor ID does not match"**
   - Ensure visitor_id matches the session's visitor
   - Use the correct visitor_id

5. **"message is required"**
   - Ensure the message field is included and not empty

### Error Handling Example

```javascript
ws.setOnError((error) => {
    const errorMessage = error.message || 'An unknown error occurred';
    
    // Handle specific errors
    if (errorMessage.includes('Session not found')) {
        // Redirect to create new session
        createNewSession();
    } else if (errorMessage.includes('expired')) {
        // Show expiration message and offer to create new session
        showExpirationMessage();
    } else {
        // Show generic error
        showErrorMessage(errorMessage);
    }
});
```

## Best Practices

### 1. Connection Management

- **Reconnect Logic**: Implement automatic reconnection with exponential backoff
- **Connection State**: Track connection state and disable UI when disconnected
- **Cleanup**: Always close WebSocket connections when component unmounts

### 2. Message Handling

- **Queue Messages**: Queue messages when disconnected and send when reconnected
- **Debounce**: Avoid sending multiple messages rapidly
- **Validation**: Validate session_id and visitor_id before sending

### 3. Performance

- **Streaming Display**: Update UI incrementally as chunks arrive
- **Virtual Scrolling**: Use virtual scrolling for long message lists
- **Message Limits**: Limit the number of messages displayed

### 4. User Experience

- **Loading States**: Show loading indicators while streaming
- **Typing Indicators**: Display typing cursor during streaming
- **Error Messages**: Show user-friendly error messages
- **Suggestions**: Display suggestion buttons when available

### 5. Security

- **WSS in Production**: Always use `wss://` (secure WebSocket) in production
- **Input Validation**: Validate and sanitize user input
- **Rate Limiting**: Implement client-side rate limiting

## Testing

### Test Connection

```javascript
const ws = new ChatWebSocket('ws://localhost:8000/ws/chat/');
ws.connect();

ws.setOnMessage((data) => {
    console.log('Received:', data);
});

// Test message
setTimeout(() => {
    ws.sendMessage(
        'Hello, Alex AI!',
        'your-session-id',
        'your-visitor-id'
    );
}, 1000);
```

## Production Deployment

### Environment Variables

```bash
# WebSocket URL (production)
WS_URL=wss://api.yourdomain.com/ws/chat/

# Redis URL (for production channel layers)
REDIS_URL=redis://your-redis-host:6379/0
```

### Nginx Configuration

```nginx
upstream channels-backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name api.yourdomain.com;

    location /ws/ {
        proxy_pass http://channels-backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    location / {
        proxy_pass http://channels-backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Support

For issues or questions, please refer to:
- Backend API Documentation: `/api/docs/`
- WebSocket Endpoint: `/ws/chat/`
- Session Creation: `POST /api/chats/sessions/`


