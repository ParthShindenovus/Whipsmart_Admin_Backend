"""
Custom router that prevents format suffix registration conflicts.
"""
from rest_framework.routers import DefaultRouter
from rest_framework.routers import Route, DynamicRoute


class NoFormatSuffixRouter(DefaultRouter):
    """
    DefaultRouter that doesn't apply format suffixes to prevent
    "Converter 'drf_format_suffix' is already registered" errors
    when multiple routers are used in the same project.
    """
    def get_urls(self):
        """
        Override to skip format_suffix_patterns application.
        This prevents the converter from being registered multiple times.
        """
        from django.urls import re_path
        
        urls = []
        
        if self.include_root_view:
            root_view = self.get_api_root_view()
            root_url = re_path(r'^$', root_view, name=self.root_view_name)
            urls.append(root_url)
        
        for prefix, viewset, basename in self.registry:
            lookup = self.get_lookup_regex(viewset)
            routes = self.get_routes(viewset)
            
            for route in routes:
                mapping = self.get_method_map(viewset, route.mapping)
                if not mapping:
                    continue
                
                initkwargs = route.initkwargs.copy()
                initkwargs.update({
                    'basename': basename,
                })
                
                url_path = route.url.format(
                    prefix=prefix,
                    lookup=lookup,
                    trailing_slash=self.trailing_slash
                )
                
                view = viewset.as_view(mapping, **initkwargs)
                name = route.name.format(basename=basename)
                
                urls.append(re_path(url_path, view, name=name))
        
        # Don't apply format_suffix_patterns - this prevents the converter registration error
        return urls

