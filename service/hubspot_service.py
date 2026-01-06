"""
HubSpot service for CRM integration.
Handles contact creation, company association, and duplicate detection.
"""
from datetime import datetime, timezone
from typing import Optional
from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInput
from hubspot.crm.contacts import ApiException as ContactApiException
from hubspot.crm.companies import SimplePublicObjectInput as CompanyInput
from hubspot.crm.companies import ApiException as CompanyApiException
from hubspot.crm.companies.models import Filter, FilterGroup, PublicObjectSearchRequest
from hubspot.crm.contacts.models import Filter, FilterGroup, PublicObjectSearchRequest
from django.conf import settings
from loguru import logger

# Initialize HubSpot client (singleton pattern)
_client = None


def _get_hubspot_client():
    """Initialize HubSpot client (singleton pattern)"""
    global _client
    
    if _client is not None:
        return _client
    
    access_token = getattr(settings, 'HUBSPOT_ACCESS_TOKEN', None)
    if not access_token:
        logger.error("HUBSPOT_ACCESS_TOKEN is required but not set in settings")
        return None
    
    try:
        _client = HubSpot(access_token=access_token)
        logger.info("Initialized HubSpot client")
        return _client
    except Exception as e:
        # Use str() to avoid loguru formatting issues
        error_msg = str(e)
        logger.error("Failed to initialize HubSpot client: {}", error_msg)
        return None


# Valid property values
HUBSPOT_LEAD_STATUS = {
    "NEW",                    # Newly created lead
    "OPEN",                   # Open for outreach
    "IN_PROGRESS",           # Currently being worked
    "OPEN_DEAL",             # Deal created
    "UNQUALIFIED",           # Not a good fit
    "ATTEMPTED_TO_CONTACT",  # Attempted but not reached
    "CONNECTED",             # Successfully connected
    "BAD_TIMING"             # Good prospect, bad timing
}

LIFECYCLE_STAGE_ORDER = [
    "subscriber",              # Level 0: Basic subscriber
    "lead",                    # Level 1: Identified lead
    "marketingqualifiedlead",  # Level 2: MQL
    "salesqualifiedlead",      # Level 3: SQL
    "customer",                # Level 4: Paying customer
    "evangelist",              # Level 5: Brand advocate
    "other"                    # Other stages
]


def format_phone_number(phone: str) -> str:
    """
    Format phone number with +61 prefix if not already present.
    
    Args:
        phone: Phone number string
    
    Returns:
        Formatted phone number with +61 prefix (if not already present)
    """
    if not phone:
        return phone
    
    phone = phone.strip()
    
    # Remove any existing +61, 61, or 0 prefix
    if phone.startswith('+61'):
        return phone
    elif phone.startswith('61'):
        return '+' + phone
    elif phone.startswith('0'):
        # Remove leading 0 and add +61
        return '+61' + phone[1:]
    else:
        # Add +61 prefix
        return '+61' + phone


def search_contact_by_email(email: str) -> Optional[str]:
    """
    Search HubSpot contact by email and return contact_id or None.
    
    Uses the Search API.
    
    Args:
        email: Email address to search for
    
    Returns:
        contact_id if found, None otherwise
    """
    client = _get_hubspot_client()
    if not client:
        return None
    
    # Validate email is not empty
    if not email or not email.strip():
        logger.warning("Email search skipped: empty email provided")
        return None
    
    try:
        # Normalize email
        email = email.strip().lower()
        
        # Basic email format validation
        if '@' not in email or '.' not in email.split('@')[-1]:
            logger.warning(f"Email search skipped: invalid email format: {email}")
            return None
        
        # Use the simpler approach with value (singular) instead of values (array)
        filter_ = Filter(property_name="email", operator="EQ", value=email)
        group = FilterGroup(filters=[filter_])
        req = PublicObjectSearchRequest(
            filter_groups=[group], 
            sorts=[], 
            properties=["email"], 
            limit=1, 
            after=None
        )
        
        res = client.crm.contacts.search_api.do_search(public_object_search_request=req)
        
        if res.results:
            contact_id = res.results[0].id
            logger.debug(f"Found existing contact with email {email}: {contact_id}")
            return contact_id
        
        return None
    except ContactApiException as e:
        # Use str() to avoid loguru formatting issues with exception objects
        error_msg = str(e)
        logger.warning("Failed to search contact by email {}: {}", email, error_msg)
        return None
    except Exception as e:
        # Use str() to avoid loguru formatting issues with exception objects
        error_msg = str(e)
        logger.warning("Failed to search contact by email {}: {}", email, error_msg)
        return None


def search_company_by_name(company_name: str) -> Optional[str]:
    """
    Search for existing company by name.
    
    Args:
        company_name: Company name to search for
    
    Returns:
        company_id if found, None otherwise
    """
    client = _get_hubspot_client()
    if not client:
        return None
    
    # Validate company_name is not empty
    if not company_name or not company_name.strip():
        logger.warning("Company search skipped: empty company name provided")
        return None
    
    try:
        company_name = company_name.strip()
        filter_group = FilterGroup(filters=[
            Filter(property_name="name", operator="EQ", values=[company_name])
        ])
        
        search_request = PublicObjectSearchRequest(
            filter_groups=[filter_group],
            properties=["name", "website"],
            limit=1
        )
        
        results = client.crm.companies.search_api.do_search(search_request)
        if results.results:
            company_id = results.results[0].id
            logger.debug(f"Found existing company with name {company_name}: {company_id}")
            return company_id
        
        return None
    except CompanyApiException as e:
        # Use str() to avoid loguru formatting issues with exception objects
        error_msg = str(e)
        logger.error("Company search failed for {}: {}", company_name, error_msg)
        return None
    except Exception as e:
        # Use str() to avoid loguru formatting issues with exception objects
        error_msg = str(e)
        logger.error("Company search failed for {}: {}", company_name, error_msg)
        return None


def create_contact(
    firstname: str,
    lastname: str,
    email: str | None = None,
    phone: str | None = None,
    mobilephone: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
    hs_lead_status: str = "NEW",
    lifecyclestage: str | None = None,
    custom_properties: dict | None = None,
    owner_id: str | None = None,
) -> dict | None:
    """
    Create a new contact in HubSpot with optional company association.
    
    Args:
        firstname: Contact first name (required)
        lastname: Contact last name (required)
        email: Contact email address (optional, checked for duplicates)
        phone: Contact phone number (optional)
        mobilephone: Contact mobile phone number (optional)
        company_name: Associated company name (optional)
        company_domain: Company domain (optional)
        hs_lead_status: Lead status from HUBSPOT_LEAD_STATUS enum (default: "NEW")
        lifecyclestage: Stage from LIFECYCLE_STAGE_ORDER (optional)
        custom_properties: Additional custom properties dict (optional)
        owner_id: HubSpot user ID for owner assignment (optional)
    
    Returns:
        dict: Contact data with keys: contact_id, firstname, lastname, email, 
              phone, company_id (if associated), company_name, created_at
        None: On any failure (logs error details)
    
    Examples:
        >>> create_contact("John", "Doe", email="john@example.com")
        {'contact_id': '12345', 'email': 'john@example.com', ...}
        
        >>> create_contact("Jane", "Smith", company_name="Acme Corp")
        {'contact_id': '67890', 'company_id': '54321', ...}
    """
    client = _get_hubspot_client()
    if not client:
        logger.error("HubSpot client not available")
        return None
    
    # Step 1: Validate required fields
    if not firstname or not isinstance(firstname, str) or not firstname.strip():
        logger.error(f"Contact creation failed: Invalid firstname: {firstname}")
        return None
    
    if not lastname or not isinstance(lastname, str) or not lastname.strip():
        logger.error(f"Contact creation failed: Invalid lastname: {lastname}")
        return None
    
    # Step 2: Check for duplicate email
    if email:
        if not isinstance(email, str) or "@" not in email:
            logger.error(f"Invalid email format: {email}")
            return None
        
        existing_contact_id = search_contact_by_email(email)
        if existing_contact_id:
            logger.warning(f"Contact with email {email} already exists: {existing_contact_id}")
            return None
    
    # Step 3: Validate lead status (if provided)
    if hs_lead_status and hs_lead_status not in HUBSPOT_LEAD_STATUS:
        logger.error(f"Invalid hs_lead_status: {hs_lead_status}. Must be one of {HUBSPOT_LEAD_STATUS}")
        return None
    
    # Step 4: Validate lifecycle stage (if provided)
    if lifecyclestage and lifecyclestage not in LIFECYCLE_STAGE_ORDER:
        logger.error(f"Invalid lifecyclestage: {lifecyclestage}. Must be one of {LIFECYCLE_STAGE_ORDER}")
        return None
    
    # Step 5: Validate custom properties (if provided)
    if custom_properties and not isinstance(custom_properties, dict):
        logger.error(f"custom_properties must be dict, got {type(custom_properties)}")
        return None
    
    # Step 6: Build properties dictionary
    properties = {
        "firstname": firstname.strip(),
        "lastname": lastname.strip(),
    }
    
    # Add optional fields if provided
    if email:
        properties["email"] = email.strip().lower()
    if phone:
        properties["phone"] = format_phone_number(phone)
    if mobilephone:
        properties["mobilephone"] = format_phone_number(mobilephone)
    if hs_lead_status:
        properties["hs_lead_status"] = hs_lead_status
    if lifecyclestage:
        properties["lifecyclestage"] = lifecyclestage
    if owner_id:
        properties["hubspotownerId"] = owner_id
    
    # Merge custom properties if provided
    if custom_properties:
        properties.update(custom_properties)
    
    logger.debug(f"Creating contact with properties: {properties}")
    
    # Step 7: Create contact in HubSpot
    try:
        contact_input = SimplePublicObjectInput(properties=properties)
        created_contact = client.crm.contacts.basic_api.create(contact_input)
        contact_id = created_contact.id
        logger.info("Contact created: {} | {} {} | {}", contact_id, firstname, lastname, email or 'no email')
    except ContactApiException as e:
        # Use str() to avoid loguru formatting issues with exception objects
        error_msg = str(e)
        logger.error("Failed to create contact: {}", error_msg)
        return None
    except Exception as e:
        # Use str() to avoid loguru formatting issues with exception objects
        error_msg = str(e)
        logger.error("Unexpected error creating contact: {}", error_msg)
        return None
    
    # Step 8: Handle company association (if provided)
    company_id = None
    if company_name:
        try:
            # Search for existing company by name
            company_id = search_company_by_name(company_name)
            
            if not company_id:
                # Company doesn't exist, create it
                company_properties = {
                    "name": company_name.strip(),
                }
                if company_domain:
                    # Ensure domain doesn't have protocol
                    domain = company_domain.strip()
                    if not domain.startswith(('http://', 'https://')):
                        domain = f"https://{domain}"
                    company_properties["website"] = domain
                
                company_input = CompanyInput(properties=company_properties)
                created_company = client.crm.companies.basic_api.create(company_input)
                company_id = created_company.id
                logger.info("Company created: {} | {}", company_id, company_name)
            
            # Associate contact with company
            client.crm.associations.v4.basic_api.create_default(
                from_object_type="contacts",
                from_object_id=contact_id,
                to_object_type="companies",
                to_object_id=company_id
            )
            logger.info("Contact {} associated with company {}", contact_id, company_id)
            
        except CompanyApiException as e:
            # Use str() to avoid loguru formatting issues with exception objects
            error_msg = str(e)
            logger.error("Failed to handle company association: {}", error_msg)
            # Don't fail contact creation if company association fails
            company_id = None
        except Exception as e:
            # Use str() to avoid loguru formatting issues with exception objects
            error_msg = str(e)
            logger.error("Unexpected error handling company association: {}", error_msg)
            # Don't fail contact creation if company association fails
            company_id = None
    
    # Step 9: Build and return response
    response = {
        "contact_id": contact_id,
        "firstname": firstname.strip(),
        "lastname": lastname.strip(),
        "email": email.strip().lower() if email and isinstance(email, str) else None,
        "phone": phone.strip() if phone and isinstance(phone, str) else None,
        "mobilephone": mobilephone.strip() if mobilephone and isinstance(mobilephone, str) else None,
        "company_id": company_id,
        "company_name": company_name.strip() if company_id else None,
        "hs_lead_status": hs_lead_status,
        "lifecyclestage": lifecyclestage,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    logger.debug(f"Contact creation response: {response}")
    return response


def update_contact(
    contact_id: str,
    firstname: str | None = None,
    lastname: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    mobilephone: str | None = None,
    custom_properties: dict | None = None,
) -> dict | None:
    """
    Update an existing HubSpot contact.
    
    Args:
        contact_id: HubSpot contact ID to update
        firstname: First name (optional)
        lastname: Last name (optional)
        email: Email address (optional)
        phone: Phone number (optional)
        mobilephone: Mobile phone number (optional)
        custom_properties: Dictionary of custom properties to update (optional)
    
    Returns:
        Dictionary with updated contact info if successful, None otherwise
    """
    client = _get_hubspot_client()
    if not client:
        logger.error("HubSpot client not available")
        return None
    
    if not contact_id:
        logger.error("Contact ID is required for update")
        return None
    
    # Build properties dictionary with only provided fields
    properties = {}
    
    if firstname:
        if not isinstance(firstname, str) or not firstname.strip():
            logger.error(f"Invalid firstname: {firstname}")
            return None
        properties["firstname"] = firstname.strip()
    
    if lastname:
        if not isinstance(lastname, str) or not lastname.strip():
            logger.error(f"Invalid lastname: {lastname}")
            return None
        properties["lastname"] = lastname.strip()
    
    if email:
        if not isinstance(email, str) or "@" not in email:
            logger.error(f"Invalid email format: {email}")
            return None
        properties["email"] = email.strip().lower()
    
    if phone:
        properties["phone"] = format_phone_number(phone)
    
    if mobilephone:
        properties["mobilephone"] = format_phone_number(mobilephone)
    
    # Merge custom properties if provided
    if custom_properties:
        if not isinstance(custom_properties, dict):
            logger.error(f"custom_properties must be dict, got {type(custom_properties)}")
            return None
        properties.update(custom_properties)
    
    # If no properties to update, return None
    if not properties:
        logger.warning(f"No properties provided to update contact {contact_id}")
        return None
    
    logger.debug(f"Updating contact {contact_id} with properties: {properties}")
    
    try:
        contact_input = SimplePublicObjectInput(properties=properties)
        updated_contact = client.crm.contacts.basic_api.update(
            contact_id=contact_id,
            simple_public_object_input=contact_input
        )
        
        logger.info("Contact updated: {} | Properties updated: {}", contact_id, list(properties.keys()))
        
        return {
            "contact_id": contact_id,
            "updated_properties": list(properties.keys()),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    except ContactApiException as e:
        error_msg = str(e)
        logger.error("Failed to update contact {}: {}", contact_id, error_msg)
        return None
    except Exception as e:
        error_msg = str(e)
        logger.error("Unexpected error updating contact {}: {}", contact_id, error_msg)
        return None

