"""
URL extraction service for fetching and extracting content from URLs.
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import logging
from typing import Tuple, Optional, List, Dict

logger = logging.getLogger(__name__)


def extract_content_from_url(url: str, timeout: int = 30) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract text content and title from a URL.
    
    Args:
        url: URL to extract content from
        timeout: Request timeout in seconds (default: 30)
        
    Returns:
        Tuple of (text_content, page_title) or (None, None) if extraction fails
    """
    try:
        # Validate URL
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            logger.error(f"Invalid URL format: {url}")
            return None, None
        
        # Make request with proper headers to avoid blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        logger.info(f"Fetching content from URL: {url}")
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type and 'text' not in content_type:
            logger.warning(f"URL does not contain HTML/text content. Content-Type: {content_type}")
            return None, None
        
        # Parse HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else None
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script.decompose()
        
        # Extract main content (try to find main content areas first)
        main_content = None
        
        # Try to find main content in semantic HTML5 tags
        for tag_name in ['main', 'article', 'div[role="main"]']:
            tag = soup.select_one(tag_name) if '[' in tag_name else soup.find(tag_name)
            if tag:
                main_content = tag
                break
        
        # If no main content found, use body
        if not main_content:
            main_content = soup.find('body') or soup
        
        # Extract text
        text = main_content.get_text(separator='\n', strip=True)
        
        # Clean up text (remove excessive whitespace)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        
        if not text:
            logger.warning(f"No text content extracted from URL: {url}")
            return None, title
        
        logger.info(f"Successfully extracted {len(text)} characters from URL: {url}")
        return text, title or url
    
    except requests.exceptions.Timeout:
        logger.error(f"Timeout while fetching URL: {url}")
        return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching URL {url}: {str(e)}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error extracting content from URL {url}: {str(e)}")
        return None, None


def extract_content_with_structure(url: str, timeout: int = 30) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """
    Extract content from URL preserving structure (headings and sections).
    Returns structured content with headings and paragraphs grouped by topic.
    
    Args:
        url: URL to extract content from
        timeout: Request timeout in seconds (default: 30)
        
    Returns:
        Tuple of (structured_content_list, page_title) or (None, None) if extraction fails.
        structured_content_list is a list of dicts with keys: 'heading', 'level', 'content'
    """
    try:
        # Validate URL
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            logger.error(f"Invalid URL format: {url}")
            return None, None
        
        # Make request with proper headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        logger.info(f"Fetching structured content from URL: {url}")
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type and 'text' not in content_type:
            logger.warning(f"URL does not contain HTML/text content. Content-Type: {content_type}")
            return None, None
        
        # Parse HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else None
        
        # Remove script, style, nav, footer, header, aside elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
            element.decompose()
        
        # Find main content area
        main_content = None
        for tag_name in ['main', 'article', 'div[role="main"]']:
            tag = soup.select_one(tag_name) if '[' in tag_name else soup.find(tag_name)
            if tag:
                main_content = tag
                break
        
        if not main_content:
            main_content = soup.find('body') or soup
        
        # Extract structured content (headings and their associated content)
        # Use a better approach: iterate through elements maintaining heading hierarchy
        structured_content = []
        heading_stack = []  # Stack to track heading hierarchy
        current_content = []
        
        # Get all content elements in order
        for element in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'ul', 'ol', 'dl', 'dt', 'dd']):
            tag_name = element.name.lower()
            text = element.get_text(strip=True)
            
            if not text or len(text) < 3:  # Skip very short text
                continue
            
            # If it's a heading
            if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                # Save previous section if exists
                if heading_stack and current_content:
                    # Combine heading path for better context
                    heading_path = ' > '.join([h['text'] for h in heading_stack])
                    structured_content.append({
                        'heading': heading_path,
                        'level': heading_stack[-1]['level'],
                        'main_heading': heading_stack[-1]['text'],
                        'content': '\n'.join(current_content).strip()
                    })
                    current_content = []
                
                # Update heading stack based on hierarchy
                level = int(tag_name[1])
                
                # Remove headings at same or deeper level
                while heading_stack and heading_stack[-1]['level'] >= level:
                    heading_stack.pop()
                
                # Add new heading to stack
                heading_stack.append({
                    'text': text,
                    'level': level
                })
            
            # If it's content (paragraph, list items, etc.)
            else:
                # Only add content if we have a heading or if it's substantial standalone content
                if heading_stack:
                    # Add content to current section
                    if tag_name in ['li', 'dt', 'dd']:
                        # List items and definition terms - format nicely
                        current_content.append(f"• {text}" if tag_name == 'li' else text)
                    else:
                        current_content.append(text)
                elif len(text) > 50:  # Substantial content without heading
                    # Create a section without heading
                    structured_content.append({
                        'heading': None,
                        'level': 0,
                        'main_heading': None,
                        'content': text
                    })
        
        # Save last section
        if heading_stack and current_content:
            heading_path = ' > '.join([h['text'] for h in heading_stack])
            structured_content.append({
                'heading': heading_path,
                'level': heading_stack[-1]['level'],
                'main_heading': heading_stack[-1]['text'],
                'content': '\n'.join(current_content).strip()
            })
        elif current_content:
            # Content without final heading
            structured_content.append({
                'heading': None,
                'level': 0,
                'main_heading': None,
                'content': '\n'.join(current_content).strip()
            })
        
        # Filter out empty sections
        structured_content = [section for section in structured_content if section['content']]
        
        if not structured_content:
            logger.warning(f"No structured content extracted from URL: {url}")
            return None, title
        
        logger.info(f"Successfully extracted {len(structured_content)} structured sections from URL: {url}")
        return structured_content, title or url
    
    except requests.exceptions.Timeout:
        logger.error(f"Timeout while fetching URL: {url}")
        return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching URL {url}: {str(e)}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error extracting structured content from URL {url}: {str(e)}")
        return None, None


def validate_url(url: str) -> bool:
    """
    Validate that a string is a valid URL.
    
    Args:
        url: URL string to validate
        
    Returns:
        True if valid URL, False otherwise
    """
    try:
        parsed = urlparse(url)
        return all([parsed.scheme, parsed.netloc])
    except Exception:
        return False

