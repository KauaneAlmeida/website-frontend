"""
Lawyer Notification Service

Service for sending lead notifications to lawyers via WhatsApp.
Now uses the new lead assignment service with clickable links.
"""

import logging
from typing import Dict, Any

from app.services.lead_assignment_service import lead_assignment_service

logger = logging.getLogger(__name__)


class LawyerNotificationService:
    """Service for managing lawyer notifications."""
    
    async def notify_lawyers_of_new_lead(
        self,
        lead_name: str = None,
        lead_phone: str = None,
        category: str = None,
        additional_info: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Send notification to all configured lawyers about a new lead with clickable assignment links.
        
        Args:
            lead_name (str): Name of the lead
            lead_phone (str): Phone number of the lead
            category (str): Legal category (Penal or Saúde Liminar)
            additional_info (Dict[str, Any], optional): Additional lead information
            
        Returns:
            Dict[str, Any]: Results of notification attempts
        """
        try:
            # Garantir que sempre tenha um nome, mesmo se não vier do Orchestration
            safe_lead_name = lead_name or (additional_info.get("name") if additional_info else None) or "Cliente não identificado"
            safe_lead_phone = lead_phone or (additional_info.get("phone") if additional_info else None) or "Telefone não informado"
            safe_category = category or (additional_info.get("area") if additional_info else None) or "Categoria não informada"

            situation = additional_info.get("situation", "") if additional_info else ""

            logger.info(
                f"🚨 Creating lead with assignment links - "
                f"Name: {safe_lead_name}, Phone: {safe_lead_phone}, Category: {safe_category}"
            )
            
            # Usar o serviço de assignment
            result = await lead_assignment_service.create_lead_with_assignment_links(
                lead_name=safe_lead_name,
                lead_phone=safe_lead_phone,
                category=safe_category,
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

    
    async def test_lawyer_notifications(self) -> Dict[str, Any]:
        """
        Test function to verify lawyer notification system with assignment links.
        
        Returns:
            Dict[str, Any]: Test results
        """
        try:
            test_result = await self.notify_lawyers_of_new_lead(
                lead_name="João Silva (TESTE)",
                lead_phone="11999999999",
                category="Penal",
                additional_info={"situation": "Teste do sistema de notificações com links de atribuição"}
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
