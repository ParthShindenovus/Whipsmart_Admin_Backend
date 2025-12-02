"""
Base ViewSet mixin for standardized API responses.
"""
from rest_framework import viewsets, status
from rest_framework.response import Response
from core.utils import success_response, error_response


class StandardizedResponseMixin:
    """
    Mixin that provides standardized response format for all ViewSet methods.
    
    Success format: {success: true, ...data}
    Error format: {success: false, message: "error message"}
    """
    
    def list(self, request, *args, **kwargs):
        """Override list to use standardized response"""
        response = super().list(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            # Wrap paginated or non-paginated responses
            if hasattr(response.data, 'results'):
                # Paginated response
                return success_response({
                    'results': response.data['results'],
                    'count': response.data.get('count', len(response.data['results'])),
                    'next': response.data.get('next'),
                    'previous': response.data.get('previous'),
                })
            else:
                # List response
                return success_response({'results': response.data})
        return response
    
    def retrieve(self, request, *args, **kwargs):
        """Override retrieve to use standardized response"""
        response = super().retrieve(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            return success_response(response.data)
        return response
    
    def create(self, request, *args, **kwargs):
        """Override create to use standardized response"""
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED:
            return success_response(response.data, message="Created successfully", status_code=status.HTTP_201_CREATED)
        return response
    
    def update(self, request, *args, **kwargs):
        """Override update to use standardized response"""
        response = super().update(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            return success_response(response.data, message="Updated successfully")
        return response
    
    def partial_update(self, request, *args, **kwargs):
        """Override partial_update to use standardized response"""
        response = super().partial_update(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            return success_response(response.data, message="Updated successfully")
        return response
    
    def destroy(self, request, *args, **kwargs):
        """Override destroy to use standardized response"""
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message="Deleted successfully", status_code=status.HTTP_200_OK)


