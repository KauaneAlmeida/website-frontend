"""
Lawyer Configuration

Configuration file for lawyer contact information and notifications.
This file contains the list of lawyers who should receive lead notifications.
"""

from typing import List, Dict, Any

# Lawyer contact configuration
LAWYERS = [
    {
        "name": "Advogada Maria Fernanda",
        "phone": "555195690381",
        "specialties": ["Penal", "Saúde Liminar"]
    },
    {
        "name": "Advogado Ricardo", 
        "phone": "5511959840099",
        "specialties": ["Penal", "Saúde Liminar"]
    },
    {
        "name": "Advogado Daniel",
        "phone": "559985252836", 
        "specialties": ["Penal", "Saúde Liminar"]
    }
]

def get_lawyers_for_notification() -> List[Dict[str, Any]]:
    """
    Get list of lawyers who should receive lead notifications.
    
    Returns:
        List[Dict[str, Any]]: List of lawyer information
    """
    return LAWYERS

def format_lawyer_phone_for_whatsapp(phone: str) -> str:
    """
    Format phone number for WhatsApp messaging.
    
    Args:
        phone (str): Raw phone number
        
    Returns:
        str: Formatted phone number for WhatsApp
    """
    # Clean phone number
    clean_phone = ''.join(filter(str.isdigit, phone))
    
    # Ensure it starts with country code if not present
    if not clean_phone.startswith("55"):
        clean_phone = f"55{clean_phone}"
    
    return f"{clean_phone}@s.whatsapp.net"

def create_lead_notification_message(lead_name: str, lead_phone: str, category: str) -> str:
    """
    Create the notification message for lawyers.
    
    NOTE: This function is now deprecated in favor of the new lead assignment service
    which includes clickable links for assignment.
    
    Args:
        lead_name (str): Name of the lead
        lead_phone (str): Phone number of the lead
        category (str): Legal category selected by lead
        
    Returns:
        str: Formatted notification message
    """
    return f"""🚨 New lead received!

Name: {lead_name}
Phone: {lead_phone}
Category: {category}

Please review and decide who will take this case.

NOTE: This message format is deprecated. New leads use clickable assignment links."""