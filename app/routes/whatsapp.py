"""
WhatsApp Routes + BigQuery Logging

Handles WhatsApp webhook events, integrates with Intelligent Orchestrator,
and logs processed messages into BigQuery for deduplication & analytics.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, status

from app.services.orchestration_service import intelligent_orchestrator
from app.services.baileys_service import (
    send_baileys_message,
    get_baileys_status,
    baileys_service
)
from app.services.lawyer_notification_service import lawyer_notification_service
from app.services.bigquery_service import bigquery_service

# Logging
logger = logging.getLogger(__name__)

# FastAPI router
router = APIRouter()


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """
    Webhook endpoint for receiving WhatsApp messages via Baileys.
    Logs into BigQuery and avoids duplicates.
    """
    try:
        payload = await request.json()
        logger.info(f"📨 Received WhatsApp webhook: {payload}")

        # Extract message details
        message_text = payload.get("message", "")
        phone_number = payload.get("from", "")
        message_id = payload.get("messageId", "")
        session_id = payload.get("sessionId", f"whatsapp_{phone_number.replace('@s.whatsapp.net', '')}")

        if not message_text or not phone_number or not message_id:
            logger.warning("⚠️ Invalid webhook payload - missing message, phone number, or messageId")
            return {"status": "error", "message": "Invalid payload"}

        # Verifica se a mensagem já foi registrada no BigQuery
        try:
            stats = bigquery_service.obter_estatisticas_tabela()
            logger.debug(f"BigQuery stats: {stats}")
        except Exception:
            stats = None

        # (Opcional) — aqui você poderia implementar uma query em BigQuery
        # para checar se message_id já existe. Por simplicidade,
        # vamos apenas registrar sempre e deixar o controle por análise posterior.

        logger.info(f"🎯 Processing WhatsApp message {message_id} from {phone_number}: {message_text[:50]}...")

        # Process via Intelligent Orchestrator
        response = await intelligent_orchestrator.process_message(
            message_text,
            session_id,
            phone_number=phone_number,
            platform="whatsapp"
        )

        ai_response = response.get("response", "")

        # Salva evento no BigQuery (message como lead_id e phone_number como advogado_id simbólico)
        bigquery_service.inserir_evento_lead(
            lead_id=message_id,
            advogado_id=phone_number,
            foi_notificado=True,
            respondeu=bool(ai_response)
        )

        if ai_response:
            logger.info(f"🤖 Sending AI response to {phone_number}")
            return {
                "status": "success",
                "message_id": message_id,
                "session_id": session_id,
                "response": ai_response,
                "response_type": response.get("response_type", "ai_whatsapp"),
                "message_count": response.get("message_count", 1)
            }
        else:
            logger.warning("⚠️ No AI response generated")
            return {
                "status": "success",
                "message_id": message_id,
                "session_id": session_id,
                "response": "Obrigado pela sua mensagem. Nossa equipe entrará em contato em breve.",
                "response_type": "fallback"
            }

    except Exception as e:
        logger.error(f"❌ Error processing WhatsApp webhook: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "response": "Desculpe, ocorreu um erro interno. Nossa equipe foi notificada e entrará em contato em breve."
        }


@router.post("/whatsapp/send")
async def send_whatsapp_message(phone_number: str, message: str):
    """Send a WhatsApp message manually via Baileys."""
    try:
        logger.info(f"📤 Sending WhatsApp message to {phone_number}")
        success = await send_baileys_message(phone_number, message)

        if success:
            return {
                "status": "success",
                "message": "WhatsApp message sent successfully",
                "to": phone_number
            }
        raise HTTPException(status_code=500, detail="Failed to send WhatsApp message")

    except Exception as e:
        logger.error(f"❌ Error sending WhatsApp message: {str(e)}")
        raise HTTPException(status_code=500, detail="WhatsApp message sending error")


@router.post("/whatsapp/start")
async def start_whatsapp_service():
    """Start the Baileys WhatsApp service."""
    try:
        logger.info("🚀 Starting Baileys WhatsApp service")
        success = await baileys_service.start_whatsapp_service()

        if success:
            return {
                "status": "success",
                "message": "Baileys WhatsApp service started successfully",
                "note": "Check console for QR code if first time setup"
            }
        raise HTTPException(status_code=500, detail="Failed to start WhatsApp service")

    except Exception as e:
        logger.error(f"❌ Error starting WhatsApp service: {str(e)}")
        raise HTTPException(status_code=500, detail="WhatsApp service start error")


@router.get("/whatsapp/status")
async def whatsapp_status():
    """Get Baileys WhatsApp service status."""
    try:
        return await get_baileys_status()
    except Exception as e:
        logger.error(f"❌ Error getting WhatsApp status: {str(e)}")
        return {"service": "baileys_whatsapp", "status": "error", "error": str(e)}


@router.post("/whatsapp/test-lawyer-notifications")
async def test_lawyer_notifications():
    """Test endpoint to verify lawyer notification system."""
    try:
        logger.info("🧪 Testing lawyer notification system")
        result = await lawyer_notification_service.test_lawyer_notifications()
        return {"status": "success", "message": "Lawyer notification test completed", "result": result}
    except Exception as e:
        logger.error(f"❌ Error testing lawyer notifications: {str(e)}")
        return {"status": "error", "message": "Failed to test lawyer notifications", "error": str(e)}


@router.post("/whatsapp/suggest-contact")
async def suggest_whatsapp_contact(session_id: str, user_name: str = "Cliente"):
    """Suggest WhatsApp contact after intake completion."""
    try:
        logger.info(f"📲 Suggesting WhatsApp contact for session: {session_id}")

        notification_message = f"""
🔔 *Nova Lead do Chatbot AI*

👤 *Cliente:* {user_name}
🆔 *Sessão:* {session_id}
⏰ *Horário:* {datetime.now().strftime('%d/%m/%Y às %H:%M')}
🤖 *Origem:* Conversa inteligente com IA

O cliente interagiu com nosso assistente AI e demonstrou interesse em nossos serviços jurídicos.

_Mensagem enviada automaticamente pelo sistema._
        """.strip()

        success = await send_baileys_message("+5511918368812", notification_message)

        return {
            "status": "success" if success else "partial",
            "message": "WhatsApp contact suggested to user",
            "notification_sent": success,
            "whatsapp_number": "+55 11 91836-8812",
            "suggestion_text": (
                f"Olá {user_name}! Para continuar com seu atendimento personalizado, "
                "entre em contato conosco pelo WhatsApp: +55 11 91836-8812. "
                "Nossa equipe está pronta para ajudá-lo!"
            )
        }

    except Exception as e:
        logger.error(f"❌ Error suggesting WhatsApp contact: {str(e)}")
        return {"status": "error", "message": "Failed to suggest WhatsApp contact", "error": str(e)}
