import logging
import json
import os
import re
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from app.services.firebase_service import (
    get_user_session,
    save_user_session,
    save_lead_data,
    get_conversation_flow,
    get_firebase_service_status
)
from app.services.ai_chain import ai_orchestrator
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service

logger = logging.getLogger(__name__)


def ensure_utc(dt: datetime) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class IntelligentHybridOrchestrator:
    def __init__(self):
        self.gemini_available = True
        self.gemini_timeout = 15.0
        self.law_firm_number = "+5511918368812"
        self.schema_flow_cache = None
        self.cache_timestamp = None
        
        # Lista de respostas inválidas comuns para evitar pulos
        self.invalid_responses = {
            'greetings': ['oi', 'olá', 'ola', 'hello', 'hi', 'hey', 'e ai', 'eai', 'opa'],
            'short_responses': ['ok', 'sim', 'não', 'nao', 'yes', 'no', 'k', 'kk', 'kkk'],
            'test_responses': ['teste', 'test', '123', 'abc', 'aaa', 'bbb', 'ccc', 'xxx'],
            'generic': ['p.o.', 'po', 'p.o', '.', '..', '...', 'a', 'aa', 'bb', 'cc']
        }

    def _format_brazilian_phone(self, phone_clean: str) -> str:
        """
        Format Brazilian phone number correctly for WhatsApp.
        Handles all Brazilian area codes (DDDs) properly.
        """
        try:
            # Remove country code if already present
            if phone_clean.startswith("55"):
                phone_clean = phone_clean[2:]
            
            # Handle different input formats
            if len(phone_clean) == 10:
                # Format: DDNNNNNNNNN (10 digits - old format without 9th digit)
                ddd = phone_clean[:2]
                number = phone_clean[2:]
                
                # Add 9th digit for mobile numbers (all modern Brazilian mobiles start with 9)
                if number[0] in ['6', '7', '8', '9']:
                    # Already a mobile number, add 9th digit if missing
                    if len(number) == 8:
                        number = f"9{number}"
                
                return f"55{ddd}{number}"
                
            elif len(phone_clean) == 11:
                # Format: DDNNNNNNNNN (11 digits - already has 9th digit)
                ddd = phone_clean[:2]
                number = phone_clean[2:]
                return f"55{ddd}{number}"
                
            elif len(phone_clean) == 13:
                # Format: 55DDNNNNNNNNN (already formatted)
                return phone_clean
                
            elif len(phone_clean) == 12:
                # Format: 55DDNNNNNNN (missing 9th digit)
                if phone_clean.startswith("55"):
                    ddd = phone_clean[2:4]
                    number = phone_clean[4:]
                    
                    # Add 9th digit for mobile numbers
                    if number[0] in ['6', '7', '8', '9'] and len(number) == 8:
                        number = f"9{number}"
                        
                    return f"55{ddd}{number}"
                else:
                    # 12 digits without country code - probably has extra digit
                    ddd = phone_clean[:2]
                    number = phone_clean[2:]
                    return f"55{ddd}{number}"
            
            else:
                # Fallback - try to guess format
                logger.warning(f"⚠️ Unexpected phone format: {phone_clean} (length: {len(phone_clean)})")
                
                if len(phone_clean) >= 10:
                    ddd = phone_clean[:2]
                    number = phone_clean[2:]
                    
                    # Ensure mobile format
                    if len(number) == 8 and number[0] in ['6', '7', '8', '9']:
                        number = f"9{number}"
                    
                    return f"55{ddd}{number}"
                
                # Last resort
                return f"55{phone_clean}"
                
        except Exception as e:
            logger.error(f"❌ Error formatting phone number {phone_clean}: {str(e)}")
            return f"55{phone_clean}"  # Fallback to basic format

    def _is_invalid_response(self, response: str, context: str = "general") -> bool:
        """
        Verifica se a resposta é inválida baseada em padrões comuns para evitar pulos
        """
        response_lower = response.lower().strip()
        
        # Lista todas as respostas inválidas
        all_invalid = []
        for category in self.invalid_responses.values():
            all_invalid.extend(category)
        
        # Verifica se é uma resposta inválida comum
        if response_lower in all_invalid:
            return True
            
        # Verifica padrões problemáticos
        if len(response.strip()) < 2:
            return True
            
        # Apenas números ou caracteres especiais
        if response.strip().isdigit() and len(response.strip()) < 4:
            return True
            
        # Apenas caracteres repetidos
        if len(set(response.strip().replace(' ', ''))) <= 2 and len(response.strip()) < 4:
            return True
            
        return False

    async def get_gemini_health_status(self) -> Dict[str, Any]:
        """
        Safe health check for Gemini AI service.
        Returns status without raising exceptions.
        """
        try:
            # Quick test of Gemini availability
            test_response = await asyncio.wait_for(
                ai_orchestrator.generate_response(
                    "test", 
                    session_id="__health_check__"
                ),
                timeout=5.0  # Short timeout for health checks
            )
            
            # Clean up test session
            ai_orchestrator.clear_session_memory("__health_check__")
            
            if test_response and isinstance(test_response, str) and test_response.strip():
                self.gemini_available = True
                return {
                    "service": "gemini_ai",
                    "status": "active",
                    "available": True,
                    "message": "Gemini AI is operational"
                }
            else:
                self.gemini_available = False
                return {
                    "service": "gemini_ai", 
                    "status": "inactive",
                    "available": False,
                    "message": "Gemini AI returned invalid response"
                }
                
        except asyncio.TimeoutError:
            self.gemini_available = False
            return {
                "service": "gemini_ai",
                "status": "inactive", 
                "available": False,
                "message": "Gemini AI timeout - likely quota exceeded"
            }
        except Exception as e:
            self.gemini_available = False
            error_str = str(e).lower()
            
            if self._is_quota_error(error_str):
                return {
                    "service": "gemini_ai",
                    "status": "quota_exceeded",
                    "available": False, 
                    "message": f"Gemini API quota exceeded: {str(e)}"
                }
            else:
                return {
                    "service": "gemini_ai",
                    "status": "error",
                    "available": False,
                    "message": f"Gemini AI error: {str(e)}"
                }

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """
        Get comprehensive service status including Firebase, AI, and overall health.
        """
        try:
            # Check Firebase status
            firebase_status = await get_firebase_service_status()
            
            # Check Gemini AI status
            ai_status = await self.get_gemini_health_status()
            
            # Determine overall status
            firebase_healthy = firebase_status.get("status") == "active"
            ai_healthy = ai_status.get("status") == "active"
            
            if firebase_healthy and ai_healthy:
                overall_status = "active"
            elif firebase_healthy:
                overall_status = "degraded"  # Firebase works, AI doesn't
            else:
                overall_status = "error"  # Firebase issues are critical
            
            return {
                "overall_status": overall_status,
                "firebase_status": firebase_status,
                "ai_status": ai_status,
                "features": {
                    "conversation_flow": firebase_healthy,
                    "ai_responses": ai_healthy,
                    "fallback_mode": firebase_healthy and not ai_healthy,
                    "whatsapp_integration": True,  # Assumed available
                    "lead_collection": firebase_healthy
                },
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting overall service status: {str(e)}")
            return {
                "overall_status": "error",
                "firebase_status": {"status": "error", "error": str(e)},
                "ai_status": {"status": "error", "error": str(e)},
                "features": {
                    "conversation_flow": False,
                    "ai_responses": False,
                    "fallback_mode": False,
                    "whatsapp_integration": False,
                    "lead_collection": False
                },
                "gemini_available": False,
                "fallback_mode": True,
                "error": str(e)
            }

    async def _get_or_create_session(
        self,
        session_id: str,
        platform: str,
        phone_number: Optional[str] = None
    ) -> Dict[str, Any]:
        session_data = await get_user_session(session_id)
        
        if not session_data:
            # Create new session with proper initialization
            session_data = {
                "session_id": session_id,
                "platform": platform,
                "created_at": ensure_utc(datetime.now(timezone.utc)),
                "lead_data": {},
                "message_count": 0,
                "fallback_step": None,
                "phone_submitted": False,
                "gemini_available": True,
                "last_gemini_check": None,
                "fallback_completed": False,
                "lead_qualified": False,
                "validation_attempts": {}  # Track validation attempts per step
            }
            logger.info(f"🆕 Created new session {session_id} for platform {platform}")

        if phone_number:
            session_data["phone_number"] = phone_number

        return session_data

    def _is_quota_error(self, error_message: str) -> bool:
        """Check if error is related to API quota/rate limits."""
        quota_indicators = [
            "429", "quota", "rate limit", "exceeded", "ResourceExhausted",
            "billing", "plan", "free tier", "requests per day"
        ]
        return any(indicator.lower() in str(error_message).lower() for indicator in quota_indicators)

    def _is_phone_number(self, message: str) -> bool:
        """Check if message looks like a Brazilian phone number."""
        clean_message = ''.join(filter(str.isdigit, message))
        return len(clean_message) >= 10 and len(clean_message) <= 13

    async def _get_schema_flow(self) -> Dict[str, Any]:
        """Get schema-based conversation flow with caching - NOVO FLUXO APENAS PENAL E SAUDE COM VALIDAÇÃO ROBUSTA."""
        try:
            # Cache for 5 minutes
            if (self.schema_flow_cache is None or 
                self.cache_timestamp is None or
                (datetime.now(timezone.utc) - self.cache_timestamp).seconds > 300):
                
                # Load from ai_schema.json first
                schema_path = "ai_schema.json"
                if os.path.exists(schema_path):
                    with open(schema_path, "r", encoding="utf-8") as f:
                        schema_data = json.load(f)
                        fallback_flow = schema_data.get("fallback_flow", {})
                        
                        if fallback_flow.get("enabled", False):
                            self.schema_flow_cache = fallback_flow
                            self.cache_timestamp = datetime.now(timezone.utc)
                            logger.info("📋 Schema-based conversation flow loaded from ai_schema.json")
                            return self.schema_flow_cache
                
                # NOVO FLUXO HARDCODED - APENAS PENAL E SAUDE COM VALIDAÇÃO ROBUSTA
                self.schema_flow_cache = {
                    "enabled": True,
                    "sequential": True,
                    "steps": [
                        {
                            "id": 1,
                            "field": "identification",
                            "question": "Olá! Seja bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?",
                            "validation": {
                                "min_length": 4,
                                "min_words": 2,
                                "required": True,
                                "type": "name",
                                "strict": True
                            },
                            "error_message": "Por favor, informe seu nome completo (nome e sobrenome). Exemplo: João Silva"
                        },
                        {
                            "id": 2,
                            "field": "contact_info",
                            "question": "Prazer em conhecê-lo, {user_name}! Agora preciso de algumas informações de contato:\n\n📱 Qual o melhor telefone/WhatsApp para contato?\n📧 Você poderia informar seu e-mail também?",
                            "validation": {
                                "min_length": 10,
                                "required": True,
                                "type": "contact_combined",
                                "strict": True
                            },
                            "error_message": "Por favor, informe seu telefone (com DDD) e e-mail. Exemplo: (11) 99999-9999 - joao@email.com"
                        },
                        {
                            "id": 3,
                            "field": "area_qualification",
                            "question": "Perfeito, {user_name}! Com qual área do direito você precisa de ajuda?\n\n• Penal\n• Saúde (ações e liminares médicas)",
                            "validation": {
                                "min_length": 3,
                                "required": True,
                                "type": "area",
                                "strict": True,
                                "normalize_map": {
                                    "penal": "Direito Penal",
                                    "criminal": "Direito Penal", 
                                    "crime": "Direito Penal",
                                    "saude": "Saúde/Liminares",
                                    "saúde": "Saúde/Liminares",
                                    "liminar": "Saúde/Liminares",
                                    "medica": "Saúde/Liminares",
                                    "médica": "Saúde/Liminares"
                                }
                            },
                            "error_message": "Por favor, escolha uma das áreas disponíveis: Penal ou Saúde (liminares médicas)."
                        },
                        {
                            "id": 4,
                            "field": "case_details",
                            "question": "Entendi, {user_name}. Me diga de forma breve sobre sua situação em {area}:\n\n• O caso já está em andamento na justiça ou é uma situação inicial?\n• Existe algum prazo ou audiência marcada?\n• Em qual cidade ocorreu/está ocorrendo?",
                            "validation": {
                                "min_length": 20,
                                "min_words": 5,
                                "required": True,
                                "type": "case_description",
                                "strict": True
                            },
                            "error_message": "Por favor, me conte mais detalhes sobre sua situação. Preciso de pelo menos 20 caracteres para entender seu caso adequadamente."
                        },
                        {
                            "id": 5,
                            "field": "lead_warming",
                            "question": "Obrigado por compartilhar, {user_name}. Casos como o seu em {area} exigem atenção imediata para evitar complicações.\n\nNossos advogados já atuaram em dezenas de casos semelhantes com ótimos resultados. Vou registrar os principais pontos para que o advogado responsável já entenda sua situação e agilize a solução.\n\nEm instantes você será direcionado para um de nossos especialistas. Está tudo certo?",
                            "validation": {
                                "min_length": 1,
                                "required": True,
                                "type": "confirmation",
                                "strict": False
                            },
                            "error_message": "Por favor, confirme se posso prosseguir com o direcionamento. Digite 'sim' ou 'não'."
                        }
                    ],
                    "completion_message": "Perfeito, {user_name}! Um de nossos advogados especialistas em {area} já vai assumir seu atendimento em instantes.\n\nEnquanto isso, fique tranquilo - você está em boas mãos! 🤝\n\nSuas informações foram registradas e o advogado já terá todo o contexto do seu caso."
                }
                self.cache_timestamp = datetime.now(timezone.utc)
                logger.info("📋 Novo fluxo de qualificação carregado (Penal + Saúde) com validação robusta")
            
            return self.schema_flow_cache
        except Exception as e:
            logger.error(f"❌ Error loading schema flow: {str(e)}")
            # Return default NOVO FLUXO if everything fails
            return {
                "enabled": True,
                "sequential": True,
                "steps": [
                    {"id": 1, "field": "identification", "question": "Olá! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?", "validation": {"min_length": 4, "min_words": 2}},
                    {"id": 2, "field": "contact_info", "question": "Prazer, {user_name}! Preciso do seu telefone/WhatsApp e e-mail:", "validation": {"min_length": 10}},
                    {"id": 3, "field": "area_qualification", "question": "Com qual área você precisa de ajuda? Penal ou Saúde (liminares)?", "validation": {"min_length": 3}},
                    {"id": 4, "field": "case_details", "question": "Me conte sobre sua situação: está em andamento? Há prazos? Qual cidade?", "validation": {"min_length": 20, "min_words": 5}},
                    {"id": 5, "field": "lead_warming", "question": "Casos assim precisam de atenção imediata. Nossos advogados têm ótimos resultados. Posso direcioná-lo?", "validation": {"min_length": 1}}
                ],
                "completion_message": "Perfeito! Nossa equipe entrará em contato em breve."
            }

    async def _get_fallback_response(
        self, 
        session_data: Dict[str, Any], 
        message: str
    ) -> str:
        """
        NOVO FLUXO: Firebase-based fallback para TODAS as plataformas COM VALIDAÇÃO ROBUSTA.
        Fluxo: Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Finalização
        """
        try:
            session_id = session_data["session_id"]
            platform = session_data.get("platform", "web")
            
            # CORREÇÃO: Aplica fluxo para TODAS as plataformas
            logger.info(f"⚡ Firebase fallback activated for {platform} session {session_id}")
            
            # Get schema-based conversation flow
            flow = await self._get_schema_flow()
            steps = flow.get("steps", [])
            
            if not steps:
                logger.error("❌ No steps found in schema flow")
                return "Olá! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"
            
            # Sort steps by ID to ensure correct order
            steps = sorted(steps, key=lambda x: x.get("id", 0))
            
            # Initialize validation attempts tracker
            if "validation_attempts" not in session_data:
                session_data["validation_attempts"] = {}
            
            # Initialize fallback_step if not set - SEMPRE start at step 1 (NOVO FLUXO)
            if session_data.get("fallback_step") is None:
                session_data["fallback_step"] = 1  # NOVO FLUXO: Inicia no step 1
                session_data["lead_data"] = {}
                session_data["fallback_completed"] = False
                session_data["lead_qualified"] = False
                session_data["validation_attempts"] = {1: 0}  # Track attempts per step
                await save_user_session(session_id, session_data)
                logger.info(f"🚀 NOVO FLUXO: Schema fallback initialized at step 1 for session {session_id}")
                
                # Return first question directly (step 1)
                first_step = next((s for s in steps if s["id"] == 1), None)
                if first_step:
                    question = self._interpolate_message(first_step["question"], {})
                    logger.info(f"📝 Returning step 1 question: {question[:50]}...")
                    return question
                else:
                    return "Olá! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"
            
            # CORREÇÃO: Verifica se o fluxo já foi completado
            if session_data.get("fallback_completed", False):
                user_name = session_data.get("lead_data", {}).get("identification", "")
                return f"Obrigado {user_name}! Nossa equipe já foi notificada e entrará em contato em breve. 🤝"
            
            current_step_id = session_data["fallback_step"]
            lead_data = session_data.get("lead_data", {})
            validation_attempts = session_data.get("validation_attempts", {})
            
            # Initialize attempts counter for current step
            if current_step_id not in validation_attempts:
                validation_attempts[current_step_id] = 0
            
            logger.info(f"📊 NOVO FLUXO - Current state - Step: {current_step_id}, Attempts: {validation_attempts.get(current_step_id, 0)}, Lead data keys: {list(lead_data.keys())}")
            
            # Find current step in sorted steps
            current_step = next((s for s in steps if s["id"] == current_step_id), None)
            if not current_step:
                logger.error(f"❌ Step {current_step_id} not found. Reset to step 1")
                session_data["fallback_step"] = 1
                session_data["lead_data"] = {}
                session_data["validation_attempts"] = {1: 0}
                await save_user_session(session_id, session_data)
                
                first_step = next((s for s in steps if s.get("id") == 1), None)
                if first_step:
                    return self._interpolate_message(first_step.get("question", ""), {})
                else:
                    return "Olá! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"
            
            # Process user's answer if provided and not empty
            step_key = current_step.get("field", f"step_{current_step_id}")
            
            # CORREÇÃO: Tratamento especial para mensagens iniciais apenas no step 1
            if current_step_id == 1 and message and message.strip().lower() in ['oi', 'olá', 'hello', 'hi', 'ola', 'pronto para conversar', 'pronto pra conversar']:
                # Responde com a primeira pergunta
                return self._interpolate_message(current_step["question"], lead_data)
            
            # If user provided a meaningful answer
            if message and message.strip() and len(message.strip()) > 0:
                # Increment validation attempts
                validation_attempts[current_step_id] = validation_attempts.get(current_step_id, 0) + 1
                session_data["validation_attempts"] = validation_attempts
                
                # Check for too many failed attempts (após 3 tentativas, seja mais flexível)
                max_attempts = 3
                is_flexible = validation_attempts[current_step_id] > max_attempts
                
                # Validate and store the answer
                normalized_answer = self._validate_and_normalize_answer_schema(message, current_step)
                
                # Check if answer should advance step (com flexibilidade após muitas tentativas)
                should_advance = self._should_advance_step_schema(normalized_answer, current_step, is_flexible)
                
                if not should_advance:
                    # Re-prompt same step with validation message
                    logger.info(f"🔄 Invalid answer '{normalized_answer[:30]}...' for step {current_step_id} (attempt {validation_attempts[current_step_id]}), re-prompting")
                    
                    # Mensagem de erro mais específica após múltiplas tentativas
                    if validation_attempts[current_step_id] >= max_attempts:
                        if current_step_id == 1:
                            validation_msg = "Preciso do seu nome completo para continuar. Por favor, digite seu nome e sobrenome (exemplo: João Silva):"
                        elif current_step_id == 2:
                            validation_msg = "Preciso de seu telefone e/ou e-mail. Por favor, digite ao menos um contato válido:"
                        elif current_step_id == 3:
                            validation_msg = "Por favor, escolha apenas: 'Penal' ou 'Saúde'"
                        elif current_step_id == 4:
                            validation_msg = "Preciso de mais detalhes sobre sua situação jurídica. Conte-me pelo menos uma frase sobre seu caso:"
                        else:
                            validation_msg = "Por favor, confirme digitando 'sim' ou 'não':"
                    else:
                        validation_msg = current_step.get("error_message", "Por favor, forneça uma resposta válida.")
                    
                    # Save session with updated attempts
                    await save_user_session(session_id, session_data)
                    
                    question = self._interpolate_message(current_step["question"], lead_data)
                    return f"{validation_msg}\n\n{question}"
                
                # Reset attempts counter for this step (successful validation)
                validation_attempts[current_step_id] = 0
                
                # Store the valid answer
                lead_data[step_key] = normalized_answer
                session_data["lead_data"] = lead_data
                
                # Special handling for contact_info extraction
                if step_key == "contact_info":
                    phone, email = self._extract_contact_info(normalized_answer)
                    if phone:
                        session_data["lead_data"]["phone"] = phone
                    if email:
                        session_data["lead_data"]["email"] = email
                
                logger.info(f"💾 Stored answer for step {current_step_id}: {normalized_answer[:30]}...")
                
                # Find next step in sequence
                next_step_id = current_step_id + 1
                next_step = next((s for s in steps if s["id"] == next_step_id), None)
                
                if next_step:
                    # Advance to next step
                    session_data["fallback_step"] = next_step_id
                    # Initialize attempts for next step
                    validation_attempts[next_step_id] = 0
                    session_data["validation_attempts"] = validation_attempts
                    await save_user_session(session_id, session_data)
                    logger.info(f"➡️ Advanced to step {next_step_id} for session {session_id}")
                    return self._interpolate_message(next_step.get("question", ""), lead_data)
                else:
                    # All steps completed - finalize lead qualification
                    session_data["fallback_completed"] = True
                    session_data["lead_qualified"] = True
                    await save_user_session(session_id, session_data)
                    logger.info(f"✅ NOVO FLUXO: Lead qualification completed for session {session_id}")
                    
                    # Finalize the lead automatically
                    return await self._handle_lead_finalization(session_id, session_data)
            else:
                # No meaningful message provided, return current question
                logger.info(f"📝 No meaningful message, returning current step {current_step_id} question")
                return self._interpolate_message(current_step.get("question", ""), lead_data)
            
            # Fallback: return current question
            logger.info(f"📝 Fallback: returning current step {current_step_id} question")
            return self._interpolate_message(current_step.get("question", ""), lead_data)
            
        except Exception as e:
            logger.error(f"❌ Error in Firebase fallback: {str(e)}")
            return "Olá! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"

    def _interpolate_message(self, message: str, lead_data: Dict[str, Any]) -> str:
        """Interpolate variables in message template - NOVO FLUXO."""
        try:
            if not message:
                return "Como posso ajudá-lo?"
                
            # Map NOVO FLUXO field names to user-friendly variables
            interpolation_data = {
                "user_name": lead_data.get("identification", ""),
                "area": lead_data.get("area_qualification", ""),
                "contact_info": lead_data.get("contact_info", ""),
                "case_details": lead_data.get("case_details", ""),
                "phone": lead_data.get("phone", "")
            }
            
            # Only interpolate if we have the required data
            for key, value in interpolation_data.items():
                if value and f"{{{key}}}" in message:
                    message = message.replace(f"{{{key}}}", value)
            
            return message
        except Exception as e:
            logger.error(f"❌ Error interpolating message: {str(e)}")
            return message

    def _extract_contact_info(self, contact_text: str) -> tuple:
        """Extract phone and email from combined contact text."""
        phone_match = re.search(r'(\d{10,11})', contact_text)
        email_match = re.search(r'(\S+@\S+\.\S+)', contact_text)
        
        phone = phone_match.group(1) if phone_match else ""
        email = email_match.group(1) if email_match else ""
        
        return phone, email

    def _validate_and_normalize_answer_schema(self, answer: str, step_config: Dict[str, Any]) -> str:
        """Validate and normalize answers based on schema configuration - NOVO FLUXO COM VALIDAÇÃO ROBUSTA."""
        answer = answer.strip()
        step_id = step_config.get("id", 0)
        validation = step_config.get("validation", {})
        
        # Apply normalization map if available
        normalize_map = validation.get("normalize_map", {})
        if normalize_map:
            answer_lower = answer.lower()
            for keyword, normalized in normalize_map.items():
                if keyword in answer_lower:
                    return normalized
        
        # Field-specific validation and normalization - NOVO FLUXO
        field_type = validation.get("type", "")
        
        if field_type == "name" or step_id == 1:  # Identification step
            # Remove common invalid patterns
            if self._is_invalid_response(answer, "name"):
                return answer  # Return as-is, will be caught by should_advance
            
            if len(answer.split()) >= 2:
                return " ".join(word.capitalize() for word in answer.split())
            else:
                return answer.capitalize()
        elif field_type == "contact_combined" or step_id == 2:  # Contact info step
            return answer  # Mantém como está para extração posterior
        elif field_type == "area" or step_id == 3:  # Area qualification step  
            answer_lower = answer.lower()
            
            # APENAS PENAL E SAUDE - Mapeamento simplificado
            area_mapping = {
                ("penal", "criminal", "crime", "direito penal"): "Direito Penal",
                ("saude", "saúde", "liminar", "saude liminar", "saúde liminar", "health", "injunction", "medica", "médica"): "Saúde/Liminares"
            }
            
            for keywords, normalized_area in area_mapping.items():
                if any(keyword in answer_lower for keyword in keywords):
                    return normalized_area
            
            # Se não encontrou correspondência, retorna capitalizado
            return answer.title()
        elif field_type == "case_description" or step_id == 4:  # Case details step
            return answer
        elif field_type == "confirmation" or step_id == 5:  # Lead warming step
            answer_lower = answer.lower()
            if any(conf in answer_lower for conf in ['sim', 'ok', 'pode', 'claro', 'vamos', 'confirmo']):
                return "Confirmado"
            return answer
        elif field_type == "phone":
            return ''.join(filter(str.isdigit, answer))
        
        return answer

    def _should_advance_step_schema(self, answer: str, step_config: Dict[str, Any], is_flexible: bool = False) -> bool:
        """
        Determine if answer is sufficient to advance to next step - NOVO FLUXO COM VALIDAÇÃO ROBUSTA.
        is_flexible = True após múltiplas tentativas falhadas
        """
        answer = answer.strip()
        validation = step_config.get("validation", {})
        min_length = validation.get("min_length", 1)
        min_words = validation.get("min_words", 1)
        required = validation.get("required", True)
        strict = validation.get("strict", False)
        step_id = step_config.get("id", 0)
        
        if required and (not answer or len(answer) < 1):
            return False
        
        # Validação básica de tamanho
        if len(answer) < min_length and not is_flexible:
            return False
        
        # Flexible mode - aceita respostas menores após múltiplas tentativas
        if is_flexible and len(answer) >= 2:
            logger.info(f"📋 Flexible validation enabled for step {step_id}")
            
        # Step-specific validation - NOVO FLUXO COM VALIDAÇÃO ROBUSTA
        if step_id == 1:  # Identification step - VALIDAÇÃO RIGOROSA DE NOME
            # Rejeita respostas inválidas comuns
            if self._is_invalid_response(answer, "name"):
                return False
                
            # Rejeita apenas números
            if answer.isdigit():
                return False
                
            # Rejeita respostas muito curtas (menos de 4 chars)
            if len(answer) < 4 and not is_flexible:
                return False
                
            words = answer.split()
            
            # Modo flexível - aceita após 3 tentativas
            if is_flexible:
                return len(words) >= 1 and len(answer) >= 2
                
            # Modo normal - exige pelo menos 2 palavras
            if len(words) >= min_words:
                # Verifica se cada palavra tem pelo menos 2 caracteres
                valid_words = [w for w in words if len(w) >= 2 and not w.isdigit()]
                return len(valid_words) >= 2
                
            # Aceita nomes compostos ou únicos mais longos
            return len(answer) >= 6 and not answer.isdigit()
            
        elif step_id == 2:  # Contact info step - VALIDAÇÃO DE CONTATO
            answer_lower = answer.lower()
            has_phone = bool(re.search(r'\d{10,11}', answer))
            has_email = bool(re.search(r'\S+@\S+\.\S+', answer))
            has_contact_words = any(word in answer_lower for word in ['telefone', 'celular', 'whatsapp', 'email', 'gmail', 'hotmail', 'outlook'])
            
            # Rejeita respostas inválidas
            if self._is_invalid_response(answer, "contact"):
                return False
                
            # Modo flexível
            if is_flexible:
                return has_phone or has_email or has_contact_words or len(answer) >= 8
                
            # Modo normal - precisa ter telefone OU email OU pelo menos mencionar contato
            return has_phone or has_email or (has_contact_words and len(answer) >= min_length)
            
        elif step_id == 3:  # Area qualification step - APENAS PENAL E SAUDE
            answer_lower = answer.lower()
            valid_areas = [
                "penal", "criminal", "crime", "direito penal",
                "saude", "saúde", "liminar", "saude liminar", "saúde liminar", "health", "medica", "médica"
            ]
            
            # Rejeita respostas inválidas
            if self._is_invalid_response(answer, "area"):
                return False
                
            # Verifica se menciona uma área válida
            has_valid_area = any(keyword in answer_lower for keyword in valid_areas)
            
            # Modo flexível
            if is_flexible:
                return has_valid_area or len(answer) >= 3
                
            # Modo normal
            return has_valid_area
            
        elif step_id == 4:  # Case details step - VALIDAÇÃO DE SITUAÇÃO JURÍDICA
            # Rejeita respostas inválidas
            if self._is_invalid_response(answer, "case"):
                return False
                
            words = answer.split()
            
            # Modo flexível
            if is_flexible:
                return len(answer) >= 10 and len(words) >= 3
                
            # Modo normal - exige descrição mais detalhada
            return len(answer) >= min_length and len(words) >= min_words
            
        elif step_id == 5:  # Lead warming step - CONFIRMAÇÃO
            answer_lower = answer.lower()
            valid_responses = [
                'sim', 'não', 'nao', 'yes', 'no', 'ok', 'pode', 'claro', 'vamos', 'confirmo',
                'perfeito', 'beleza', 'certo', 'tudo bem', 'pode ser', 'vamos lá', 'tabom', 'blz',
                'aceito', 'concordo', 'negativo', 'positivo'
            ]
            
            # Para confirmação, é sempre flexível
            return any(response in answer_lower for response in valid_responses) or len(answer) >= 1
        
        # Default validation - modo flexível vs rigoroso
        if is_flexible:
            return len(answer) >= 2
        else:
            return len(answer) >= min_length

    async def _handle_lead_finalization(
        self,
        session_id: str,
        session_data: Dict[str, Any]
    ) -> str:
        """
        Handle lead finalization after step 5 completion - NOVO FLUXO.
        """
        try:
            # Get lead data
            lead_data = session_data.get("lead_data", {})
            
            # Extract phone from contact_info if not already extracted
            phone_clean = lead_data.get("phone", "")
            if not phone_clean:
                contact_info = lead_data.get("contact_info", "")
                phone_match = re.search(r'(\d{10,11})', contact_info)
                phone_clean = phone_match.group(1) if phone_match else ""
            
            # Validate phone number
            if not phone_clean or len(phone_clean) < 10:
                return "Não conseguimos identificar seu telefone nas informações fornecidas. Por favor, informe seu WhatsApp com DDD (exemplo: 11999999999):"

            # Format phone number for WhatsApp
            phone_formatted = self._format_brazilian_phone(phone_clean)
            whatsapp_number = f"{phone_formatted}@s.whatsapp.net"

            # Update session data
            session_data.update({
                "phone_number": phone_clean,
                "phone_formatted": phone_formatted,
                "phone_submitted": True,
                "lead_qualified": True,
                "qualification_completed_at": ensure_utc(datetime.now(timezone.utc)),
                "last_updated": ensure_utc(datetime.now(timezone.utc))
            })
            
            # Ensure phone is stored in lead_data
            session_data["lead_data"]["phone"] = phone_clean
            await save_user_session(session_id, session_data)

            # Build answers array for lead saving - NOVO FLUXO
            answers = []
            
            # Map NOVO FLUXO fields to answers
            field_mapping = {
                "identification": 1,
                "contact_info": 2, 
                "area_qualification": 3,
                "case_details": 4,
                "lead_warming": 5
            }
            
            for field, step_id in field_mapping.items():
                answer = lead_data.get(field, "")
                if answer:
                    answers.append({"id": step_id, "answer": answer})
            
            # Add phone as separate entry if available
            if phone_clean:
                answers.append({"id": 99, "field": "phone_extracted", "answer": phone_clean})

            # Save lead data
            try:
                await save_lead_data({"answers": answers})
                logger.info(f"💾 NOVO FLUXO: Qualified lead saved for session {session_id}: {len(answers)} answers")
                
                # Prepare data BEFORE sending notifications - NOVO FLUXO
                user_name = lead_data.get("identification", "Cliente")
                area = lead_data.get("area_qualification", "não informada")
                case_details = lead_data.get("case_details", "não detalhada")
                contact_info = lead_data.get("contact_info", "não informado")
                email = lead_data.get("email", "não informado")

                # Send notifications to lawyers
                try:
                    notification_result = await lawyer_notification_service.notify_lawyers_of_new_lead(
                        lead_name=user_name,
                        lead_phone=phone_clean,
                        category=area,
                        additional_info={
                            "case_details": case_details,
                            "contact_info": contact_info,
                            "email": email,
                            "urgency": "high",  # Leads qualificados são sempre alta prioridade
                            "lead_temperature": "hot",
                            "flow_type": "novo_fluxo_qualificacao"
                        }
                    )
                    
                    if notification_result.get("success"):
                        notifications_sent = notification_result.get("notifications_sent", 0)
                        total_lawyers = notification_result.get("total_lawyers", 0)
                        logger.info(f"✅ NOVO FLUXO: Lawyer notifications sent: {notifications_sent}/{total_lawyers}")
                    else:
                        logger.error(f"❌ Failed to send lawyer notifications: {notification_result.get('error', 'Unknown error')}")
                        
                except Exception as notification_error:
                    logger.error(f"❌ Error sending lawyer notifications: {str(notification_error)}")
                    # Don't fail the entire flow if notifications fail
                    
            except Exception as save_error:
                logger.error(f"❌ Error saving lead: {str(save_error)}")

            # Prepare data for final WhatsApp message - NOVO FLUXO
            case_summary = case_details[:100]
            if len(case_details) > 100:
                case_summary += "..."

            # Create the final WhatsApp message - NOVO FLUXO
            final_whatsapp_message = f"""Olá {user_name}! Obrigado pelas informações! 👋

Recebemos sua solicitação através do nosso site e nossa equipe especializada em {area} já foi notificada.

Um de nossos advogados experientes entrará em contato diretamente com você no WhatsApp em breve. 🤝

📄 Resumo registrado:

- 👤 Nome: {user_name}
- ⚖️ Área: {area}
- 📝 Situação: {case_summary}

Você está em excelentes mãos! Nossa equipe do m.lima tem vasta experiência em casos similares.

Aguarde nosso contato! 💼"""

            # Send single final WhatsApp message
            whatsapp_success = False
            try:
                # Send final message to user
                logger.info(f"📤 NOVO FLUXO: Enviando WhatsApp para: {whatsapp_number} (DDD: {phone_clean[:2]})")
                await baileys_service.send_whatsapp_message(whatsapp_number, final_whatsapp_message)
                logger.info(f"📤 NOVO FLUXO: WhatsApp confirmation sent to {phone_formatted}")
                
                whatsapp_success = True
                
            except Exception as whatsapp_error:
                logger.error(f"❌ Error sending WhatsApp: {str(whatsapp_error)}")
                whatsapp_success = False

            # Return confirmation message for web interface - NOVO FLUXO
            final_message = f"""Perfeito, {user_name}! ✅

Suas informações foram registradas com sucesso e nossa equipe especializada em {area} foi notificada.

Um advogado experiente do m.lima entrará em contato em breve para dar continuidade ao seu caso.

{'📱 Confirmação enviada no seu WhatsApp!' if whatsapp_success else '⚠️ Houve um problema ao enviar a confirmação no WhatsApp, mas suas informações foram salvas com sucesso.'}

Obrigado por escolher nossos serviços jurídicos! 🤝"""

            return final_message
            
        except Exception as e:
            logger.error(f"❌ Error in lead finalization: {str(e)}")
            user_name = session_data.get("lead_data", {}).get("identification", "")
            return f"Obrigado pelas informações, {user_name}! Nossa equipe entrará em contato em breve."

    async def _handle_phone_collection(
        self, 
        phone_message: str, 
        session_id: str, 
        session_data: Dict[str, Any]
    ) -> str:
        """
        Handle phone number collection - ADAPTADO PARA NOVO FLUXO.
        Agora é usado apenas em casos especiais onde telefone não foi extraído.
        """
        try:
            # Clean and validate phone number
            phone_clean = ''.join(filter(str.isdigit, phone_message))
            
            # Validate Brazilian phone number format
            if len(phone_clean) < 10 or len(phone_clean) > 13:
                return "Número inválido. Por favor, digite no formato com DDD (exemplo: 11999999999, 21987654321):"

            # Update session data with phone
            session_data["lead_data"]["phone"] = phone_clean
            
            # Call lead finalization
            return await self._handle_lead_finalization(session_id, session_data)
            
        except Exception as e:
            logger.error(f"❌ Error in phone collection handling: {str(e)}")
            user_name = session_data.get("lead_data", {}).get("identification", "")
            return f"Obrigado pelas informações, {user_name}! Nossa equipe entrará em contato em breve."

    async def process_message(
        self,
        message: str,
        session_id: str,
        phone_number: Optional[str] = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        Main message processing with platform-specific handling - NOVO FLUXO.
        - TODAS as plataformas: Usam NOVO FLUXO DE QUALIFICACAO (5 steps) COM VALIDAÇÃO ROBUSTA
        """
        try:
            logger.info(f"🎯 NOVO FLUXO: Processing message - Session: {session_id}, Platform: {platform}")
            logger.info(f"📝 Message content: '{message[:100]}...' (length: {len(message)})")

            session_data = await self._get_or_create_session(session_id, platform, phone_number)
            logger.info(f"📊 NOVO FLUXO: Session state - Step: {session_data.get('fallback_step')}, Qualified: {session_data.get('lead_qualified')}, Phone submitted: {session_data.get('phone_submitted')}")

            # Handle phone collection para casos especiais onde telefone não foi extraído
            if (session_data.get("lead_qualified") and 
                not session_data.get("phone_submitted") and 
                self._is_phone_number(message)):
                
                logger.info(f"📱 NOVO FLUXO: Processing phone number submission")
                phone_response = await self._handle_phone_collection(message, session_id, session_data)
                return {
                    "response_type": "phone_collected_novo_fluxo",
                    "platform": platform,
                    "session_id": session_id,
                    "response": phone_response,
                    "phone_submitted": True,
                    "message_count": session_data.get("message_count", 0) + 1
                }

            # CORREÇÃO PRINCIPAL: TODAS AS PLATAFORMAS usam o mesmo fluxo estruturado COM VALIDAÇÃO
            logger.info(f"🌐 Platform {platform} - using NOVO FLUXO DE QUALIFICACAO COM VALIDAÇÃO ROBUSTA")
            fallback_response = await self._get_fallback_response(session_data, message)
            
            # Update session
            session_data["last_message"] = message
            session_data["last_response"] = fallback_response
            session_data["last_updated"] = ensure_utc(datetime.now(timezone.utc))
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            await save_user_session(session_id, session_data)
            
            return {
                "response_type": f"{platform}_novo_fluxo_qualificacao_validado",
                "platform": platform,
                "session_id": session_id,
                "response": fallback_response,
                "ai_mode": False,
                "fallback_step": session_data.get("fallback_step"),
                "lead_qualified": session_data.get("lead_qualified", False),
                "fallback_completed": session_data.get("fallback_completed", False),
                "lead_data": session_data.get("lead_data", {}),
                "validation_attempts": session_data.get("validation_attempts", {}),
                "available_areas": ["Direito Penal", "Saúde/Liminares"],
                "message_count": session_data.get("message_count", 1)
            }

        except Exception as e:
            logger.error(f"❌ Error in NOVO FLUXO orchestration: {str(e)}")
            return {
                "response_type": "orchestration_error_silent",
                "platform": platform,
                "session_id": session_id,
                "response": None,
                "error": str(e)
            }

    async def handle_phone_number_submission(
        self,
        phone_number: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Handle phone number submission from web interface - NOVO FLUXO.
        """
        try:
            session_data = await get_user_session(session_id) or {}
            response = await self._handle_phone_collection(phone_number, session_id, session_data)
            return {
                "status": "success",
                "message": response,
                "phone_submitted": True,
                "flow_type": "novo_fluxo_qualificacao_validado"
            }
        except Exception as e:
            logger.error(f"❌ Error in handle_phone_number_submission: {str(e)}")
            return {
                "status": "error",
                "message": "Erro ao processar número de WhatsApp",
                "error": str(e)
            }

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Get current session context and status - NOVO FLUXO."""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"exists": False}

            return {
                "exists": True,
                "session_id": session_id,
                "platform": session_data.get("platform", "unknown"),
                "fallback_step": session_data.get("fallback_step"),
                "lead_qualified": session_data.get("lead_qualified", False),
                "fallback_completed": session_data.get("fallback_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "lead_data": session_data.get("lead_data", {}),
                "validation_attempts": session_data.get("validation_attempts", {}),
                "available_areas": ["Direito Penal", "Saúde/Liminares"],
                "flow_type": "novo_fluxo_qualificacao_validado",
                "message_count": session_data.get("message_count", 0),
                "created_at": session_data.get("created_at"),
                "last_updated": session_data.get("last_updated")
            }
        except Exception as e:
            logger.error(f"❌ Error getting session context: {str(e)}")
            return {"exists": False, "error": str(e)}


# Global instance
intelligent_orchestrator = IntelligentHybridOrchestrator()
hybrid_orchestrator = intelligent_orchestrator