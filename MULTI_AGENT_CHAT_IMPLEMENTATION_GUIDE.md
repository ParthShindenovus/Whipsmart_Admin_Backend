# WhipSmart Multi-Agent Chat API - Complete Implementation Guide

## Overview

The WhipSmart Chat API implements a production-grade multi-agent system with three specialized agents:
1. **Sales Agent** - Collects contact info (name, email, phone) + answers questions
2. **Support Agent** - Collects issue info (issue, name, email) + answers questions  
3. **Knowledge Agent** - Pure Q&A with Sales escalation capability

## Architecture

### Agent Router
Every message is routed to the correct agent based on `conversation_type`:
- `conversation_type: "sales"` → Sales Agent
- `conversation_type: "support"` → Support Agent
- `conversation_type: "knowledge"` → Knowledge Agent

### Flow Control
- **Sales/Support**: Collect data → Confirmation → Complete → Lock session
- **Knowledge**: Answer questions → Detect sales intent → Escalate to Sales (optional)

## API Base URL

```
Production: https://whipsmart-admin-panel-921aed6c92cf.herokuapp.com
Development: http://localhost:8000
```

## Authentication

All chat endpoints require API Key:

```
X-API-Key: your-api-key-here
```

OR

```
Authorization: Bearer your-api-key-here
```

## Complete API Flow

### Step 1: Create Visitor

**Endpoint:** `POST /api/chats/visitors/`

**Request:**
```json
{}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "visitor-uuid",
    "created_at": "2025-12-10T10:00:00Z",
    "last_seen_at": "2025-12-10T10:00:00Z"
  }
}
```

### Step 2: Create Session with Conversation Type

**Endpoint:** `POST /api/chats/sessions/`

**Request:**
```json
{
  "visitor_id": "visitor-uuid",
  "conversation_type": "sales"  // "sales", "support", or "knowledge"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "session-uuid",
    "visitor_id": "visitor-uuid",
    "conversation_type": "sales",
    "conversation_data": {
      "step": "name",
      "name": null,
      "email": null,
      "phone": null
    },
    "is_active": true
  }
}
```

### Step 3: Send Chat Message

**Endpoint:** `POST /api/chats/messages/chat`

**Request:**
```json
{
  "message": "What is a novated lease?",
  "session_id": "session-uuid",
  "visitor_id": "visitor-uuid",
  "conversation_type": "sales"  // Optional: uses session's type if not provided
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "response": "A novated lease is...",
    "session_id": "session-uuid",
    "conversation_type": "sales",
    "conversation_data": {
      "step": "name",
      "name": null,
      "email": null,
      "phone": null
    },
    "complete": false,
    "needs_info": "name",
    "suggestions": [],
    "message_id": "message-uuid",
    "response_id": "response-uuid"
  }
}
```

## Conversation Flows

### 1. Sales Agent Flow

**Purpose:** Collect contact information for sales team.

**Data Collection Order:**
1. Full Name
2. Email Address
3. Phone Number
4. Confirmation (Yes/No)
5. Complete

**Example Flow:**
```
User: "What is a novated lease?"
Bot: "A novated lease is..." [answers question]
Bot: "To connect you with our sales team, could you please provide your full name?"

User: "John Doe"
Bot: "Thank you, John! Could you please provide your email address?"

User: "john@example.com"
Bot: "Perfect! Now, could you please provide your phone number?"

User: "+1234567890"
Bot: "Here is what I have collected:
      Name: John Doe
      Email: john@example.com
      Phone: +1234567890
      Is this correct? (Yes/No)"

User: "Yes"
Bot: "Thank you! Our sales team will contact you shortly. Have a wonderful day!"
[complete: true, session locked]
```

**Response Fields:**
- `needs_info`: `"name"` → `"email"` → `"phone"` → `"confirmation"` → `null`
- `complete`: `true` when confirmed and session locked
- `conversation_data`: Contains collected information

### 2. Support Agent Flow

**Purpose:** Collect issue details and contact information.

**Data Collection Order:**
1. Issue Description
2. Full Name
3. Email Address
4. Confirmation (Yes/No)
5. Complete

**Example Flow:**
```
User: "I'm having trouble logging in"
Bot: "I'm here to help. Could you please describe the issue in more detail?"

User: "I can't access my account, it says password incorrect"
Bot: "Thank you for describing the issue. To help our support team assist you better, could you please provide your name?"

User: "Jane Smith"
Bot: "Thank you, Jane! Now, could you please provide your email address?"

User: "jane@example.com"
Bot: "Here is what I have collected:
      Issue: I can't access my account...
      Name: Jane Smith
      Email: jane@example.com
      Is this correct? (Yes/No)"

User: "Yes"
Bot: "Thank you! Our support team will contact you shortly."
[complete: true, session locked]
```

**Response Fields:**
- `needs_info`: `"issue"` → `"name"` → `"email"` → `"confirmation"` → `null`
- `complete`: `true` when confirmed and session locked

### 3. Knowledge Agent Flow

**Purpose:** Answer questions about WhipSmart services.

**Features:**
- Answers questions using knowledge base
- Provides contextual suggestions
- Can escalate to Sales when user shows buying intent

**Sales Escalation Triggers:**
- User mentions: pricing, plans, onboarding, setup, consultation, implementation, enterprise, sign up, get started
- User asks: "speak with sales", "contact sales", "talk to someone"

**Example Flow:**
```
User: "What is a novated lease?"
Bot: "A novated lease is..." [detailed answer]
Bot: [suggestions: "What are the tax benefits?", "How do I apply?", ...]

User: "How much does it cost?"
Bot: "I can connect you directly with our sales team to guide you personally. Would you like me to do that?"

User: "Yes"
Bot: "Great! I am now connecting you with our Sales Team.
      To get started, could you please provide your full name?"
[escalated_to: "sales", conversation_type changes to "sales"]
```

**Response Fields:**
- `needs_info`: Always `null`
- `complete`: Always `false`
- `escalated_to`: `"sales"` when escalation happens
- `suggestions`: Array of contextual questions

## Response Schema

### Success Response
```json
{
  "success": true,
  "data": {
    "response": "Bot's response message",
    "session_id": "uuid",
    "conversation_type": "sales|support|knowledge",
    "conversation_data": {
      "step": "name|email|phone|issue|confirmation|complete|chatting",
      "name": "string or null",
      "email": "string or null",
      "phone": "string or null",
      "issue": "string or null"
    },
    "complete": false,
    "needs_info": "name|email|phone|issue|confirmation|null",
    "suggestions": ["suggestion 1", "suggestion 2"],
    "message_id": "uuid",
    "response_id": "uuid",
    "escalated_to": "sales"  // Only present when escalation happens
  }
}
```

### Error Response
```json
{
  "success": false,
  "message": "Error message"
}
```

## Session States

### Active States
- `step: "name"` - Collecting name
- `step: "email"` - Collecting email
- `step: "phone"` - Collecting phone (Sales only)
- `step: "issue"` - Collecting issue (Support only)
- `step: "confirmation"` - Waiting for Yes/No confirmation
- `step: "chatting"` - Normal Q&A (Knowledge)

### Complete State
- `step: "complete"` - Session completed
- `is_active: false` - Session locked, no more messages accepted

## Frontend Implementation

### React/JavaScript Example

```javascript
class WhipSmartMultiAgentChat {
  constructor(apiKey) {
    this.apiKey = apiKey;
    this.baseUrl = 'https://whipsmart-admin-panel-921aed6c92cf.herokuapp.com';
    this.visitorId = null;
    this.sessionId = null;
    this.conversationType = null;
  }

  async initialize(conversationType = 'knowledge') {
    try {
      // Step 1: Create visitor
      const visitorRes = await fetch(`${this.baseUrl}/api/chats/visitors/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const visitorData = await visitorRes.json();
      this.visitorId = visitorData.data.id;

      // Step 2: Create session
      const sessionRes = await fetch(`${this.baseUrl}/api/chats/sessions/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': this.apiKey
        },
        body: JSON.stringify({
          visitor_id: this.visitorId,
          conversation_type: conversationType
        })
      });
      const sessionData = await sessionRes.json();
      this.sessionId = sessionData.data.id;
      this.conversationType = sessionData.data.conversation_type;

      return {
        visitorId: this.visitorId,
        sessionId: this.sessionId,
        conversationType: this.conversationType
      };
    } catch (error) {
      console.error('Error initializing chat:', error);
      throw error;
    }
  }

  async sendMessage(message) {
    try {
      const response = await fetch(`${this.baseUrl}/api/chats/messages/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': this.apiKey
        },
        body: JSON.stringify({
          message: message,
          session_id: this.sessionId,
          visitor_id: this.visitorId,
          conversation_type: this.conversationType
        })
      });

      const data = await response.json();
      
      if (!data.success) {
        throw new Error(data.message || 'Failed to send message');
      }

      // Handle escalation
      if (data.data.escalated_to === 'sales') {
        this.conversationType = 'sales';
        console.log('Escalated to Sales Agent');
      }

      return {
        response: data.data.response,
        conversationType: data.data.conversation_type,
        conversationData: data.data.conversation_data,
        complete: data.data.complete,
        needsInfo: data.data.needs_info,
        suggestions: data.data.suggestions || [],
        escalated: data.data.escalated_to || null
      };
    } catch (error) {
      console.error('Error sending message:', error);
      throw error;
    }
  }
}

// Usage
const chat = new WhipSmartMultiAgentChat('your-api-key');

// Initialize with conversation type
await chat.initialize('sales'); // or 'support' or 'knowledge'

// Send message
const result = await chat.sendMessage('What is a novated lease?');

// Handle response
console.log('Bot:', result.response);
console.log('Needs Info:', result.needsInfo); // 'name', 'email', 'phone', etc.
console.log('Complete:', result.complete); // true when done
console.log('Suggestions:', result.suggestions);

// Check if escalated
if (result.escalated === 'sales') {
  console.log('Conversation escalated to Sales');
}
```

### React Component Example

```jsx
import React, { useState, useEffect } from 'react';

const MultiAgentChatWidget = ({ apiKey, initialType = 'knowledge' }) => {
  const [chat, setChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [needsInfo, setNeedsInfo] = useState(null);
  const [complete, setComplete] = useState(false);
  const [conversationType, setConversationType] = useState(initialType);
  const [conversationData, setConversationData] = useState({});

  useEffect(() => {
    const initChat = async () => {
      const chatInstance = new WhipSmartMultiAgentChat(apiKey);
      await chatInstance.initialize(initialType);
      setChat(chatInstance);
      setConversationType(chatInstance.conversationType);
    };
    initChat();
  }, [apiKey, initialType]);

  const sendMessage = async (messageText) => {
    if (!chat || !messageText.trim() || complete) return;

    setLoading(true);
    setMessages(prev => [...prev, { role: 'user', content: messageText }]);
    setInput('');

    try {
      const result = await chat.sendMessage(messageText);
      
      setMessages(prev => [...prev, { role: 'assistant', content: result.response }]);
      setSuggestions(result.suggestions || []);
      setNeedsInfo(result.needsInfo);
      setComplete(result.complete);
      setConversationType(result.conversationType);
      setConversationData(result.conversationData);

      // Handle escalation
      if (result.escalated === 'sales') {
        console.log('Escalated to Sales Agent');
        // Update UI to show sales flow
      }

      // Handle completion
      if (result.complete) {
        console.log('Conversation complete!', result.conversationData);
        // Show success message, disable input
      }
    } catch (error) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Sorry, I encountered an error. Please try again.' 
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-widget">
      <div className="chat-header">
        <span>Chat - {conversationType.charAt(0).toUpperCase() + conversationType.slice(1)}</span>
        {complete && <span className="badge">Complete</span>}
      </div>

      <div className="messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {loading && <div className="loading">Typing...</div>}
      </div>

      {needsInfo && !complete && (
        <div className="info-prompt">
          Please provide: <strong>{needsInfo}</strong>
        </div>
      )}

      {suggestions.length > 0 && !complete && (
        <div className="suggestions">
          {suggestions.map((suggestion, idx) => (
            <button
              key={idx}
              onClick={() => sendMessage(suggestion)}
              className="suggestion-btn"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {!complete && (
        <div className="input-area">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && sendMessage(input)}
            placeholder="Type your message..."
            disabled={loading}
          />
          <button onClick={() => sendMessage(input)} disabled={loading}>
            Send
          </button>
        </div>
      )}

      {complete && (
        <div className="completion-message">
          ✓ Conversation completed. Our team will contact you shortly.
        </div>
      )}
    </div>
  );
};

export default MultiAgentChatWidget;
```

## Key Implementation Points

### 1. Session Locking
When `complete: true`:
- **Disable input** - User cannot send more messages
- **Show completion message** - Display success message
- **Store lead data** - Save `conversation_data` for CRM/webhook

### 2. Escalation Handling
When `escalated_to: "sales"`:
- **Update conversation type** - Change UI to show Sales flow
- **Reset form state** - Prepare for data collection
- **Continue conversation** - Next message goes to Sales Agent

### 3. Needs Info Display
Show helpful prompts based on `needs_info`:
- `"name"` → "Please provide your name"
- `"email"` → "Please provide your email"
- `"phone"` → "Please provide your phone number"
- `"issue"` → "Please describe your issue"
- `"confirmation"` → "Please confirm: Yes or No"

### 4. Confirmation Handling
When `needs_info: "confirmation"`:
- Show Yes/No buttons
- Handle both button clicks and text input ("yes", "no")
- On "Yes": Show completion message
- On "No": Allow correction

### 5. Error Handling
- **403 Forbidden (Session Locked)**: Show "Conversation completed" message
- **400 Bad Request**: Show validation error
- **500 Internal Server Error**: Show generic error, allow retry

## Testing Checklist

- [ ] Sales flow: Name → Email → Phone → Confirmation → Complete
- [ ] Support flow: Issue → Name → Email → Confirmation → Complete
- [ ] Knowledge flow: Q&A with suggestions
- [ ] Knowledge → Sales escalation
- [ ] Session locking after completion
- [ ] Confirmation Yes/No handling
- [ ] Error handling for locked sessions
- [ ] Suggestion buttons working
- [ ] Conversation data persistence

## Best Practices

1. **Store IDs**: Save `visitor_id` and `session_id` in localStorage
2. **Handle Completion**: Check `complete: true` and disable input
3. **Show Needs Info**: Display helpful prompts based on `needs_info`
4. **Handle Escalation**: Update UI when `escalated_to` is present
5. **Confirmation UI**: Show Yes/No buttons when `needs_info: "confirmation"`
6. **Error Handling**: Handle all error cases gracefully
7. **Loading States**: Show loading indicators during API calls
8. **Session Persistence**: Reuse existing session if available

## API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chats/visitors/` | POST | Create visitor |
| `/api/chats/sessions/` | POST | Create session with conversation_type |
| `/api/chats/messages/chat` | POST | Send message, get response |
| `/api/chats/messages/suggestions/` | GET | Get contextual suggestions |

## Support

For questions or issues, contact the development team.

