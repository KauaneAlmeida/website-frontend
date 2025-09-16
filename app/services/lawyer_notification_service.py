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
            
            # Get lawyer list
            lawyers = get_lawyers_for_notification()
            
            if not lawyers:
                logger.warning("⚠️ No lawyers configured for notifications")
                return {
                    "success": False,
                    "error": "No lawyers configured",
                    "notifications_sent": 0
                }
            
            # Create notification message
            notification_message = create_lead_notification_message(
                lead_name, lead_phone, category
            )
            
            # Add additional context if provided
            if additional_info:
                situation = additional_info.get("situation", "")
                if situation:
                    notification_message += f"\n\nSituação: {situation[:100]}..."
            
            # Send notifications to all lawyers
            results = []
            successful_notifications = 0
            
            for lawyer in lawyers:
                try:
                    lawyer_name = lawyer["name"]
                    lawyer_phone = lawyer["phone"]
                    whatsapp_number = format_lawyer_phone_for_whatsapp(lawyer_phone)
                    
                    logger.info(f"📤 Sending notification to {lawyer_name} ({lawyer_phone})")
                    
                    # Send notification with retry logic
                    success = await self._send_notification_with_retry(
                        whatsapp_number, 
                        notification_message,
                        lawyer_name
                    )
                    
                    results.append({
                        "lawyer": lawyer_name,
                        "phone": lawyer_phone,
                        "success": success,
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    if success:
                        successful_notifications += 1
                        logger.info(f"✅ Notification sent successfully to {lawyer_name}")
                    else:
                        logger.error(f"❌ Failed to send notification to {lawyer_name}")
                    
                    # Small delay between messages to avoid rate limiting
                    await asyncio.sleep(1)
                    
                except Exception as lawyer_error:
                    logger.error(f"❌ Error sending notification to {lawyer.get('name', 'Unknown')}: {str(lawyer_error)}")
                    results.append({
                        "lawyer": lawyer.get("name", "Unknown"),
                        "phone": lawyer.get("phone", "Unknown"),
                        "success": False,
                        "error": str(lawyer_error),
                        "timestamp": datetime.now().isoformat()
                    })
            
            # Log summary
            logger.info(f"📊 Notification summary: {successful_notifications}/{len(lawyers)} sent successfully")
            
            return {
                "success": successful_notifications > 0,
                "notifications_sent": successful_notifications,
                "total_lawyers": len(lawyers),
                "results": results,
                "lead_info": {
                    "name": lead_name,
                    "phone": lead_phone,
                    "category": category
                }
            }
            
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