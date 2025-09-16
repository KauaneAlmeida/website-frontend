"""
Lawyer Notification Service

Service for sending lead notifications to lawyers via WhatsApp.
Handles the distribution of new lead information to the configured lawyer list.
"""

import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime

from app.config.lawyers import (
    get_lawyers_for_notification,
    format_lawyer_phone_for_whatsapp,
    create_lead_notification_message
)
from app.services.baileys_service import baileys_service
from app.services.lead_assignment_service import lead_assignment_service

logger = logging.getLogger(__name__)


class LawyerNotificationService:
    """Service for managing lawyer notifications."""
    
    def __init__(self):
        self.max_retries = 3
        self.retry_delay = 2  # seconds
    
    async def notify_lawyers_of_new_lead(
        self,
        lead_name: str,
        lead_phone: str,
        category: str,
        additional_info: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Send notification to all configured lawyers about a new lead.
        
        Args:
            lead_name (str): Name of the lead
            lead_phone (str): Phone number of the lead
            category (str): Legal category (Penal or Saúde Liminar)
            additional_info (Dict[str, Any], optional): Additional lead information
            
        Returns:
            Dict[str, Any]: Results of notification attempts
        """
        try:
            logger.info(f"🚨 Sending lead notifications - Name: {lead_name}, Category: {category}")
            
            # Use the new lead assignment service with clickable links
            situation = additional_info.get("situation", "") if additional_info else ""
            
            result = await lead_assignment_service.create_lead_with_assignment_links(
                lead_name=lead_name,
                lead_phone=lead_phone,
                category=category,
                situation=situation,
                additional_data=additional_info
            )
            
            return result.get("notifications", {
                "success": False,
                "error": "Failed to create lead with assignment links",
                "notifications_sent": 0
            })
            
        except Exception as e:
            logger.error(f"❌ Error in lawyer notification service: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "notifications_sent": 0
            }
    
    async def _send_notification_with_retry(
        self,
        whatsapp_number: str,
        message: str,
        lawyer_name: str
    ) -> bool:
        """
        Send notification with retry logic.
        
        Args:
            whatsapp_number (str): WhatsApp number to send to
            message (str): Message to send
            lawyer_name (str): Name of the lawyer (for logging)
            
        Returns:
            bool: True if message was sent successfully
        """
        for attempt in range(self.max_retries):
            try:
                success = await baileys_service.send_whatsapp_message(whatsapp_number, message)
                
                if success:
                    return True
                else:
                    logger.warning(f"⚠️ Attempt {attempt + 1} failed for {lawyer_name}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay)
                    
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1} error for {lawyer_name}: {str(e)}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
        
        return False
    
    async def test_lawyer_notifications(self) -> Dict[str, Any]:
        """
        Test function to verify lawyer notification system.
        
        Returns:
            Dict[str, Any]: Test results
        """
        try:
            test_result = await self.notify_lawyers_of_new_lead(
                lead_name="João Silva (TESTE)",
                lead_phone="11999999999",
                category="Penal",
                additional_info={"situation": "Teste do sistema de notificações"}
            )
            
            return {
                "test_completed": True,
                "result": test_result
            }
            
        except Exception as e:
            logger.error(f"❌ Error in test notification: {str(e)}")
            return {
                "test_completed": False,
                "error": str(e)
            }


# Global service instance
lawyer_notification_service = LawyerNotificationService()