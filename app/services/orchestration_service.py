import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import re
import os

# Configuração de logging otimizada para Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Imports com fallback para evitar erros de deploy
try:
    from services.firebase_service import save_user_session, get_user_session, save_lead_data, get_firebase_service_status
except ImportError:
    logger.warning("Firebase service imports failed - using fallback")
    async def save_user_session(session_id, data): pass
    async def get_user_session(session_id): return None
    async def save_lead_data(data): pass
    async def get_firebase_service_status(): return {"status": "inactive"}

try:
    from services.ai_orchestrator import ai_orchestrator
except ImportError:
    logger.warning("AI orchestrator import failed - using fallback")
    class FallbackAI:
        async def generate_response(self, msg, **kwargs): return "Fallback response"
        def clear_session_memory(self, session_id): pass
    ai_orchestrator = FallbackAI()

try:
    from services.lead_assignment_service import lead_assignment_service
except ImportError:
    logger.warning("Lead assignment service import failed - using fallback")
    class FallbackLead:
        async def create_lead_with_assignment_links(self, **kwargs):
            return {"success": True, "notifications": {"notifications_sent": 0}}
    lead_assignment_service = FallbackLead()

try:
    from services.baileys_service import baileys_service
except ImportError:
    logger.warning("Baileys service import failed - using fallback")
    class FallbackBaileys:
        async def send_whatsapp_message(self, number, message):
            logger.info(f"Fallback: Would send WhatsApp to {number[:10]}...")
            return True
    baileys_service = FallbackBaileys()

try:
    from utils.date_utils import ensure_utc
except ImportError:
    logger.warning("Date utils import failed - using fallback")
    def ensure_utc(dt): return dt

class IntelligentHybridOrchestrator:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.whatsapp_authorized_sessions = set()
        self.unauthorized_whatsapp_sessions = {}
        self.blocked_sessions = set()
        self.gemini_available = False
        self._health_check_cache = None
        self._health_check_timestamp = None
        
        # Cloud Run optimization
        self.startup_complete = False
        self._initialize_async()

    def _initialize_async(self):
        """Initialize async components without blocking startup"""
        try:
            # Marca como inicializado para health checks
            self.startup_complete = True
            logger.info("Orchestrator initialized successfully")
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

    async def health_check(self) -> Dict[str, Any]:
        """Simple health check for Cloud Run"""
        try:
            return {
                "status": "healthy" if self.startup_complete else "starting",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "orchestrator"
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def _get_or_create_session(self, session_id: str, platform: str = "web", phone_number: str = None) -> Dict[str, Any]:
        """Get existing session or create new one with fallback"""
        try:
            session_data = await get_user_session(session_id)
            if session_data:
                return session_data
            
            # Create new session
            now = datetime.now(timezone.utc)
            new_session = {
                "session_id": session_id,
                "platform": platform,
                "fallback_step": 1,
                "lead_data": {},
                "validation_attempts": {1: 0},
                "lead_qualified": False,
                "fallback_completed": False,
                "phone_submitted": False,
                "created_at": now.isoformat(),
                "last_updated": now.isoformat(),
                "message_count": 0
            }
            
            if phone_number:
                new_session["phone_number"] = phone_number
            
            await save_user_session(session_id, new_session)
            return new_session
            
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            # Return minimal fallback session
            return {
                "session_id": session_id,
                "platform": platform,
                "fallback_step": 1,
                "lead_data": {},
                "validation_attempts": {1: 0},
                "lead_qualified": False,
                "fallback_completed": False,
                "phone_submitted": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "message_count": 0
            }

    def _is_whatsapp_session_authorized(self, session_id: str) -> bool:
        """Check if WhatsApp session is authorized"""
        return session_id in self.whatsapp_authorized_sessions

    def _get_whatsapp_authorization_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get WhatsApp authorization data for session"""
        return self.unauthorized_whatsapp_sessions.get(session_id, {}).get("authorization_data")

    async def authorize_whatsapp_session(self, session_id: str, phone_number: str, source: str, user_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Authorize WhatsApp session with comprehensive validation"""
        try:
            logger.info(f"Authorizing WhatsApp session: {session_id}")
            
            # Validate inputs
            if not session_id or not source:
                raise ValueError("Missing required parameters: session_id or source")
            
            # Clean phone number
            phone_clean = ""
            if phone_number:
                phone_clean = re.sub(r'\D', '', phone_number)
                if phone_clean.startswith("55"):
                    phone_clean = phone_clean[2:]
            
            # Create authorization data
            authorization_data = {
                "source": source,
                "phone_number": phone_clean,
                "phone_raw": phone_number,
                "user_data": user_data or {},
                "authorized_at": datetime.now(timezone.utc).isoformat(),
                "page_url": (user_data or {}).get("page_url", ""),
                "user_agent": (user_data or {}).get("user_agent", ""),
                "referrer": (user_data or {}).get("referrer", "")
            }
            
            # Add to authorized sessions
            self.whatsapp_authorized_sessions.add(session_id)
            
            # Store authorization data
            if session_id not in self.unauthorized_whatsapp_sessions:
                self.unauthorized_whatsapp_sessions[session_id] = {}
            self.unauthorized_whatsapp_sessions[session_id]["authorization_data"] = authorization_data
            
            # Remove from blocked if exists
            self.blocked_sessions.discard(session_id)
            
            logger.info(f"WhatsApp session authorized successfully: {session_id}")
            
            return {
                "success": True,
                "session_id": session_id,
                "authorized": True,
                "source": source,
                "phone_formatted": self._format_brazilian_phone(phone_clean) if phone_clean else None,
                "authorization_data": authorization_data
            }
            
        except Exception as e:
            logger.error(f"Error authorizing WhatsApp session: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
                "authorized": False
            }

    async def _get_fallback_response(self, session_data: Dict[str, Any], message: str) -> str:
        """Get fallback response using structured flow with timeout protection"""
        try:
            # Timeout protection for Cloud Run
            async def _process_with_timeout():
                session_id = session_data.get("session_id", "")
                platform = session_data.get("platform", "web")
                
                # Get flow steps based on platform (simplified for Cloud Run)
                if platform == "whatsapp_authorized":
                    steps = [{
                        "id": 1,
                        "field": "confirmation_authorized",
                        "question": "Olá! Vi que você estava interessado em nossos serviços jurídicos. Posso ajudá-lo agora?",
                        "validation": {"type": "confirmation", "required": True},
                        "error_message": "Por favor, confirme se posso ajudá-lo (sim/não):"
                    }]
                    platform_flow = "whatsapp_authorized"
                elif platform.startswith("whatsapp"):
                    steps = [
                        {"id": 1, "field": "identification", "question": "Olá! Sou da equipe m.lima Advocacia. Para melhor atendê-lo, qual seu nome?", "validation": {"type": "name", "min_length": 2, "required": True}, "error_message": "Por favor, informe seu nome:"},
                        {"id": 2, "field": "area_qualification", "question": "Obrigado {user_name}! Em qual área precisa de ajuda?\n\n1️⃣ Direito Penal\n2️⃣ Saúde/Liminares", "validation": {"type": "area", "required": True}, "error_message": "Escolha: Penal ou Saúde?"},
                        {"id": 3, "field": "case_details", "question": "Perfeito! Conte-me mais detalhes sobre sua situação em {area}:", "validation": {"type": "text", "min_length": 10, "required": True}, "error_message": "Preciso de mais detalhes sobre seu caso:"},
                        {"id": 4, "field": "lead_warming", "question": "Entendi sua situação. Nossa equipe pode ajudar com isso. Posso registrar seus dados e um advogado especializado entra em contato?", "validation": {"type": "confirmation", "required": True}, "error_message": "Confirma o contato? (sim/não)"}
                    ]
                    platform_flow = "whatsapp"
                else:
                    steps = [
                        {"id": 1, "field": "identification", "question": "Olá! Bem-vindo ao m.lima Advocacia. Para começar, qual seu nome completo?", "validation": {"type": "name", "min_length": 4, "required": True}, "error_message": "Por favor, informe seu nome completo:"},
                        {"id": 2, "field": "contact_info", "question": "Obrigado {user_name}! Agora preciso de seu contato (telefone e/ou email):", "validation": {"type": "contact", "required": True}, "error_message": "Informe seu telefone ou email:"},
                        {"id": 3, "field": "area_qualification", "question": "Perfeito! Em qual área jurídica você precisa de ajuda?\n\n🔹 Direito Penal\n🔹 Saúde/Liminares", "validation": {"type": "area", "required": True}, "error_message": "Escolha uma das áreas: Penal ou Saúde"},
                        {"id": 4, "field": "case_details", "question": "Ótimo! Conte-me mais detalhes sobre sua situação em {area}:", "validation": {"type": "text", "min_length": 20, "required": True}, "error_message": "Preciso de mais informações sobre seu caso:"},
                        {"id": 5, "field": "lead_warming", "question": "Entendi perfeitamente sua situação. Nossa equipe tem experiência nessa área e pode ajudar. Posso registrar seus dados para um advogado especializado entrar em contato?", "validation": {"type": "confirmation", "required": True}, "error_message": "Confirma o registro? (sim/não)"}
                    ]
                    platform_flow = "web"
                
                # Check if already completed
                if session_data.get("fallback_completed", False):
                    user_name = session_data.get("lead_data", {}).get("identification", "")
                    return f"Obrigado {user_name}! Nossa equipe já foi notificada."
                
                # Process current step
                current_step_id = session_data["fallback_step"]
                lead_data = session_data.get("lead_data", {})
                validation_attempts = session_data.get("validation_attempts", {})
                
                if current_step_id not in validation_attempts:
                    validation_attempts[current_step_id] = 0
                
                current_step = next((s for s in steps if s["id"] == current_step_id), None)
                if not current_step:
                    session_data["fallback_step"] = 1
                    session_data["lead_data"] = session_data.get("lead_data", {})
                    session_data["validation_attempts"] = {1: 0}
                    try:
                        await save_user_session(session_id, session_data)
                    except:
                        pass
                    first_step = next((s for s in steps if s.get("id") == 1), None)
                    if first_step:
                        return self._interpolate_message(first_step.get("question", ""), lead_data)
                    return "Como posso ajudá-lo?"
                
                # Handle WhatsApp greetings only on first step
                if (current_step_id == 1 and platform.startswith("whatsapp") and self._is_whatsapp_greeting(message)):
                    return self._interpolate_message(current_step["question"], lead_data)
                
                # Process user input
                if message and message.strip():
                    validation_attempts[current_step_id] += 1
                    session_data["validation_attempts"] = validation_attempts
                    
                    max_attempts = 2 if platform.startswith("whatsapp") else 3
                    is_flexible = validation_attempts[current_step_id] > max_attempts
                    
                    normalized_answer = self._validate_and_normalize_answer_schema(message, current_step, platform_flow)
                    should_advance = self._should_advance_step_schema(normalized_answer, current_step, is_flexible, platform_flow)
                    
                    if not should_advance:
                        if validation_attempts[current_step_id] >= max_attempts:
                            validation_msg = self._get_simple_error_message(current_step_id, platform_flow)
                        else:
                            validation_msg = current_step.get("error_message", "Resposta inválida.")
                        
                        try:
                            await save_user_session(session_id, session_data)
                        except:
                            pass
                        return validation_msg
                    
                    # Valid answer - advance
                    step_key = current_step.get("field", f"step_{current_step_id}")
                    validation_attempts[current_step_id] = 0
                    lead_data[step_key] = normalized_answer
                    session_data["lead_data"] = lead_data
                    
                    # Extract contact info for web
                    if step_key == "contact_info" and platform == "web":
                        phone, email = self._extract_contact_info(normalized_answer)
                        if phone:
                            session_data["lead_data"]["phone"] = phone
                        if email:
                            session_data["lead_data"]["email"] = email
                    
                    # Find next step
                    next_step_id = current_step_id + 1
                    next_step = next((s for s in steps if s["id"] == next_step_id), None)
                    
                    if next_step:
                        session_data["fallback_step"] = next_step_id
                        validation_attempts[next_step_id] = 0
                        session_data["validation_attempts"] = validation_attempts
                        try:
                            await save_user_session(session_id, session_data)
                        except:
                            pass
                        return self._interpolate_message(next_step.get("question", ""), lead_data)
                    else:
                        session_data["fallback_completed"] = True
                        session_data["lead_qualified"] = True
                        try:
                            await save_user_session(session_id, session_data)
                        except:
                            pass
                        return await self._handle_lead_finalization(session_id, session_data)
                
                return self._interpolate_message(current_step.get("question", ""), lead_data)
            
            # Execute with timeout for Cloud Run
            return await asyncio.wait_for(_process_with_timeout(), timeout=25.0)
            
        except asyncio.TimeoutError:
            logger.warning("Fallback response timeout - returning quick response")
            return "Olá! Nossa equipe entrará em contato em breve."
        except Exception as e:
            logger.error(f"Error in fallback flow: {str(e)}")
            return "Olá! Como posso ajudá-lo?"

    def _is_whatsapp_greeting(self, message: str) -> bool:
        """Check if message is a WhatsApp greeting"""
        if not message:
            return False
        message_lower = message.lower().strip()
        greetings = ['oi', 'olá', 'ola', 'hello', 'hi', 'hey']
        return message_lower in greetings or len(message.strip()) <= 3

    def _get_simple_error_message(self, step_id: int, platform: str) -> str:
        """Get simplified error message for re-prompts"""
        if platform.startswith("whatsapp"):
            messages = {1: "Seu nome:", 2: "Penal ou Saúde?", 3: "Mais detalhes:", 4: "Sim ou não?"}
        else:
            messages = {1: "Preciso do seu nome completo:", 2: "Informe telefone e/ou e-mail:", 3: "Escolha: Penal ou Saúde", 4: "Mais detalhes sobre o caso:", 5: "Confirme: sim ou não?"}
        return messages.get(step_id, "Resposta válida:")

    def _validate_and_normalize_answer_schema(self, answer: str, step_config: Dict[str, Any], platform: str) -> str:
        """Validate and normalize user answer"""
        if not answer:
            return ""
        
        answer = answer.strip()
        step_id = step_config.get("id", 0)
        validation = step_config.get("validation", {})
        
        # Apply normalization map
        normalize_map = validation.get("normalize_map", {})
        if normalize_map:
            answer_lower = answer.lower()
            for keyword, normalized in normalize_map.items():
                if keyword in answer_lower:
                    return normalized
        
        # Field-specific normalization
        field_type = validation.get("type", "")
        
        if field_type == "name":
            return " ".join(word.capitalize() for word in answer.split())
        elif field_type == "area":
            answer_lower = answer.lower()
            area_mapping = {
                ("penal", "criminal", "crime"): "Direito Penal",
                ("saude", "saúde", "liminar", "medica", "médica"): "Saúde/Liminares"
            }
            for keywords, normalized_area in area_mapping.items():
                if any(keyword in answer_lower for keyword in keywords):
                    return normalized_area
            return answer.title()
        elif field_type == "confirmation":
            answer_lower = answer.lower()
            if any(conf in answer_lower for conf in ['sim', 'ok', 'pode', 'claro', 'vamos']):
                return "Confirmado"
            return answer
        
        return answer

    def _should_advance_step_schema(self, answer: str, step_config: Dict[str, Any], is_flexible: bool, platform: str) -> bool:
        """Determine if answer is sufficient to advance to next step"""
        if not answer:
            answer = ""
        
        answer = answer.strip()
        validation = step_config.get("validation", {})
        min_length = validation.get("min_length", 1)
        required = validation.get("required", True)
        step_id = step_config.get("id", 0)
        
        if required and not answer:
            return False
        
        # Platform-specific validation
        if platform == "whatsapp_authorized":
            if step_id == 1:
                answer_lower = answer.lower()
                valid_responses = ['sim', 'não', 'nao', 'yes', 'no', 'ok', 'pode', 'claro']
                return any(response in answer_lower for response in valid_responses) or len(answer) >= 1
        elif platform.startswith("whatsapp"):
            if step_id == 1:
                return len(answer) >= 2 and not answer.isdigit()
            elif step_id == 2:
                answer_lower = answer.lower()
                valid_areas = ["penal", "criminal", "saude", "saúde", "liminar"]
                return any(area in answer_lower for area in valid_areas) or len(answer) >= 3
            elif step_id == 3:
                return len(answer) >= 5 and len(answer.split()) >= 2
            elif step_id == 4:
                answer_lower = answer.lower()
                valid_responses = ['sim', 'não', 'nao', 'ok', 'pode', 'claro']
                return any(response in answer_lower for response in valid_responses)
        else:
            if step_id == 1:
                words = answer.split()
                if is_flexible:
                    return len(words) >= 1 and len(answer) >= 2
                return len(words) >= 2 and len(answer) >= 4
            elif step_id == 2:
                has_phone = bool(re.search(r'\d{10,11}', answer))
                has_email = bool(re.search(r'\S+@\S+\.\S+', answer))
                return has_phone or has_email or (is_flexible and len(answer) >= 8)
            elif step_id == 3:
                answer_lower = answer.lower()
                valid_areas = ["penal", "criminal", "saude", "saúde", "liminar"]
                return any(area in answer_lower for area in valid_areas)
            elif step_id == 4:
                if is_flexible:
                    return len(answer) >= 10
                return len(answer) >= min_length and len(answer.split()) >= 5
            elif step_id == 5:
                answer_lower = answer.lower()
                valid_responses = ['sim', 'não', 'nao', 'ok', 'pode', 'claro']
                return any(response in answer_lower for response in valid_responses)
        
        return len(answer) >= min_length

    def _interpolate_message(self, message: str, lead_data: Dict[str, Any]) -> str:
        """Interpolate variables in message template"""
        try:
            if not message:
                return "Como posso ajudá-lo?"
            
            interpolation_data = {
                "user_name": lead_data.get("identification", ""),
                "area": lead_data.get("area_qualification", ""),
                "contact_info": lead_data.get("contact_info", ""),
                "case_details": lead_data.get("case_details", ""),
                "phone": lead_data.get("phone", "")
            }
            
            for key, value in interpolation_data.items():
                if value and f"{{{key}}}" in message:
                    message = message.replace(f"{{{key}}}", value)
            
            return message
        except Exception as e:
            logger.error(f"Error interpolating message: {str(e)}")
            return message or "Como posso ajudá-lo?"

    def _extract_contact_info(self, contact_text: str) -> tuple:
        """Extract phone and email from combined contact text"""
        if not contact_text:
            return "", ""
        
        phone_match = re.search(r'(\d{10,11})', contact_text)
        email_match = re.search(r'(\S+@\S+\.\S+)', contact_text)
        
        phone = phone_match.group(1) if phone_match else ""
        email = email_match.group(1) if email_match else ""
        
        return phone, email

    def _format_brazilian_phone(self, phone_clean: str) -> str:
        """Format Brazilian phone number with enhanced validation"""
        try:
            if not phone_clean or not phone_clean.strip():
                return "5511999999999"
            
            phone_clean = re.sub(r'\D', '', phone_clean)
            
            if phone_clean.startswith("55"):
                phone_clean = phone_clean[2:]
            
            if len(phone_clean) == 10:
                ddd = phone_clean[:2]
                number = phone_clean[2:]
                if number[0] in ['6', '7', '8', '9'] and len(number) == 8:
                    number = f"9{number}"
                result = f"55{ddd}{number}"
            elif len(phone_clean) == 11:
                result = f"55{phone_clean}"
            elif len(phone_clean) == 13:
                result = phone_clean
            else:
                result = "5511999999999"
            
            return result
            
        except Exception as e:
            logger.error(f"Error formatting phone: {str(e)}")
            return "5511999999999"

    def _build_answers_array(self, platform: str, lead_data: dict, phone_clean: str) -> list:
        """Build answers array based on platform"""
        answers = []
        
        try:
            if platform == "whatsapp_authorized":
                field_mapping = {"confirmation_authorized": 1}
            elif platform.startswith("whatsapp"):
                field_mapping = {"identification": 1, "area_qualification": 2, "case_details": 3, "lead_warming": 4}
            else:
                field_mapping = {"identification": 1, "contact_info": 2, "area_qualification": 3, "case_details": 4, "lead_warming": 5}
            
            for field, step_id in field_mapping.items():
                answer = lead_data.get(field, "")
                if answer:
                    answers.append({"id": step_id, "answer": answer})
            
            if phone_clean:
                answers.append({"id": 99, "field": "phone_extracted", "answer": phone_clean, "platform": platform})
            
            return answers
            
        except Exception as e:
            logger.error(f"Error building answers array: {e}")
            return []

    async def _handle_lead_finalization(self, session_id: str, session_data: Dict[str, Any]) -> str:
        """Handle lead finalization with enhanced error handling and Cloud Run optimization"""
        try:
            # Timeout protection
            async def _finalize_with_timeout():
                if session_data.get("finalization_completed", False):
                    user_name = session_data.get("lead_data", {}).get("identification", "")
                    return f"Obrigado {user_name}! Nossa equipe já foi notificada."
                
                platform = session_data.get("platform", "web")
                lead_data = session_data.get("lead_data", {})
                
                # Extract and validate phone
                phone_clean = lead_data.get("phone", "")
                
                if platform.startswith("whatsapp"):
                    if not phone_clean and session_data.get("phone_number"):
                        raw_phone = session_data["phone_number"].replace("@s.whatsapp.net", "").replace("+", "")
                        if raw_phone.startswith("55"):
                            phone_clean = raw_phone[2:]
                        else:
                            phone_clean = raw_phone
                        session_data["lead_data"]["phone"] = phone_clean
                else:
                    if not phone_clean:
                        contact_info = lead_data.get("contact_info", "")
                        phone_match = re.search(r'(\d{10,11})', contact_info)
                        phone_clean = phone_match.group(1) if phone_match else ""
                
                # Validate phone with fallback
                if not phone_clean or len(phone_clean) < 10:
                    if platform == "web":
                        return "Informe seu WhatsApp com DDD (ex: 11999999999):"
                    else:
                        phone_clean = "11999999999"
                
                # Format phone safely
                try:
                    phone_formatted = self._format_brazilian_phone(phone_clean)
                    whatsapp_number = f"{phone_formatted}@s.whatsapp.net"
                except Exception:
                    phone_formatted = "5511999999999"
                    whatsapp_number = f"{phone_formatted}@s.whatsapp.net"
                
                # Mark as finalized BEFORE external calls
                session_data.update({
                    "phone_number": phone_clean,
                    "phone_formatted": phone_formatted,
                    "phone_submitted": True,
                    "lead_qualified": True,
                    "finalization_completed": True,
                    "finalization_timestamp": datetime.now(timezone.utc).isoformat(),
                    "qualification_completed_at": datetime.now(timezone.utc).isoformat(),
                    "last_updated": datetime.now(timezone.utc).isoformat()
                })
                
                session_data["lead_data"]["phone"] = phone_clean
                
                # Save session
                try:
                    await save_user_session(session_id, session_data)
                except Exception as e:
                    logger.error(f"Failed to save session: {e}")
                
                # Build and save lead data
                answers = self._build_answers_array(platform, lead_data, phone_clean)
                try:
                    if not session_data.get("lead_saved", False):
                        await save_lead_data({"answers": answers})
                        session_data["lead_saved"] = True
                        await save_user_session(session_id, session_data)
                except Exception as e:
                    logger.error(f"Error saving lead: {e}")
                
                # Prepare user data
                user_name = lead_data.get("identification", "Cliente")
                area = lead_data.get("area_qualification", "não informada")
                case_details = lead_data.get("case_details", "não detalhada")
                
                # Send lawyer notifications with timeout
                try:
                    if not session_data.get("lawyers_notified", False):
                        assignment_result = await asyncio.wait_for(
                            lead_assignment_service.create_lead_with_assignment_links(
                                lead_name=user_name,
                                lead_phone=phone_clean,
                                category=area,
                                situation=case_details,
                                additional_data={
                                    "contact_info": lead_data.get("contact_info", f"WhatsApp: {phone_clean}"),
                                    "email": lead_data.get("email", "não informado"),
                                    "urgency": "high",
                                    "platform": platform,
                                    "session_id": session_id
                                }
                            ),
                            timeout=10.0
                        )
                        session_data["lawyers_notified"] = True
                        await save_user_session(session_id, session_data)
                except Exception as e:
                    logger.error(f"Error with lawyer notifications: {e}")
                
                # Prepare final messages
                case_summary = case_details[:100]
                if len(case_details) > 100:
                    case_summary += "..."
                
                # Platform-specific final messaging
                if platform.startswith("whatsapp"):
                    return f"""Perfeito, {user_name}! ✅

Suas informações foram registradas e nossa equipe especializada em {area} foi notificada.

Um advogado experiente entrará em contato aqui no WhatsApp em breve.

📄 Resumo:
• Nome: {user_name}
• Área: {area}
• Situação: {case_summary}

Você está em excelentes mãos! 🤝"""
                else:
                    # Web - send WhatsApp confirmation
                    final_whatsapp_message = f"""Olá {user_name}! 👋

Recebemos sua solicitação do site e nossa equipe de {area} foi notificada.

Um advogado entrará em contato no WhatsApp em breve.

📄 Resumo:
• Nome: {user_name}
• Área: {area}
• Situação: {case_summary}

Aguarde nosso contato! 💼"""

                    # Send WhatsApp with timeout
                    whatsapp_success = False
                    try:
                        await asyncio.wait_for(
                            baileys_service.send_whatsapp_message(whatsapp_number, final_whatsapp_message),
                            timeout=5.0
                        )
                        whatsapp_success = True
                    except Exception as e:
                        logger.error(f"WhatsApp send failed: {e}")
                    
                    # Return web confirmation
                    status_msg = "📱 Confirmação enviada no seu WhatsApp!" if whatsapp_success else "⚠️ Seus dados foram salvos e nossa equipe entrará em contato."
                    
                    return f"""Perfeito, {user_name}! ✅

Suas informações foram registradas e nossa equipe de {area} foi notificada.

Um advogado experiente entrará em contato em breve.

{status_msg}

Obrigado por escolher nossos serviços! 🤝"""
            
            # Execute with timeout for Cloud Run
            return await asyncio.wait_for(_finalize_with_timeout(), timeout=20.0)
                
        except asyncio.TimeoutError:
            logger.warning("Lead finalization timeout")
            user_name = session_data.get("lead_data", {}).get("identification", "")
            return f"Obrigado {user_name}! Nossa equipe entrará em contato em breve."
        except Exception as e:
            logger.error(f"Critical error in lead finalization: {str(e)}")
            user_name = session_data.get("lead_data", {}).get("identification", "")
            return f"Obrigado {user_name}! Suas informações foram registradas e nossa equipe entrará em contato em breve."

    def _should_handle_whatsapp_message(self, session_id: str, message: str) -> tuple:
        """Enhanced WhatsApp message handling logic"""
        try:
            # Check if session is authorized
            if self._is_whatsapp_session_authorized(session_id):
                return True, "authorized"
            
            # Check if session is blocked
            if session_id in self.blocked_sessions:
                return False, "blocked"
            
            # Check rate limiting
            now = datetime.now(timezone.utc)
            if session_id in self.unauthorized_whatsapp_sessions:
                last_message_time = self.unauthorized_whatsapp_sessions[session_id].get("last_message_time")
                if last_message_time:
                    time_diff = (now - last_message_time).total_seconds()
                    if time_diff < 60:
                        return False, "rate_limited"
            
            return False, "session_not_authorized"
            
        except Exception as e:
            logger.error(f"Error in should_handle_whatsapp_message: {e}")
            return False, "error"

    async def process_message(self, message: str, session_id: str, phone_number: Optional[str] = None, platform: str = "web") -> Dict[str, Any]:
        """Main message processing with Cloud Run optimization"""
        try:
            # Cloud Run timeout protection
            async def _process_with_timeout():
                logger.info(f"Processing message - Session: {session_id}, Platform: {platform}")
                
                # WhatsApp authorization check
                if platform == "whatsapp":
                    should_handle, reason = self._should_handle_whatsapp_message(session_id, message)
                    
                    if not should_handle:
                        return {
                            "response_type": f"whatsapp_{reason}",
                            "platform": platform,
                            "session_id": session_id,
                            "response": None,
                            "reason": reason
                        }
                
                # Get or create session
                try:
                    session_data = await self._get_or_create_session(session_id, platform, phone_number)
                except Exception as session_error:
                    return {
                        "response_type": "session_error",
                        "platform": platform,
                        "session_id": session_id,
                        "response": "Erro ao criar sessão. Tente novamente.",
                        "error": str(session_error)
                    }
                
                # Update platform
                if platform == "whatsapp":
                    session_data["platform"] = platform
                
                # Process through fallback flow
                try:
                    fallback_response = await self._get_fallback_response(session_data, message)
                except Exception as fallback_error:
                    logger.error(f"Fallback processing failed: {fallback_error}")
                    fallback_response = "Desculpe, ocorreu um erro. Nossa equipe entrará em contato em breve."
                
                # Update session
                try:
                    session_data["last_message"] = message
                    session_data["last_response"] = fallback_response
                    session_data["last_updated"] = datetime.now(timezone.utc).isoformat()
                    session_data["message_count"] = session_data.get("message_count", 0) + 1
                    await save_user_session(session_id, session_data)
                except Exception as update_error:
                    logger.error(f"Session update failed: {update_error}")
                
                # Determine response type
                if platform == "whatsapp":
                    auth_data = self._get_whatsapp_authorization_data(session_id)
                    response_type = "whatsapp_authorized_flow" if auth_data and auth_data.get("source") == "landing_chat" else "whatsapp_standard_flow"
                else:
                    response_type = "web_structured_flow"
                
                return {
                    "response_type": response_type,
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
                    "message_count": session_data.get("message_count", 1),
                    "authorized": self._is_whatsapp_session_authorized(session_id) if platform == "whatsapp" else True
                }
            
            # Execute with timeout
            return await asyncio.wait_for(_process_with_timeout(), timeout=28.0)
            
        except asyncio.TimeoutError:
            logger.warning("Message processing timeout")
            return {
                "response_type": "timeout_error",
                "platform": platform,
                "session_id": session_id,
                "response": "Nossa equipe entrará em contato em breve.",
                "error": "timeout"
            }
        except Exception as e:
            logger.error(f"Critical error in message processing: {str(e)}")
            return {
                "response_type": "processing_error",
                "platform": platform,
                "session_id": session_id,
                "response": "Erro interno. Nossa equipe entrará em contato em breve.",
                "error": str(e)
            }

    async def get_gemini_health_status(self) -> Dict[str, Any]:
        """Get Gemini AI health status with caching and timeout"""
        now = datetime.now(timezone.utc)
        if self._health_check_cache and self._health_check_timestamp:
            time_diff = (now - self._health_check_timestamp).total_seconds()
            if time_diff < 300:
                return self._health_check_cache
        
        try:
            test_response = await asyncio.wait_for(
                ai_orchestrator.generate_response("test", session_id="__health_check__"),
                timeout=2.0
            )
            
            try:
                ai_orchestrator.clear_session_memory("__health_check__")
            except:
                pass
            
            if test_response and isinstance(test_response, str) and test_response.strip():
                self.gemini_available = True
                result = {"service": "gemini_ai", "status": "active", "available": True, "message": "Gemini AI is operational"}
            else:
                self.gemini_available = False
                result = {"service": "gemini_ai", "status": "inactive", "available": False, "message": "Gemini AI returned invalid response"}
            
            self._health_check_cache = result
            self._health_check_timestamp = now
            return result
            
        except asyncio.TimeoutError:
            self.gemini_available = False
            result = {"service": "gemini_ai", "status": "inactive", "available": False, "message": "Gemini AI timeout"}
            self._health_check_cache = result
            self._health_check_timestamp = now
            return result
        except Exception as e:
            self.gemini_available = False
            result = {"service": "gemini_ai", "status": "error", "available": False, "message": f"Gemini AI error: {str(e)}"}
            self._health_check_cache = result
            self._health_check_timestamp = now
            return result

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Get comprehensive service status with timeout protection"""
        try:
            # Get status with timeout
            firebase_status = await asyncio.wait_for(get_firebase_service_status(), timeout=3.0)
            ai_status = await self.get_gemini_health_status()
            
            firebase_healthy = firebase_status.get("status") == "active"
            ai_healthy = ai_status.get("status") == "active"
            
            overall_status = "active" if firebase_healthy and ai_healthy else ("degraded" if firebase_healthy else "error")
            
            return {
                "overall_status": overall_status,
                "firebase_status": firebase_status,
                "ai_status": ai_status,
                "features": {
                    "conversation_flow": firebase_healthy,
                    "ai_responses": ai_healthy,
                    "fallback_mode": firebase_healthy and not ai_healthy,
                    "whatsapp_integration": True,
                    "whatsapp_authorization": True,
                    "lead_collection": firebase_healthy
                },
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available,
                "whatsapp_sessions": {
                    "authorized": len(self.whatsapp_authorized_sessions),
                    "unauthorized": len(self.unauthorized_whatsapp_sessions),
                    "blocked": len(self.blocked_sessions)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting service status: {str(e)}")
            return {
                "overall_status": "error",
                "firebase_status": {"status": "error", "error": str(e)},
                "ai_status": {"status": "error", "error": str(e)},
                "features": {
                    "conversation_flow": False,
                    "ai_responses": False,
                    "fallback_mode": False,
                    "whatsapp_integration": False,
                    "whatsapp_authorization": False,
                    "lead_collection": False
                },
                "gemini_available": False,
                "fallback_mode": True,
                "error": str(e)
            }

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Get current session context and status with timeout"""
        try:
            session_data = await asyncio.wait_for(get_user_session(session_id), timeout=3.0)
            if not session_data:
                return {"exists": False}

            platform = session_data.get("platform", "unknown")
            
            context = {
                "exists": True,
                "session_id": session_id,
                "platform": platform,
                "fallback_step": session_data.get("fallback_step"),
                "lead_qualified": session_data.get("lead_qualified", False),
                "fallback_completed": session_data.get("fallback_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "lead_data": session_data.get("lead_data", {}),
                "validation_attempts": session_data.get("validation_attempts", {}),
                "available_areas": ["Direito Penal", "Saúde/Liminares"],
                "flow_type": "structured_flow_with_authorization",
                "message_count": session_data.get("message_count", 0),
                "created_at": session_data.get("created_at"),
                "last_updated": session_data.get("last_updated")
            }
            
            if platform == "whatsapp":
                context.update({
                    "authorized": self._is_whatsapp_session_authorized(session_id),
                    "authorization_data": self._get_whatsapp_authorization_data(session_id)
                })
            
            return context
        except Exception as e:
            logger.error(f"Error getting session context: {str(e)}")
            return {"exists": False, "error": str(e)}


# Global instance
intelligent_orchestrator = IntelligentHybridOrchestrator()
hybrid_orchestrator = intelligent_orchestrator