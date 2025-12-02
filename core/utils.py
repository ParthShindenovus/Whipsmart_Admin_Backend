"""
Utility functions for standardized API responses.
"""
from rest_framework.response import Response
from rest_framework import status


def success_response(data=None, message=None, status_code=status.HTTP_200_OK):
    """
    Create a standardized success response.
    
    Args:
        data: Response data (dict, list, or any serializable object)
        message: Optional success message
        status_code: HTTP status code (default: 200)
        
    Returns:
        Response object with format: {success: true, data: ..., message: ...}
    """
    response_data = {"success": True}
    
    if data is not None:
        if isinstance(data, dict):
            # Merge data into response
            response_data.update(data)
        else:
            # Wrap in data key
            response_data["data"] = data
    
    if message:
        response_data["message"] = message
    
    return Response(response_data, status=status_code)


def error_response(message, status_code=status.HTTP_400_BAD_REQUEST, errors=None):
    """
    Create a standardized error response.
    
    Args:
        message: Error message string
        status_code: HTTP status code (default: 400)
        errors: Optional detailed error information (dict or list)
        
    Returns:
        Response object with format: {success: false, message: "...", errors: ...}
    """
    response_data = {
        "success": False,
        "message": message
    }
    
    if errors:
        response_data["errors"] = errors
    
    return Response(response_data, status=status_code)


