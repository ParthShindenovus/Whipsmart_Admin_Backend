"""
Standalone script to test Neo4j connection.
Run this independently to debug Neo4j connectivity issues.

Usage:
    python knowledge_graph/test_neo4j_connection.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whipsmart_admin.settings')

# Initialize Django
import django
django.setup()

from django.conf import settings
from neo4j import GraphDatabase


def test_neo4j_connection():
    """Test Neo4j connection with detailed debugging."""
    print("=" * 60)
    print("Neo4j Connection Test")
    print("=" * 60)
    
    # Get settings
    use_neo4j = getattr(settings, 'USE_NEO4J', False)
    uri = getattr(settings, 'NEO4J_URI', 'bolt://localhost:7687')
    user = getattr(settings, 'NEO4J_USER', 'neo4j')
    password = getattr(settings, 'NEO4J_PASSWORD', '')
    
    print(f"\n[Settings]")
    print(f"  USE_NEO4J: {use_neo4j}")
    print(f"  NEO4J_URI: {uri}")
    print(f"  NEO4J_USER: {user}")
    print(f"  NEO4J_PASSWORD: {'***' if password else 'NOT SET'}")
    print(f"  Database: neo4j (default)")
    
    if not use_neo4j:
        print("\n[ERROR] USE_NEO4J is False. Set USE_NEO4J=True in your .env file.")
        return False
    
    if not password:
        print("\n[ERROR] NEO4J_PASSWORD is not set. Please set it in your .env file.")
        return False
    
    print(f"\n[Connection Test]")
    print(f"  Attempting to connect to: {uri}")
    print(f"  Username: {user}")
    
    try:
        # Create driver
        print("\n  Step 1: Creating driver...")
        
        # Add SSL/TLS parameters for secure connections (neo4j+s://)
        driver_kwargs = {'auth': (user, password)}
        if uri.startswith('neo4j+s://') or uri.startswith('bolt+s://'):
            driver_kwargs['encrypted'] = True
            driver_kwargs['trusted_certificates'] = True
            print("  → Using encrypted connection with trusted certificates")
        
        driver = GraphDatabase.driver(uri, **driver_kwargs)
        print("  [OK] Driver created successfully")
        
        # Verify connectivity
        print("\n  Step 2: Verifying connectivity...")
        driver.verify_connectivity()
        print("  [OK] Connectivity verified successfully")
        
        # Test a simple query
        print("\n  Step 3: Testing query execution...")
        records, summary, keys = driver.execute_query(
            "RETURN 1 as test",
            database_="neo4j"
        )
        print(f"  [OK] Query executed successfully")
        print(f"  [OK] Result: {records[0].data() if records else 'No records'}")
        
        # Get server info
        print("\n  Step 4: Getting server information...")
        server_info = driver.get_server_info()
        print(f"  [OK] Server version: {server_info.agent}")
        print(f"  [OK] Protocol version: {server_info.protocol_version}")
        
        # Close driver
        driver.close()
        print("\n  [OK] Driver closed successfully")
        
        print("\n" + "=" * 60)
        print("[SUCCESS] Neo4j connection test passed!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n  [ERROR] Error: {str(e)}")
        print(f"\n  Error type: {type(e).__name__}")
        
        # Provide specific troubleshooting based on error
        error_msg = str(e).lower()
        print("\n[Troubleshooting]")
        
        if "routing" in error_msg:
            print("  - Routing error detected. This usually means:")
            print("    - URI format might be incorrect")
            print("    - Network/firewall blocking routing requests")
            print("    - Try using bolt:// instead of neo4j:// or neo4j+s://")
            print("    - For AuraDB, ensure you're using neo4j+s:// format")
        
        if "authentication" in error_msg or "unauthorized" in error_msg:
            print("  - Authentication error detected:")
            print("    - Check your NEO4J_USER and NEO4J_PASSWORD")
            print("    - Ensure credentials match your Neo4j instance")
        
        if "connection" in error_msg or "refused" in error_msg:
            print("  - Connection error detected:")
            print("    - Check if Neo4j is running")
            print("    - Verify NEO4J_URI is correct")
            print("    - Check firewall/network settings")
        
        if "ssl" in error_msg or "certificate" in error_msg:
            print("  - SSL/TLS error detected:")
            print("    - For AuraDB, ensure URI uses neo4j+s:// (secure)")
            print("    - Check SSL certificate settings")
        
        print("\n" + "=" * 60)
        print("[FAILED] Neo4j connection test failed!")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = test_neo4j_connection()
    sys.exit(0 if success else 1)

