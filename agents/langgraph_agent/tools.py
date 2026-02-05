"""
LangChain tools for the unified agent.
"""
import logging
import json
import re
from typing import Dict, Any, Optional, List
from langchain.tools import tool
from django.conf import settings
from chats.models import Session, ChatMessage
from service.hubspot_service import create_contact, update_contact, format_phone_number

logger = logging.getLogger(__name__)


@tool
def search_knowledge_base(query: str) -> Dict[str, Any]:
    """
    Search WhipSmart knowledge base for answers to questions about services,
    novated leases, EVs, tax benefits, etc.
    
    Args:
        query: The search query to find relevant information
        
    Returns:
        Dictionary with success flag and results
    """
    if not query:
        return {"error": "Query is required", "success": False}
    
    try:
        from agents.tools.rag_tool import rag_tool_node
        from agents.state import AgentState
        from agents.session_manager import session_manager
        
        # Create a minimal state for RAG tool
        agent_state = AgentState(session_id="temp", messages=[])
        agent_state.tool_result = {"action": "rag", "query": query}
        
        # Call RAG tool
        state_dict = rag_tool_node(agent_state.to_dict())
        rag_state = AgentState.from_dict(state_dict)
        
        results = rag_state.tool_result.get('results', [])
        
        if results:
            formatted_results = []
            for r in results[:4]:  # Top 4 results
                if isinstance(r, dict):
                    text = r.get('text', '')[:500]
                    score = r.get('score', 0.0)
                    source = r.get('reference_url') or r.get('url') or ''
                    formatted_results.append({
                        "text": text,
                        "score": score,
                        "source": source
                    })
            
            return {
                "success": True,
                "results": formatted_results,
                "count": len(formatted_results)
            }
        else:
            return {
                "success": False,
                "results": [],
                "message": "No relevant information found"
            }
    except Exception as e:
        logger.error(f"Error searching knowledge base: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool
def search_vehicles(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Search for available vehicles/cars with optional filters.
    
    Args:
        filters: Optional search filters (max_price, min_price, min_range, max_range, make, model)
        
    Returns:
        Dictionary with success flag and vehicles list
    """
    try:
        from agents.tools.car_tool import car_tool_node
        from agents.state import AgentState
        
        # Create a minimal state for car tool
        agent_state = AgentState(session_id="temp", messages=[])
        agent_state.tool_result = {"action": "search", "filters": filters or {}}
        
        # Call car tool
        state_dict = car_tool_node(agent_state.to_dict())
        car_state = AgentState.from_dict(state_dict)
        
        results = car_state.tool_result.get('results', [])
        
        return {
            "success": True,
            "vehicles": results,
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"Error searching vehicles: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool
def collect_user_info(session_id: str, name: Optional[str] = None, 
                     email: Optional[str] = None, phone: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract and store user information (name, email, phone).
    
    Args:
        session_id: The session ID
        name: User's name if provided
        email: User's email if provided
        phone: User's phone if provided
        
    Returns:
        Dictionary with collected information
    """
    try:
        session = Session.objects.get(id=session_id)
        conversation_data = session.conversation_data or {}
        
        # Extract and store information
        if name:
            conversation_data['name'] = name
        if email:
            conversation_data['email'] = email
        if phone:
            conversation_data['phone'] = phone
        
        # Save to session
        session.conversation_data = conversation_data
        session.save(update_fields=['conversation_data'])
        
        # Trigger HubSpot contact creation/update if we have email or phone
        if email or phone:
            try:
                contact_data = {
                    'email': email or conversation_data.get('email'),
                    'phone': phone or conversation_data.get('phone'),
                    'firstname': name or conversation_data.get('name', '').split()[0] if conversation_data.get('name') else '',
                }
                
                if contact_data.get('email') or contact_data.get('phone'):
                    if contact_data.get('email'):
                        create_contact(contact_data)
                    else:
                        update_contact(contact_data)
            except Exception as e:
                logger.warning(f"Error syncing with HubSpot: {str(e)}")
        
        return {
            "success": True,
            "collected": {
                "name": conversation_data.get('name'),
                "email": conversation_data.get('email'),
                "phone": conversation_data.get('phone')
            }
        }
    except Exception as e:
        logger.error(f"Error collecting user info: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool
def update_user_info(session_id: str, field: str, value: str) -> Dict[str, Any]:
    """
    Update a specific user information field.
    
    Args:
        session_id: The session ID
        field: The field to update (name, email, phone)
        value: The new value
        
    Returns:
        Dictionary with update status
    """
    try:
        if field not in ['name', 'email', 'phone']:
            return {"error": f"Invalid field: {field}", "success": False}
        
        session = Session.objects.get(id=session_id)
        conversation_data = session.conversation_data or {}
        
        conversation_data[field] = value
        session.conversation_data = conversation_data
        session.save(update_fields=['conversation_data'])
        
        return {
            "success": True,
            "updated_field": field,
            "new_value": value
        }
    except Exception as e:
        logger.error(f"Error updating user info: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool
def submit_lead(session_id: str) -> Dict[str, Any]:
    """
    Submit the lead to HubSpot when all information is collected.
    
    Args:
        session_id: The session ID
        
    Returns:
        Dictionary with submission status
    """
    try:
        session = Session.objects.get(id=session_id)
        conversation_data = session.conversation_data or {}
        
        name = conversation_data.get('name', '')
        email = conversation_data.get('email', '')
        phone = conversation_data.get('phone', '')
        
        if not (name and email and phone):
            return {
                "success": False,
                "error": "Missing required information"
            }
        
        # Create/update HubSpot contact
        contact_data = {
            'email': email,
            'phone': format_phone_number(phone),
            'firstname': name.split()[0] if name else '',
            'lastname': ' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
        }
        
        create_contact(contact_data)
        
        # Mark session as complete
        conversation_data['step'] = 'complete'
        session.conversation_data = conversation_data
        session.is_active = False
        session.save(update_fields=['conversation_data', 'is_active'])
        
        return {
            "success": True,
            "message": "Lead submitted successfully"
        }
    except Exception as e:
        logger.error(f"Error submitting lead: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


@tool
def end_conversation(session_id: str) -> Dict[str, Any]:
    """
    End the conversation gracefully.
    
    Args:
        session_id: The session ID
        
    Returns:
        Dictionary with end status
    """
    try:
        session = Session.objects.get(id=session_id)
        conversation_data = session.conversation_data or {}
        
        conversation_data['step'] = 'complete'
        session.conversation_data = conversation_data
        session.is_active = False
        session.save(update_fields=['conversation_data', 'is_active'])
        
        return {
            "success": True,
            "message": "Conversation ended"
        }
    except Exception as e:
        logger.error(f"Error ending conversation: {str(e)}", exc_info=True)
        return {"error": str(e), "success": False}


def get_tools() -> List:
    """Get all available tools for the agent."""
    return [
        search_knowledge_base,
        search_vehicles,
        collect_user_info,
        update_user_info,
        submit_lead,
        end_conversation,
    ]
