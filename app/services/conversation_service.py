"""
Conversation Flow Routes

Handles intelligent conversation flow using AI orchestration.
Web platform uses Firebase structured flow.
WhatsApp platform uses structured flow via orchestrator.
"""

import uuid
import logging
import json
import os
from typing import Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.models.request import ConversationRequest
from app.models.response import ConversationResponse
from app.services.orchestration_service import intelligent_orchestrator
from app.services.firebase_service import get_firebase_service_status

# Logging
logger = logging.getLogger(__name__)

# FastAPI router
router = APIRouter()


@router.post("/conversation/start", response_model=ConversationResponse)
async def start_conversation():
    """
    Start a new conversation session for web platform.
    Uses Firebase structured flow for web lead collection.
    """
    try:
        session_id = str(uuid.uuid4())
        logger.info(f"🚀 Starting new web conversation | session={session_id}")

        # Start with Firebase flow for web platform
        result = await intelligent_orchestrator.process_message(
            "olá", 
            session_id, 
            platform="web"
        )
        
        response_data = ConversationResponse(
            session_id=session_id,
            response=result.get("response"),
            ai_mode=False,  # Web uses structured Firebase flow
            flow_completed=result.get("flow_completed", False),
            phone_collected=result.get("phone_collected", False),
            lead_data=result.get("lead_data", {}),
            message_count=result.get("message_count", 1)
        )
        
        logger.info(f"✅ Web conversation started | session={session_id} | response_length={len(response_data.response)}")
        
        # Return with explicit CORS headers
        return JSONResponse(
            content=response_data.dict(),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error starting web conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start conversation: {str(e)}"
        )


@router.post("/conversation/respond", response_model=ConversationResponse)
async def respond_to_conversation(request: ConversationRequest):
    """
    Process user response with Firebase structured flow for web platform.
    
    The system handles:
    - Structured conversation flow
    - Lead information collection
    - Sequential question progression
    - Phone number collection and submission
    """
    try:
        # Generate session ID if not provided
        if not request.session_id:
            request.session_id = str(uuid.uuid4())
            logger.info(f"🆕 Generated new web session: {request.session_id}")

        logger.info(f"📝 Processing web response | session={request.session_id} | msg='{request.message[:50]}...'")

        # Process via Intelligent Orchestrator (web platform uses Firebase flow)
        result = await intelligent_orchestrator.process_message(
            request.message,
            request.session_id,
            platform="web"
        )
        
        response_data = ConversationResponse(
            session_id=request.session_id,
            response=result.get("response", "Como posso ajudá-lo?"),
            ai_mode=False,  # Web uses structured Firebase flow
            flow_completed=result.get("flow_completed", False),
            phone_collected=result.get("phone_collected", False),
            lead_data=result.get("lead_data", {}),
            message_count=result.get("message_count", 1)
        )
        
        # Log completion status
        if response_data.flow_completed:
            logger.info(f"🎉 Web flow completed | session={request.session_id}")
        if response_data.phone_collected:
            logger.info(f"📱 Phone collected via web | session={request.session_id}")
        
        # Return with explicit CORS headers
        return JSONResponse(
            content=response_data.dict(),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error processing web response | session={getattr(request, 'session_id', 'unknown')}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process conversation response: {str(e)}"
        )


@router.post("/conversation/submit-phone")
async def submit_phone_number(request: dict):
    """
    Submit phone number and trigger WhatsApp flow connection.
    This finalizes the web intake and prepares for WhatsApp handover.
    """
    try:
        phone_number = request.get("phone_number", "").strip()
        session_id = request.get("session_id", "").strip()
        user_name = request.get("user_name", "Cliente").strip()
        
        if not phone_number or not session_id:
            logger.warning(f"⚠️ Invalid phone submission | phone={bool(phone_number)} | session={bool(session_id)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing phone_number or session_id"
            )
        
        logger.info(f"📱 Phone number submitted | session={session_id} | number={phone_number} | user={user_name}")

        # Process phone submission via orchestrator
        result = await intelligent_orchestrator.handle_phone_number_submission(
            phone_number, 
            session_id,
            user_name=user_name
        )
        
        logger.info(f"✅ Phone submission processed | session={session_id} | success={result.get('success', False)}")
        
        return {
            **result,
            "timestamp": datetime.now().isoformat(),
            "platform": "web_to_whatsapp_handover"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing phone submission | session={request.get('session_id', 'unknown')}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process phone number submission: {str(e)}"
        )


@router.get("/conversation/status/{session_id}")
async def get_conversation_status(session_id: str):
    """
    Get current conversation state for a session.
    Works for both web and WhatsApp sessions.
    """
    try:
        logger.info(f"📊 Fetching conversation status | session={session_id}")
        
        status_info = await intelligent_orchestrator.get_session_context(session_id)
        
        # Determine platform from session_id
        platform = "whatsapp" if session_id.startswith("whatsapp_") else "web"
        
        return {
            "session_id": session_id,
            "platform": platform,
            "status_info": status_info,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error getting status for session {session_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversation status: {str(e)}"
        )


@router.get("/conversation/ai-config")
async def get_ai_config():
    """
    Get AI system configuration for debugging/admin purposes.
    Shows current prompts and system settings.
    """
    try:
        from app.services.ai_chain import ai_orchestrator

        config = {}
        if os.path.exists("ai_schema.json"):
            with open("ai_schema.json", "r", encoding="utf-8") as f:
                config = json.load(f)

        return {
            "current_system_prompt": ai_orchestrator.get_system_prompt(),
            "full_config": config,
            "config_source": "ai_schema.json" if config else "default",
            "editable_location": "ai_schema.json in project root or AI_SYSTEM_PROMPT in .env",
            "environment_prompt": bool(os.getenv("AI_SYSTEM_PROMPT")),
            "api_key_configured": bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error getting AI config: {str(e)}")
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.get("/conversation/flow")
async def get_conversation_flow():
    """
    Get current conversation approach information.
    Shows how different platforms are handled.
    """
    try:
        return {
            "approach": "platform_specific_structured_handling",
            "description": "Both web and WhatsApp now use structured flows for lead collection",
            "platforms": {
                "web": {
                    "method": "Firebase structured flow",
                    "description": "Sequential questions via Firebase service",
                    "fields": ["name", "area_of_law", "situation", "consent"],
                    "completion": "Phone number collection + handover to WhatsApp"
                },
                "whatsapp": {
                    "method": "Structured flow via orchestrator",
                    "description": "Intelligent structured questions with AI assistance",
                    "fields": ["name", "area_of_law", "situation", "consent"],
                    "completion": "Direct lawyer notification + handover"
                }
            },
            "features": [
                "Platform-specific structured flows",
                "Consistent lead collection across platforms",
                "No AI free-form responses for lead collection",
                "Automatic lawyer notifications",
                "Session continuity tracking",
                "Manual lawyer handover after completion"
            ],
            "lead_collection": {
                "method": "structured_flows_both_platforms",
                "web_approach": "Firebase sequential questions",
                "whatsapp_approach": "Orchestrator structured questions",
                "common_fields": ["name", "area_of_law", "situation", "consent"]
            },
            "configuration": {
                "web_flow": "Firebase-based sequential questions",
                "whatsapp_flow": "Orchestrator structured questions",
                "final_step": "Lawyer notification + handover",
                "handover": "Manual lawyer takeover after lead completion"
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error retrieving conversation flow info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversation flow information: {str(e)}"
        )


@router.get("/conversation/service-status")
async def conversation_service_status():
    """
    Check overall conversation service health with comprehensive status information.
    """
    try:
        # Get comprehensive status from orchestrator
        service_status = await intelligent_orchestrator.get_overall_service_status()

        return {
            "service": "structured_conversation_service",
            "status": service_status.get("overall_status", "unknown"),
            "approach": "platform_specific_structured_flows",
            "firebase_status": service_status.get("firebase_status", {"status": "unknown"}),
            "ai_status": service_status.get("ai_status", {"status": "unknown"}),
            "features": service_status.get("features", {}),
            "platforms": {
                "web": {
                    "method": "Firebase structured flow",
                    "status": service_status.get("firebase_status", {}).get("status", "unknown")
                },
                "whatsapp": {
                    "method": "Orchestrator structured questions",
                    "status": service_status.get("ai_status", {}).get("status", "unknown")
                }
            },
            "endpoints": {
                "start": "/api/v1/conversation/start",
                "respond": "/api/v1/conversation/respond",
                "submit_phone": "/api/v1/conversation/submit-phone",
                "status": "/api/v1/conversation/status/{session_id}",
                "ai_config": "/api/v1/conversation/ai-config",
                "flow_info": "/api/v1/conversation/flow",
                "service_status": "/api/v1/conversation/service-status"
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error getting conversation service status: {str(e)}")
        return {
            "service": "structured_conversation_service", 
            "status": "error", 
            "approach": "platform_specific_structured_flows",
            "firebase_status": {"status": "error"},
            "ai_status": {"status": "error"},
            "features": {},
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.post("/conversation/reset-session/{session_id}")
async def reset_conversation_session(session_id: str):
    """
    Reset a conversation session (useful for testing).
    """
    try:
        logger.info(f"🔄 Resetting session: {session_id}")
        
        result = await intelligent_orchestrator.reset_session(session_id)
        
        return {
            "status": "success",
            "message": f"Session {session_id} reset successfully",
            "session_id": session_id,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error resetting session {session_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset session: {str(e)}"
        )