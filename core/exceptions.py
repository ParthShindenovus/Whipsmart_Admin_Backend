"""
Custom exception handler for DRF to provide standardized error responses.
"""
from rest_framework.views import exception_handler
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler that returns standardized error responses.
    
    Format: {success: false, message: "error message", errors: {...}}
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)
    
    if response is not None:
        # Get the standard error response data
        custom_response_data = {
            "success": False,
            "message": "An error occurred"
        }
        
        # Extract error details
        if hasattr(response, 'data'):
            # Handle ValidationError
            if isinstance(response.data, dict):
                # Check if it's a detail error
                if 'detail' in response.data:
                    custom_response_data["message"] = str(response.data['detail'])
                elif 'non_field_errors' in response.data:
                    custom_response_data["message"] = str(response.data['non_field_errors'][0])
                    custom_response_data["errors"] = response.data
                else:
                    # Multiple field errors
                    first_error = next(iter(response.data.values()))
                    if isinstance(first_error, list):
                        custom_response_data["message"] = str(first_error[0])
                    else:
                        custom_response_data["message"] = str(first_error)
                    custom_response_data["errors"] = response.data
            elif isinstance(response.data, list):
                custom_response_data["message"] = str(response.data[0]) if response.data else "An error occurred"
                custom_response_data["errors"] = response.data
            else:
                custom_response_data["message"] = str(response.data)
        
        # Map HTTP status codes to appropriate messages
        if response.status_code == status.HTTP_404_NOT_FOUND:
            custom_response_data["message"] = custom_response_data.get("message", "Resource not found")
        elif response.status_code == status.HTTP_403_FORBIDDEN:
            custom_response_data["message"] = custom_response_data.get("message", "Permission denied")
        elif response.status_code == status.HTTP_401_UNAUTHORIZED:
            custom_response_data["message"] = custom_response_data.get("message", "Authentication required")
        elif response.status_code == status.HTTP_400_BAD_REQUEST:
            custom_response_data["message"] = custom_response_data.get("message", "Invalid request")
        elif response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            custom_response_data["message"] = custom_response_data.get("message", "Internal server error")
        
        # Log the exception for debugging
        logger.error(f"API Error: {custom_response_data['message']}", exc_info=exc)
        
        # Update response with standardized format
        response.data = custom_response_data
        response.content_type = 'application/json'
    
    return response


