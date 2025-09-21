"""
Lead Assignment Service

Service for managing lead assignments to lawyers with clickable links.
Handles assignment logic, Firebase storage, and WhatsApp notifications.
"""

import logging
import os
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from app.services.firebase_service import get_firestore_client
from app.services.baileys_service import baileys_service
from app.config.lawyers import get_lawyers_for_notification, format_lawyer_phone_for_whatsapp

logger = logging.getLogger(__name__)


class LeadAssignmentService:
    """Service for managing lead assignments to lawyers."""
    
    def __init__(self):
           self.base_url = os.getenv("BASE_URL", "https://law-firm-backend-936902782519.us-central1.run.app")
    
    async def create_lead_with_assignment_links(
        self,
        lead_name: str,
        lead_phone: str,
        category: str,
        situation: str = "",
        additional_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Create a new lead and send assignment notifications to all lawyers.
        
        Args:
            lead_name (str): Name of the lead
            lead_phone (str): Phone number of the lead
            category (str): Legal category
            situation (str): Description of the situation
            additional_data (Dict[str, Any]): Additional lead data
            
        Returns:
            Dict[str, Any]: Result of lead creation and notifications
        """
        try:
            # Generate unique lead ID
            lead_id = str(uuid.uuid4())
            
            # Prepare lead data for Firebase
            lead_data = {
                "lead_id": lead_id,
                "lead_name": lead_name,
                "phone": lead_phone,
                "category": category,
                "situation": situation,
                "status": "new",
                "assigned_to": None,
                "assigned_lawyer_id": None,
                "assigned_lawyer_name": None,
                "assigned_at": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            
            # Add additional data if provided
            if additional_data:
                lead_data.update(additional_data)
            
            # Save lead to Firebase
            await self._save_lead_to_firebase(lead_id, lead_data)
            logger.info(f"💾 Lead {lead_id} saved to Firebase")
            
            # Send assignment notifications to all lawyers
            notification_result = await self._send_assignment_notifications(
                lead_id, lead_name, lead_phone, category, situation
            )
            
            return {
                "success": True,
                "lead_id": lead_id,
                "lead_data": lead_data,
                "notifications": notification_result
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating lead with assignment links: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def assign_lead_to_lawyer(
        self,
        lead_id: str,
        lawyer_id: str
    ) -> Dict[str, Any]:
        """
        Assign a lead to a specific lawyer.
        
        Args:
            lead_id (str): ID of the lead to assign
            lawyer_id (str): ID/phone of the lawyer
            
        Returns:
            Dict[str, Any]: Assignment result
        """
        try:
            # Get lead from Firebase
            lead_data = await self._get_lead_from_firebase(lead_id)
            
            if not lead_data:
                return {
                    "success": False,
                    "message": "Lead not found",
                    "status": "not_found"
                }
            
            # Check if already assigned
            if lead_data.get("assigned_to"):
                assigned_lawyer_name = lead_data.get("assigned_lawyer_name", "Unknown Lawyer")
                return {
                    "success": False,
                    "message": f"This lead has already been assigned to {assigned_lawyer_name}.",
                    "status": "already_assigned",
                    "assigned_to": assigned_lawyer_name
                }
            
            # Find lawyer info
            lawyers = get_lawyers_for_notification()
            lawyer_info = None
            for lawyer in lawyers:
                if lawyer["phone"] == lawyer_id or str(lawyer.get("id", lawyer["phone"])) == lawyer_id:
                    lawyer_info = lawyer
                    break
            
            if not lawyer_info:
                return {
                    "success": False,
                    "message": "Lawyer not found",
                    "status": "lawyer_not_found"
                }
            
            # Update lead assignment in Firebase
            assignment_data = {
                "status": "assigned",
                "assigned_to": lawyer_id,
                "assigned_lawyer_id": lawyer_id,
                "assigned_lawyer_name": lawyer_info["name"],
                "assigned_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            
            await self._update_lead_in_firebase(lead_id, assignment_data)
            logger.info(f"✅ Lead {lead_id} assigned to {lawyer_info['name']}")
            
            # Send confirmation to the lawyer who took the case
            await self._send_assignment_confirmation(
                lawyer_info, lead_data["lead_name"], lead_id
            )
            
            # Notify other lawyers that the case has been taken
            await self._notify_other_lawyers_case_taken(
                lead_id, lawyer_info["name"], lead_data["lead_name"], lawyer_id
            )
            
            # Generate WhatsApp redirect URL
            whatsapp_url = self._generate_whatsapp_url(
                lead_data["phone"],
                lead_data["lead_name"],
                lawyer_info["name"],
                lead_data["category"],
                lead_data["situation"]
            )
            
            return {
                "success": True,
                "message": f"You have successfully taken this lead: {lead_data['lead_name']}",
                "status": "assigned",
                "assigned_to": lawyer_info["name"],
                "lead_name": lead_data["lead_name"],
                "whatsapp_url": whatsapp_url
            }
            
        except Exception as e:
            logger.error(f"❌ Error assigning lead: {str(e)}")
            return {
                "success": False,
                "message": "Internal server error",
                "status": "error",
                "error": str(e)
            }
    
    def _generate_whatsapp_url(
        self,
        lead_phone: str,
        lead_name: str,
        lawyer_name: str,
        category: str,
        situation: str
    ) -> str:
        """Generate WhatsApp URL with pre-filled message."""
        # Clean phone number for WhatsApp URL
        clean_phone = ''.join(filter(str.isdigit, lead_phone))
        if not clean_phone.startswith("55"):
            clean_phone = f"55{clean_phone}"
        
        # Create message
        message = f"Olá {lead_name}, Eu sou {lawyer_name} e eu vou cuidar do seu {category} caso. Situação: {situation[:100]}{'...' if len(situation) > 100 else ''}"
        
        # URL encode the message
        import urllib.parse
        encoded_message = urllib.parse.quote(message)
        
        return f"https://wa.me/{clean_phone}?text={encoded_message}"
    
    async def _save_lead_to_firebase(self, lead_id: str, lead_data: Dict[str, Any]) -> bool:
        """Save lead data to Firebase."""
        try:
            db = get_firestore_client()
            db.collection("leads").document(lead_id).set(lead_data)
            return True
        except Exception as e:
            logger.error(f"❌ Error saving lead to Firebase: {str(e)}")
            raise e
    
    async def _get_lead_from_firebase(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Get lead data from Firebase."""
        try:
            db = get_firestore_client()
            doc = db.collection("leads").document(lead_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"❌ Error getting lead from Firebase: {str(e)}")
            return None
    
    async def _update_lead_in_firebase(self, lead_id: str, update_data: Dict[str, Any]) -> bool:
        """Update lead data in Firebase."""
        try:
            db = get_firestore_client()
            db.collection("leads").document(lead_id).update(update_data)
            return True
        except Exception as e:
            logger.error(f"❌ Error updating lead in Firebase: {str(e)}")
            raise e
    
    async def _send_assignment_notifications(
        self,
        lead_id: str,
        lead_name: str,
        lead_phone: str,
        category: str,
        situation: str
    ) -> Dict[str, Any]:
        """Send assignment notifications to all lawyers with clickable links."""
        try:
            lawyers = get_lawyers_for_notification()
            results = []
            successful_notifications = 0
            
            for lawyer in lawyers:
                try:
                    lawyer_id = lawyer["phone"]  # Using phone as lawyer ID
                    assignment_link = f"{self.base_url}/api/v1/leads/{lead_id}/assign/{lawyer_id}"
                    
                    # Create personalized notification message
                    notification_message = f"""🚨 Novo cliente recebido!

Nome: {lead_name}
Telefone: {lead_phone}
Área jurídica: {category}
Situação: {situation[:200]}{'...' if len(situation) > 200 else ''}

👉 Clique no link abaixo se você deseja assumir este caso:
{assignment_link}
"""
                    
                    # Format lawyer phone for WhatsApp
                    whatsapp_number = format_lawyer_phone_for_whatsapp(lawyer["phone"])
                    
                    # Send notification
                    success = await baileys_service.send_whatsapp_message(
                        whatsapp_number, 
                        notification_message
                    )
                    
                    results.append({
                        "lawyer": lawyer["name"],
                        "phone": lawyer["phone"],
                        "success": success,
                        "assignment_link": assignment_link,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
                    if success:
                        successful_notifications += 1
                        logger.info(f"✅ Assignment notification sent to {lawyer['name']}")
                    else:
                        logger.error(f"❌ Failed to send notification to {lawyer['name']}")
                    
                except Exception as lawyer_error:
                    logger.error(f"❌ Error sending notification to {lawyer.get('name', 'Unknown')}: {str(lawyer_error)}")
                    results.append({
                        "lawyer": lawyer.get("name", "Unknown"),
                        "phone": lawyer.get("phone", "Unknown"),
                        "success": False,
                        "error": str(lawyer_error),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
            
            return {
                "success": successful_notifications > 0,
                "notifications_sent": successful_notifications,
                "total_lawyers": len(lawyers),
                "results": results
            }
            
        except Exception as e:
            logger.error(f"❌ Error sending assignment notifications: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "notifications_sent": 0
            }
    
    async def _send_assignment_confirmation(
        self,
        lawyer_info: Dict[str, Any],
        lead_name: str,
        lead_id: str
    ) -> bool:
        """Send confirmation message to lawyer who took the case."""
        try:
            confirmation_message = f"✅ Você assumiu com sucesso este cliente: {lead_name}\n\nLead ID: {lead_id}\n\nPor favor, entre em contato com o cliente o quanto antes."
            
            whatsapp_number = format_lawyer_phone_for_whatsapp(lawyer_info["phone"])
            success = await baileys_service.send_whatsapp_message(
                whatsapp_number, 
                confirmation_message
            )
            
            if success:
                logger.info(f"✅ Assignment confirmation sent to {lawyer_info['name']}")
            else:
                logger.error(f"❌ Failed to send confirmation to {lawyer_info['name']}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error sending assignment confirmation: {str(e)}")
            return False
    
    async def _notify_other_lawyers_case_taken(
        self,
        lead_id: str,
        assigned_lawyer_name: str,
        lead_name: str,
        assigned_lawyer_id: str
    ) -> bool:
        """Notify other lawyers that the case has been taken."""
        try:
            lawyers = get_lawyers_for_notification()
            notification_message = f"ℹ️ O cliente '{lead_name}' foi atribuido por {assigned_lawyer_name}."
            
            for lawyer in lawyers:
                # Skip the lawyer who took the case
                if lawyer["phone"] == assigned_lawyer_id:
                    continue
                
                try:
                    whatsapp_number = format_lawyer_phone_for_whatsapp(lawyer["phone"])
                    await baileys_service.send_whatsapp_message(
                        whatsapp_number, 
                        notification_message
                    )
                    logger.info(f"📢 Notified {lawyer['name']} that case was taken")
                    
                except Exception as e:
                    logger.error(f"❌ Error notifying {lawyer['name']}: {str(e)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error notifying other lawyers: {str(e)}")
            return False


# Global service instance
lead_assignment_service = LeadAssignmentService()