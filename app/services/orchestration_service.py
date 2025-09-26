"""
Intelligent Orchestration Service

This service orchestrates the conversation flow between AI and Firebase fallback systems.
It handles platform-specific logic, session management, and intelligent fallback mechanisms.

FIXED: Placeholder replacement, message templates, and flow handling
"""

import os
import re
import uuid
import logging
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.services.ai_chain import ai_orchestrator
from app.services.firebase_service import (
    get_conversation_flow, 
    get_user_session, 
    save_user_session,
    save_lead_data,
    render_question,
    create_context_from_session_data,
    update_lead_data_field,
    force_update_identification
)
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service

logger = logging.getLogger(__name__)

class IntelligentHybridOrchestrator:
    """
    Intelligent orchestrator that manages conversation flow with proper placeholder replacement.
    """
    
    def __init__(self):
        self.gemini_available = True
        self.last_gemini_check = datetime.now()
        self.gemini_cooldown = timedelta(minutes=5)
        
    async def process_message(
        self, 
        message: str, 
        session_id: str, 
        platform: str = "web",
        phone_number: str = None
    ) -> Dict[str, Any]:
        """
        FIXED: Main message processing with proper placeholder replacement
        """
        try:
            logger.info(f"🎯 Processing message | session={session_id} | platform={platform} | msg='{message[:50]}...'")
            
            # Get or create session
            session_data = await get_user_session(session_id)
            if not session_data:
                session_data = await self._create_new_session(session_id, platform, phone_number)
            
            # Update last message and increment counter
            session_data["last_user_message"] = message.strip()
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            session_data["platform"] = platform
            if phone_number:
                session_data["phone_number"] = phone_number
            
            # Try AI first if available
            if self._should_try_gemini():
                try:
                    ai_response = await self._attempt_gemini_response(message, session_id, session_data)
                    if ai_response:
                        session_data["gemini_available"] = True
                        await save_user_session(session_id, session_data)
                        
                        return {
                            "response": ai_response,
                            "response_type": "ai_intelligent",
                            "ai_mode": True,
                            "gemini_available": True,
                            "session_id": session_id,
                            "platform": platform,
                            "message_count": session_data["message_count"]
                        }
                except Exception as e:
                    logger.warning(f"🚫 Gemini failed, using fallback: {str(e)}")
                    self._mark_gemini_unavailable()
                    session_data["gemini_available"] = False
            
            # Use Firebase fallback flow
            return await self._handle_firebase_fallback(message, session_id, session_data, platform)
            
        except Exception as e:
            logger.error(f"❌ Error in process_message: {str(e)}")
            return {
                "response": "Desculpe, ocorreu um erro. Tente novamente.",
                "response_type": "error",
                "error": str(e),
                "session_id": session_id
            }
    
    async def _create_new_session(self, session_id: str, platform: str, phone_number: str = None) -> Dict[str, Any]:
        """Create new session with proper initialization"""
        session_data = {
            "session_id": session_id,
            "platform": platform,
            "created_at": datetime.now(),
            "last_updated": datetime.now(),
            "message_count": 0,
            "current_step": 1,
            "fallback_completed": False,
            "phone_submitted": False,
            "gemini_available": self.gemini_available,
            "lead_data": {},
            "conversation_history": []
        }
        
        if phone_number:
            session_data["phone_number"] = phone_number
            
        await save_user_session(session_id, session_data)
        logger.info(f"🆕 New session created: {session_id}")
        return session_data
    
    def _should_try_gemini(self) -> bool:
        """Check if we should attempt Gemini AI"""
        if not self.gemini_available:
            # Check if cooldown period has passed
            if datetime.now() - self.last_gemini_check > self.gemini_cooldown:
                logger.info("🔄 Gemini cooldown expired, will retry")
                self.gemini_available = True
                return True
            return False
        return True
    
    async def _attempt_gemini_response(self, message: str, session_id: str, session_data: Dict[str, Any]) -> Optional[str]:
        """Attempt to get response from Gemini AI"""
        try:
            logger.info(f"🤖 Attempting Gemini AI response for session {session_id}")
            
            # Create context from session data
            context = create_context_from_session_data(session_data)
            context["platform"] = session_data.get("platform", "web")
            
            response = await asyncio.wait_for(
                ai_orchestrator.generate_response(message, session_id, context),
                timeout=15.0
            )
            
            if response and len(response.strip()) > 0:
                logger.info(f"✅ Valid Gemini response received for session {session_id}")
                return response.strip()
            
            return None
            
        except asyncio.TimeoutError:
            logger.error("⏰ Gemini API request timed out")
            raise Exception("timeout: Gemini API request timed out")
        except Exception as e:
            error_str = str(e).lower()
            if self._is_quota_error(error_str):
                logger.error(f"🚫 Gemini quota/rate limit error: {e}")
                raise Exception(f"quota: {e}")
            else:
                logger.error(f"❌ Gemini API error: {e}")
                raise e
    
    def _is_quota_error(self, error_str: str) -> bool:
        """Check if error indicates quota/rate limit issues"""
        quota_indicators = [
            "429", "quota", "rate limit", "resourceexhausted", 
            "billing", "too many requests", "quota exceeded"
        ]
        return any(indicator in error_str for indicator in quota_indicators)
    
    def _mark_gemini_unavailable(self):
        """Mark Gemini as unavailable and set cooldown"""
        self.gemini_available = False
        self.last_gemini_check = datetime.now()
        logger.warning(f"🚫 Gemini marked unavailable until {self.last_gemini_check + self.gemini_cooldown}")
    
    async def _handle_firebase_fallback(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any], 
        platform: str
    ) -> Dict[str, Any]:
        """
        FIXED: Handle Firebase fallback with proper placeholder replacement
        """
        try:
            logger.info(f"⚡ Activating Firebase fallback for session {session_id}")
            
            # Check if we're collecting phone number
            if session_data.get("fallback_completed") and not session_data.get("phone_submitted"):
                return await self._handle_phone_collection(message, session_id, session_data)
            
            # Get conversation flow
            flow_data = await get_conversation_flow()
            steps = flow_data.get("steps", [])
            
            if not steps:
                logger.error("❌ No steps found in conversation flow")
                return {
                    "response": "Desculpe, ocorreu um erro no sistema. Tente novamente.",
                    "response_type": "error",
                    "session_id": session_id
                }
            
            # Initialize fallback if needed
            if not session_data.get("fallback_step"):
                session_data["fallback_step"] = 1
                session_data["fallback_completed"] = False
                logger.info(f"🚀 Initialized fallback at step 1 for session {session_id}")
            
            current_step = session_data.get("fallback_step", 1)
            
            # Find current step
            step_data = None
            for step in steps:
                if step.get("id") == current_step:
                    step_data = step
                    break
            
            if not step_data:
                logger.error(f"❌ Step {current_step} not found in flow")
                return await self._complete_fallback_flow(session_id, session_data, flow_data)
            
            # Process user's answer if not the first interaction
            if session_data.get("message_count", 0) > 1:
                answer_processed = await self._process_step_answer(
                    message, current_step, session_id, session_data, step_data
                )
                
                if not answer_processed:
                    # Re-ask the same question with proper context
                    context = create_context_from_session_data(session_data)
                    question = render_question(step_data.get("question", ""), context)
                    
                    return {
                        "response": question,
                        "response_type": "fallback_firebase",
                        "session_id": session_id,
                        "current_step": current_step,
                        "validation_error": True,
                        "ai_mode": False,
                        "gemini_available": False
                    }
                
                # Move to next step
                current_step += 1
                session_data["fallback_step"] = current_step
                
                # Check if flow is complete
                if current_step > len(steps):
                    return await self._complete_fallback_flow(session_id, session_data, flow_data)
                
                # Get next step
                step_data = None
                for step in steps:
                    if step.get("id") == current_step:
                        step_data = step
                        break
                
                if not step_data:
                    return await self._complete_fallback_flow(session_id, session_data, flow_data)
            
            # FIXED: Render question with proper context
            context = create_context_from_session_data(session_data)
            question = render_question(step_data.get("question", ""), context)
            
            # Save session
            await save_user_session(session_id, session_data)
            
            logger.info(f"➡️ Presenting step {current_step} for session {session_id}")
            
            return {
                "response": question,
                "response_type": "fallback_firebase",
                "session_id": session_id,
                "current_step": current_step,
                "ai_mode": False,
                "gemini_available": False,
                "fallback_completed": False,
                "phone_submitted": False
            }
            
        except Exception as e:
            logger.error(f"❌ Error in Firebase fallback: {str(e)}")
            return {
                "response": "Desculpe, ocorreu um erro. Como posso ajudá-lo?",
                "response_type": "fallback_error",
                "session_id": session_id,
                "error": str(e)
            }
    
    async def _process_step_answer(
        self, 
        answer: str, 
        step_id: int, 
        session_id: str, 
        session_data: Dict[str, Any],
        step_data: Dict[str, Any]
    ) -> bool:
        """
        ENHANCED: Process and validate step answers with comprehensive name handling
        """
        try:
            answer = answer.strip()
            field_name = step_data.get("field", f"step_{step_id}")
            
            logger.info(f"💾 Processing answer for step {step_id} | field={field_name} | answer='{answer[:50]}...'")
            
            # Validate answer
            if not self._validate_answer(answer, step_data):
                logger.warning(f"⚠️ Invalid answer for step {step_id}: '{answer}'")
                return False
            
            # Normalize answer based on step type
            normalized_answer = self._normalize_answer(answer, step_id, step_data)
            
            # Store in lead_data with correct field name
            lead_data = session_data.get("lead_data", {})
            lead_data[field_name] = normalized_answer
            
            # CRITICAL: Store name in ALL possible name fields
            if field_name == "identification":
                # Store in all name variations to ensure placeholder replacement works
                lead_data["name"] = normalized_answer
                lead_data["user_name"] = normalized_answer
                lead_data["username"] = normalized_answer
                lead_data["userName"] = normalized_answer
                lead_data["user-name"] = normalized_answer
                lead_data["nome"] = normalized_answer
                lead_data["usuario"] = normalized_answer
                
                logger.info(f"🔧 STORED NAME in all fields: '{normalized_answer}'")
                
            elif field_name == "area_qualification":
                lead_data["area"] = normalized_answer
                lead_data["area_of_law"] = normalized_answer
            elif field_name == "problem_description":
                lead_data["situation"] = normalized_answer
                lead_data["case_details"] = normalized_answer
            elif field_name == "contact_info":
                lead_data["contact"] = normalized_answer
                lead_data["phone"] = normalized_answer
                lead_data["whatsapp"] = normalized_answer
            
            session_data["lead_data"] = lead_data
            
            # Force update in Firebase
            success = await update_lead_data_field(session_id, field_name, normalized_answer)
            if field_name == "identification":
                await force_update_identification(session_id, normalized_answer)
                
                # Also update all name variations in Firebase
                for name_field in ["name", "user_name", "username", "userName"]:
                    await update_lead_data_field(session_id, name_field, normalized_answer)
            
            logger.info(f"💾 Stored answer for step {step_id} | field={field_name} | value='{normalized_answer}' | success={success}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing step answer: {str(e)}")
            return False
    
    def _validate_answer(self, answer: str, step_data: Dict[str, Any]) -> bool:
        """Validate user answer based on step requirements"""
        if not answer or len(answer.strip()) < 1:
            return False
        
        validation = step_data.get("validation", {})
        min_length = validation.get("min_length", 1)
        
        if len(answer.strip()) < min_length:
            return False
        
        # Step-specific validation
        step_type = validation.get("type", "")
        
        if step_type == "name":
            # Name should have at least 2 words
            words = answer.strip().split()
            return len(words) >= 2 and all(len(word) >= 2 for word in words)
        
        elif step_type == "contact_combined":
            # Should contain phone and email
            has_phone = bool(re.search(r'\d{10,13}', answer))
            has_email = bool(re.search(r'[\w\.-]+@[\w\.-]+\.\w+', answer))
            return has_phone or has_email  # At least one
        
        elif step_type == "area":
            # Should be a valid legal area
            return len(answer.strip()) >= 3
        
        elif step_type == "case_description":
            # Should be descriptive enough
            return len(answer.strip()) >= 10
        
        return True
    
    def _normalize_answer(self, answer: str, step_id: int, step_data: Dict[str, Any]) -> str:
        """Normalize answer based on step type"""
        answer = answer.strip()
        
        validation = step_data.get("validation", {})
        normalize_map = validation.get("normalize_map", {})
        
        # Apply normalization map
        answer_lower = answer.lower()
        for key, value in normalize_map.items():
            if key in answer_lower:
                return value
        
        # Step-specific normalization
        step_type = validation.get("type", "")
        
        if step_type == "name":
            return answer.title()
        elif step_type == "area":
            # Common area normalizations
            area_map = {
                "penal": "Direito Penal",
                "criminal": "Direito Penal",
                "crime": "Direito Penal",
                "trabalhista": "Direito Trabalhista",
                "trabalho": "Direito Trabalhista",
                "clt": "Direito Trabalhista",
                "civil": "Direito Civil",
                "civel": "Direito Civil",
                "família": "Direito de Família",
                "familia": "Direito de Família",
                "divorcio": "Direito de Família",
                "saude": "Saúde/Liminares",
                "saúde": "Saúde/Liminares",
                "liminar": "Saúde/Liminares",
                "consumidor": "Direito do Consumidor",
                "tributario": "Direito Tributário",
                "previdenciario": "Direito Previdenciário"
            }
            
            answer_lower = answer.lower().strip()
            for key, value in area_map.items():
                if key in answer_lower:
                    return value
            
            return answer.title()
        
        return answer
    
    async def _complete_fallback_flow(
        self, 
        session_id: str, 
        session_data: Dict[str, Any], 
        flow_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        FIXED: Complete fallback flow with proper message rendering
        """
        try:
            logger.info(f"🎉 Completing fallback flow for session {session_id}")
            
            # Mark as completed
            session_data["fallback_completed"] = True
            session_data["completed_at"] = datetime.now()
            
            # FIXED: Render completion message with context
            context = create_context_from_session_data(session_data)
            completion_message = flow_data.get("completion_message", "Obrigado! Suas informações foram registradas.")
            rendered_message = render_question(completion_message, context)
            
            # Add phone collection prompt
            phone_prompt = "\n\n📱 Para finalizar, preciso do seu número de WhatsApp para que nossos advogados entrem em contato:"
            final_message = rendered_message + phone_prompt
            
            await save_user_session(session_id, session_data)
            
            return {
                "response": final_message,
                "response_type": "fallback_completed",
                "session_id": session_id,
                "fallback_completed": True,
                "phone_submitted": False,
                "ai_mode": False,
                "gemini_available": False,
                "lead_data": session_data.get("lead_data", {})
            }
            
        except Exception as e:
            logger.error(f"❌ Error completing fallback flow: {str(e)}")
            return {
                "response": "Obrigado pelas informações! Para finalizar, preciso do seu número de WhatsApp:",
                "response_type": "fallback_completed",
                "session_id": session_id,
                "fallback_completed": True,
                "phone_submitted": False
            }
    
    async def _handle_phone_collection(
        self, 
        phone_message: str, 
        session_id: str, 
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        FIXED: Handle phone collection with proper validation and WhatsApp integration
        """
        try:
            logger.info(f"📱 Processing phone collection for session {session_id}")
            
            # Validate phone number
            if not self._is_phone_number(phone_message):
                return {
                    "response": "Por favor, informe um número de telefone válido (com DDD):\nExemplo: 11999999999",
                    "response_type": "phone_validation_error",
                    "session_id": session_id,
                    "fallback_completed": True,
                    "phone_submitted": False
                }
            
            # Clean and format phone
            clean_phone = self._clean_phone_number(phone_message)
            
            # Update session
            session_data["phone_submitted"] = True
            session_data["phone_number"] = clean_phone
            session_data["completed_at"] = datetime.now()
            
            # Get user data for messages
            lead_data = session_data.get("lead_data", {})
            user_name = (
                lead_data.get("identification") or 
                lead_data.get("name") or 
                lead_data.get("user_name") or 
                "Cliente"
            )
            
            # FIXED: Create context for message rendering
            context = create_context_from_session_data(session_data)
            context["phone_number"] = clean_phone
            context["user_name"] = user_name
            
            # Save lead data to Firebase
            try:
                lead_record = {
                    "name": user_name,
                    "phone_number": clean_phone,
                    "session_id": session_id,
                    "platform": session_data.get("platform", "web"),
                    **lead_data
                }
                
                lead_id = await save_lead_data(lead_record)
                session_data["lead_id"] = lead_id
                logger.info(f"💾 Lead saved with ID: {lead_id}")
                
            except Exception as save_error:
                logger.error(f"❌ Error saving lead: {save_error}")
            
            # Send WhatsApp messages
            whatsapp_success = await self._send_whatsapp_messages(clean_phone, user_name, lead_data, session_id)
            
            # Notify lawyers
            notification_success = await self._notify_lawyers(user_name, clean_phone, lead_data)
            
            # Save final session
            await save_user_session(session_id, session_data)
            
            # FIXED: Render confirmation message with context
            confirmation_template = """✅ Perfeito, {user_name}! 

Suas informações foram registradas com sucesso:
📱 WhatsApp: {phone_number}

Nossa equipe jurídica especializada entrará em contato em breve pelo WhatsApp para dar continuidade ao seu caso.

Obrigado pela confiança! 🤝"""
            
            confirmation_message = render_question(confirmation_template, context)
            
            return {
                "response": confirmation_message,
                "response_type": "phone_collected_fallback",
                "session_id": session_id,
                "fallback_completed": True,
                "phone_submitted": True,
                "phone_number": clean_phone,
                "whatsapp_sent": whatsapp_success,
                "lawyers_notified": notification_success,
                "lead_data": lead_data,
                "ai_mode": False,
                "gemini_available": False
            }
            
        except Exception as e:
            logger.error(f"❌ Error in phone collection: {str(e)}")
            return {
                "response": "Obrigado! Suas informações foram registradas. Nossa equipe entrará em contato em breve.",
                "response_type": "phone_collected_fallback",
                "session_id": session_id,
                "fallback_completed": True,
                "phone_submitted": True,
                "error": str(e)
            }
    
    def _is_phone_number(self, text: str) -> bool:
        """Check if text contains a valid phone number"""
        # Remove all non-digits
        digits = re.sub(r'\D', '', text)
        
        # Brazilian phone: 10-13 digits
        if 10 <= len(digits) <= 13:
            return True
        
        return False
    
    def _clean_phone_number(self, phone: str) -> str:
        """Clean and format phone number"""
        # Remove all non-digits
        digits = re.sub(r'\D', '', phone)
        
        # Add country code if missing
        if len(digits) == 11 and digits.startswith(('11', '12', '13', '14', '15', '16', '17', '18', '19', '21', '22', '24', '27', '28')):
            digits = f"55{digits}"
        elif len(digits) == 10:
            # Assume it's missing the 9 for mobile
            area_code = digits[:2]
            number = digits[2:]
            if len(number) == 8 and not number.startswith('9'):
                digits = f"55{area_code}9{number}"
            else:
                digits = f"55{digits}"
        
        return digits
    
    async def _send_whatsapp_messages(
        self, 
        phone_number: str, 
        user_name: str, 
        lead_data: Dict[str, Any],
        session_id: str
    ) -> bool:
        """Send WhatsApp messages to user and internal team"""
        try:
            # Format phone for WhatsApp
            whatsapp_phone = f"{phone_number}@s.whatsapp.net"
            
            # FIXED: Create context for message templates
            context = {
                "user_name": user_name,
                "name": user_name,
                "phone_number": phone_number,
                "area": lead_data.get("area_qualification", lead_data.get("area", "Não informado")),
                "situation": lead_data.get("problem_description", lead_data.get("situation", "Não informado"))
            }
            
            # User welcome message template
            welcome_template = """Olá {user_name}! 👋

Recebemos suas informações e nossa equipe jurídica especializada já está analisando seu caso.

📋 Dados confirmados:
• Área: {area}
• Situação: {situation}

Em breve um de nossos advogados entrará em contato para dar continuidade ao atendimento.

Obrigado pela confiança! ⚖️"""
            
            welcome_message = render_question(welcome_template, context)
            
            # Send to user
            user_success = await baileys_service.send_whatsapp_message(whatsapp_phone, welcome_message)
            
            if user_success:
                logger.info(f"📤 Welcome message sent to user {phone_number}")
            else:
                logger.error(f"❌ Failed to send welcome message to {phone_number}")
            
            # Internal notification
            internal_phone = os.getenv("WHATSAPP_PHONE_NUMBER", "5511918368812")
            internal_whatsapp = f"{internal_phone}@s.whatsapp.net"
            
            internal_template = """🚨 Nova Lead Capturada via Chatbot!

👤 Nome: {user_name}
📱 WhatsApp: {phone_number}
⚖️ Área: {area}
📝 Situação: {situation}

🕐 Capturado em: {timestamp}
💻 Plataforma: Web Chat

⚡ AÇÃO NECESSÁRIA: Entre em contato com o cliente o mais rápido possível!"""
            
            context["timestamp"] = datetime.now().strftime("%d/%m/%Y às %H:%M")
            internal_message = render_question(internal_template, context)
            
            # Send internal notification
            internal_success = await baileys_service.send_whatsapp_message(internal_whatsapp, internal_message)
            
            if internal_success:
                logger.info(f"📤 Internal notification sent to {internal_phone}")
            else:
                logger.error(f"❌ Failed to send internal notification")
            
            return user_success and internal_success
            
        except Exception as e:
            logger.error(f"❌ Error sending WhatsApp messages: {str(e)}")
            return False
    
    async def _notify_lawyers(self, user_name: str, phone_number: str, lead_data: Dict[str, Any]) -> bool:
        """Notify lawyers about new lead"""
        try:
            area = lead_data.get("area_qualification", lead_data.get("area", "Não informado"))
            
            notification_result = await lawyer_notification_service.notify_lawyers_of_new_lead(
                lead_name=user_name,
                lead_phone=phone_number,
                category=area,
                additional_info=lead_data
            )
            
            success = notification_result.get("success", False)
            if success:
                logger.info(f"📧 Lawyers notified about lead: {user_name}")
            else:
                logger.error(f"❌ Failed to notify lawyers: {notification_result.get('error', 'Unknown error')}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error notifying lawyers: {str(e)}")
            return False
    
    async def handle_phone_number_submission(
        self, 
        phone_number: str, 
        session_id: str, 
        user_name: str = None
    ) -> Dict[str, Any]:
        """Handle phone number submission from web interface"""
        try:
            logger.info(f"📱 Handling phone submission | session={session_id} | phone={phone_number}")
            
            # Get session data
            session_data = await get_user_session(session_id)
            if not session_data:
                return {
                    "success": False,
                    "error": "Session not found",
                    "message": "Sessão não encontrada. Reinicie o chat."
                }
            
            # Process as phone collection
            result = await self._handle_phone_collection(phone_number, session_id, session_data)
            
            return {
                "success": True,
                "message": "Número de WhatsApp registrado com sucesso!",
                "phone_number": phone_number,
                "whatsapp_sent": result.get("whatsapp_sent", False),
                "lawyers_notified": result.get("lawyers_notified", False),
                "result": result
            }
            
        except Exception as e:
            logger.error(f"❌ Error in phone submission: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Erro ao processar número de WhatsApp. Tente novamente."
            }
    
    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle WhatsApp authorization from web interface"""
        try:
            session_id = auth_data.get("session_id")
            phone_number = auth_data.get("phone_number")
            source = auth_data.get("source", "unknown")
            user_data = auth_data.get("user_data", {})
            
            logger.info(f"🔐 Processing WhatsApp authorization | session={session_id} | source={source}")
            
            # Get or create session
            session_data = await get_user_session(session_id)
            if not session_data:
                session_data = await self._create_new_session(session_id, "whatsapp", phone_number)
            
            # Update with authorization data
            session_data["whatsapp_authorized"] = True
            session_data["authorization_source"] = source
            session_data["phone_number"] = phone_number
            
            # If we have user data from web chat, store it
            if user_data:
                lead_data = session_data.get("lead_data", {})
                
                # Map web data to our structure
                if user_data.get("name"):
                    lead_data["identification"] = user_data["name"]
                    lead_data["name"] = user_data["name"]
                    lead_data["user_name"] = user_data["name"]
                
                if user_data.get("email"):
                    contact_info = lead_data.get("contact_info", "")
                    if contact_info:
                        lead_data["contact_info"] = f"{contact_info}, Email: {user_data['email']}"
                    else:
                        lead_data["contact_info"] = f"Email: {user_data['email']}"
                
                if user_data.get("area"):
                    lead_data["area_qualification"] = user_data["area"]
                    lead_data["area"] = user_data["area"]
                
                if user_data.get("description"):
                    lead_data["problem_description"] = user_data["description"]
                    lead_data["situation"] = user_data["description"]
                
                session_data["lead_data"] = lead_data
            
            await save_user_session(session_id, session_data)
            
            logger.info(f"✅ WhatsApp authorization processed for {session_id}")
            
            return {
                "success": True,
                "message": "WhatsApp authorization processed successfully",
                "session_id": session_id,
                "phone_number": phone_number,
                "source": source
            }
            
        except Exception as e:
            logger.error(f"❌ Error in WhatsApp authorization: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Erro ao processar autorização do WhatsApp"
            }
    
    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Get session context and status"""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"error": "Session not found"}
            
            return {
                "session_id": session_id,
                "platform": session_data.get("platform", "unknown"),
                "created_at": session_data.get("created_at"),
                "message_count": session_data.get("message_count", 0),
                "current_step": session_data.get("fallback_step", 1),
                "fallback_completed": session_data.get("fallback_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "gemini_available": session_data.get("gemini_available", True),
                "lead_data": session_data.get("lead_data", {}),
                "phone_number": session_data.get("phone_number"),
                "whatsapp_authorized": session_data.get("whatsapp_authorized", False)
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting session context: {str(e)}")
            return {"error": str(e)}
    
    async def reset_session(self, session_id: str) -> Dict[str, Any]:
        """Reset a session (useful for testing)"""
        try:
            # Clear session data
            await save_user_session(session_id, None)
            
            logger.info(f"🔄 Session {session_id} reset successfully")
            
            return {
                "success": True,
                "message": f"Session {session_id} reset successfully",
                "session_id": session_id
            }
            
        except Exception as e:
            logger.error(f"❌ Error resetting session: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to reset session"
            }
    
    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Get comprehensive service status"""
        try:
            from app.services.firebase_service import get_firebase_service_status
            from app.services.ai_chain import get_ai_service_status
            
            # Get individual service statuses
            firebase_status = await get_firebase_service_status()
            ai_status = await get_ai_service_status()
            
            # Determine overall status
            firebase_ok = firebase_status.get("status") == "active"
            ai_ok = ai_status.get("status") == "active"
            
            if firebase_ok and (ai_ok or not self.gemini_available):
                overall_status = "active"
            elif firebase_ok:
                overall_status = "degraded"
            else:
                overall_status = "error"
            
            return {
                "overall_status": overall_status,
                "firebase_status": firebase_status,
                "ai_status": ai_status,
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available,
                "last_gemini_check": self.last_gemini_check.isoformat(),
                "features": {
                    "firebase_fallback": firebase_ok,
                    "ai_responses": ai_ok,
                    "session_persistence": firebase_ok,
                    "whatsapp_integration": True,
                    "lawyer_notifications": True,
                    "lead_collection": firebase_ok
                },
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting service status: {str(e)}")
            return {
                "overall_status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

# Global orchestrator instance
intelligent_orchestrator = IntelligentHybridOrchestrator()