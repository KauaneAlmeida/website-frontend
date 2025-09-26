"""
Intelligent Orchestration Service - VERSÃO COMPLETAMENTE CORRIGIDA PARA PLACEHOLDERS

PRINCIPAIS CORREÇÕES:
1. Mapeamento correto de campos Firebase para placeholders
2. Processamento robusto de placeholders com fallbacks múltiplos
3. Sincronização melhorada de dados entre Firebase e sessão
4. Validação e logs detalhados para debug
5. Fallback manual para casos críticos
"""

import logging
import re
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from app.services.firebase_service import (
    get_conversation_flow,
    save_user_session,
    get_user_session,
    save_lead_data,
    get_firebase_service_status,
    render_question,
    create_context_from_session_data,
    force_update_identification
)
from app.services.ai_chain import ai_orchestrator
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service

logger = logging.getLogger(__name__)


class IntelligentHybridOrchestrator:
    """
    Orchestrador unificado com processamento robusto de placeholders.
    TOTALMENTE CORRIGIDO para problemas de substituição de placeholders.
    """

    def __init__(self):
        self.gemini_unavailable_until = None
        self.gemini_check_interval = timedelta(minutes=5)
        self.flow_cache = None
        self.flow_cache_timestamp = None
        self.flow_cache_ttl = timedelta(minutes=10)

    async def process_message(
        self,
        message: str,
        session_id: str,
        phone_number: str = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        Ponto de entrada principal com tratamento robusto de erros.
        """
        try:
            logger.info(f"🎯 INÍCIO - Processing message | platform={platform} | session={session_id} | msg='{message[:50]}...'")

            if not message or not message.strip():
                logger.warning("⚠️ Mensagem vazia recebida")
                return {
                    "response": "Por favor, digite uma mensagem válida.",
                    "response_type": "validation_error",
                    "session_id": session_id,
                    "error": "empty_message"
                }

            # Get or create session
            session_data = await self._get_or_create_session(session_id, platform, phone_number)
            logger.info(f"📊 Sessão: step={session_data.get('current_step')} | flow_completed={session_data.get('flow_completed')} | collecting_phone={session_data.get('collecting_phone')}")
            
            # Check if collecting phone number
            if session_data.get("collecting_phone"):
                return await self._handle_phone_collection(message, session_id, session_data)
            
            # Check if flow is completed and should use AI
            if session_data.get("flow_completed") and session_data.get("phone_collected"):
                return await self._handle_ai_conversation(message, session_id, session_data)
            
            # Handle structured flow progression
            return await self._handle_structured_flow(message, session_id, session_data, platform)

        except Exception as e:
            logger.error(f"❌ ERRO CRÍTICO na orquestração | session={session_id}: {str(e)}")
            import traceback
            logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
            
            return {
                "response": "Desculpe, ocorreu um erro. Vamos começar novamente - qual é o seu nome completo?",
                "response_type": "error_fallback",
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "error": str(e)
            }

    def _process_placeholders_in_text(self, text: str, session_data: Dict[str, Any]) -> str:
        """
        CORREÇÃO DEFINITIVA - Processamento baseado na documentação fornecida
        """
        try:
            if not text or "{" not in text:
                return text
            
            logger.info("="*60)
            logger.info("🔧 RENDER_FIXED - PROCESSAMENTO DE PLACEHOLDERS")
            logger.info(f"📝 Template original: '{text}'")
            
            # Extrair lead_data
            lead_data = session_data.get("lead_data", {})
            logger.info(f"📊 Lead data disponível: {lead_data}")
            
            # MAPEAMENTO COMPLETO baseado na documentação
            placeholder_map = {}
            
            # 1. NOME/IDENTIFICAÇÃO - múltiplas fontes e aliases
            identification = (
                lead_data.get("identification") or 
                lead_data.get("name") or 
                lead_data.get("user_name") or
                session_data.get("last_user_message", "") or
                ""
            ).strip()
            
            if identification:
                name_aliases = [
                    "{user_name}", "{user name}", "{name}", "{identification}",
                    "{Name}", "{USER_NAME}", "{ username }", "{ user_name }",
                    "{ name }", "{nome}", "{usuario}", "{cliente}"
                ]
                for alias in name_aliases:
                    placeholder_map[alias] = identification
                logger.info(f"✅ FIXED: Nome '{identification}' mapeado para {len(name_aliases)} aliases")
            
            # 2. CONTATO - múltiplos aliases
            contact_info = (
                lead_data.get("contact_info") or 
                lead_data.get("contact") or 
                lead_data.get("phone") or
                session_data.get("phone_number", "") or
                ""
            ).strip()
            
            if contact_info:
                contact_aliases = [
                    "{contact_info}", "{contact}", "{phone}", "{telefone}",
                    "{contato}", "{whatsapp}"
                ]
                for alias in contact_aliases:
                    placeholder_map[alias] = contact_info
                logger.info(f"✅ FIXED: Contato '{contact_info}' mapeado")
            
            # 3. ÁREA DO DIREITO - múltiplos aliases
            area_qualification = (
                lead_data.get("area_qualification") or 
                lead_data.get("area") or 
                lead_data.get("area_of_law") or
                ""
            ).strip()
            
            if area_qualification:
                area_aliases = [
                    "{area}", "{area_of_law}", "{area_qualification}",
                    "{area_direito}", "{especialidade}"
                ]
                for alias in area_aliases:
                    placeholder_map[alias] = area_qualification
                logger.info(f"✅ FIXED: Área '{area_qualification}' mapeada")
            
            # 4. SITUAÇÃO/PROBLEMA - múltiplos aliases
            problem_description = (
                lead_data.get("problem_description") or 
                lead_data.get("situation") or 
                lead_data.get("case_details") or
                ""
            ).strip()
            
            if problem_description:
                situation_aliases = [
                    "{situation}", "{case_details}", "{problem_description}",
                    "{situacao}", "{problema}", "{caso}"
                ]
                for alias in situation_aliases:
                    placeholder_map[alias] = problem_description
                logger.info(f"✅ FIXED: Situação mapeada")
            
            logger.info(f"🔧 PLACEHOLDER_MAP completo criado: {len(placeholder_map)} mapeamentos")
            
            # APLICAR SUBSTITUIÇÕES
            processed_text = text
            substitutions_made = []
            
            for placeholder, value in placeholder_map.items():
                if placeholder in processed_text:
                    processed_text = processed_text.replace(placeholder, value)
                    substitutions_made.append(f"'{placeholder}' → '{value}'")
                    logger.info(f"✅ FIXED: Substituído '{placeholder}' por '{value}'")
            
            # LIMPEZA FINAL de placeholders não substituídos
            remaining_placeholders = re.findall(r'\{[^}]+\}', processed_text)
            if remaining_placeholders:
                logger.warning(f"⚠️ FIXED: Removendo placeholders não utilizados: {remaining_placeholders}")
                for unused_placeholder in remaining_placeholders:
                    # Se for relacionado a nome e temos identificação, usar ela
                    if any(word in unused_placeholder.lower() for word in ["name", "user", "nome", "usuario"]) and identification:
                        processed_text = processed_text.replace(unused_placeholder, identification)
                        logger.info(f"🔧 FIXED: Fallback '{unused_placeholder}' → '{identification}'")
                    else:
                        processed_text = processed_text.replace(unused_placeholder, "")
                        logger.info(f"🧹 FIXED: Removido '{unused_placeholder}'")
            
            # FORMATAÇÃO FINAL
            processed_text = processed_text.replace("\\n", "\n")
            processed_text = re.sub(r'\n\s*\n', '\n\n', processed_text)
            processed_text = re.sub(r'[ \t]+', ' ', processed_text)
            processed_text = processed_text.strip()
            
            logger.info(f"🔧 FIXED RESULT: '{processed_text[:100]}...' | substituições: {len(substitutions_made)}")
            logger.info("="*60)
            
            return processed_text
            
        except Exception as e:
            logger.error(f"❌ ERRO CRÍTICO no processamento: {str(e)}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            
            # FALLBACK DE EMERGÊNCIA
            try:
                emergency_name = (
                    session_data.get("lead_data", {}).get("identification") or
                    session_data.get("last_user_message", "") or
                    "usuário"
                ).strip()
                
                emergency_text = text
                emergency_patterns = [
                    "{user name}", "{user_name}", "{name}", "{Name}",
                    "{ username }", "{ user_name }", "{ name }"
                ]
                
                for pattern in emergency_patterns:
                    emergency_text = emergency_text.replace(pattern, emergency_name)
                
                # Remover outros placeholders
                emergency_text = re.sub(r'\{[^}]+\}', '', emergency_text)
                
                logger.info(f"🚨 FALLBACK DE EMERGÊNCIA: '{emergency_name}'")
                return emergency_text
                
            except Exception as final_error:
                logger.error(f"❌ FALHA TOTAL: {final_error}")
                return text or "Como posso ajudá-lo?"

    async def _get_flow_with_cache(self) -> Dict[str, Any]:
        """
        Obter fluxo do Firebase com cache e fallback.
        """
        try:
            # Verificar cache
            if (self.flow_cache and self.flow_cache_timestamp and 
                datetime.now() - self.flow_cache_timestamp < self.flow_cache_ttl):
                logger.info("📚 Usando fluxo do cache")
                return self.flow_cache
            
            # Buscar do Firebase
            try:
                logger.info("🔥 Buscando fluxo do Firebase...")
                firebase_flow = await get_conversation_flow()
                
                if firebase_flow and firebase_flow.get("steps") and len(firebase_flow["steps"]) >= 3:
                    logger.info(f"✅ Fluxo Firebase carregado com {len(firebase_flow['steps'])} steps")
                    self.flow_cache = firebase_flow
                    self.flow_cache_timestamp = datetime.now()
                    return firebase_flow
                else:
                    logger.warning("⚠️ Fluxo Firebase inválido - usando fallback")
                    raise Exception("Invalid Firebase flow")
                    
            except Exception as firebase_error:
                logger.warning(f"⚠️ Erro Firebase: {str(firebase_error)} - usando fluxo hardcoded")
                
            # Fallback para fluxo hardcoded
            hardcoded_flow = self._get_hardcoded_flow()
            logger.info("🔧 Usando fluxo hardcoded como fallback")
            return hardcoded_flow
            
        except Exception as e:
            logger.error(f"❌ Erro crítico ao obter fluxo: {str(e)}")
            return self._get_hardcoded_flow()

    async def _get_or_create_session(
        self,
        session_id: str,
        platform: str,
        phone_number: str = None
    ) -> Dict[str, Any]:
        """
        Obter sessão existente ou criar nova com melhor sincronização.
        """
        try:
            logger.info(f"🔍 Buscando/criando sessão: {session_id}")
            
            session_data = await get_user_session(session_id)
            
            if not session_data:
                logger.info(f"🆕 Criando nova sessão para {session_id}")
                session_data = {
                    "session_id": session_id,
                    "platform": platform,
                    "current_step": 1,
                    "flow_completed": False,
                    "collecting_phone": False,
                    "phone_collected": False,
                    "ai_mode": False,
                    "lead_data": {},
                    "message_count": 0,
                    "created_at": datetime.now(),
                    "last_updated": datetime.now(),
                    "flow_source": "firebase"
                }
                
                if phone_number:
                    session_data["phone_number"] = phone_number
                
                await self._persist_session_safely(session_id, session_data)
                logger.info(f"✅ Nova sessão criada: {session_id}")
            else:
                logger.info(f"📋 Sessão existente: {session_id} | step={session_data.get('current_step')}")
            
            # Atualizar contador de mensagens
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            session_data["last_updated"] = datetime.now()
            
            return session_data
            
        except Exception as e:
            logger.error(f"❌ Erro ao buscar/criar sessão: {str(e)}")
            # Sessão padrão se Firebase falhar
            return {
                "session_id": session_id,
                "platform": platform,
                "current_step": 1,
                "flow_completed": False,
                "collecting_phone": False,
                "phone_collected": False,
                "ai_mode": False,
                "lead_data": {},
                "message_count": 1,
                "created_at": datetime.now(),
                "last_updated": datetime.now(),
                "flow_source": "fallback"
            }

    async def _persist_session_safely(self, session_id: str, session_data: Dict[str, Any]):
        """
        Persistir sessão com retry e melhor tratamento de erros.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await save_user_session(session_id, session_data)
                logger.info(f"✅ Sessão persistida (tentativa {attempt + 1})")
                return
            except Exception as e:
                logger.warning(f"⚠️ Erro ao salvar sessão (tentativa {attempt + 1}/{max_retries}): {str(e)}")
                if attempt == max_retries - 1:
                    logger.error(f"❌ Falha definitiva ao persistir sessão: {str(e)}")
                    raise

    def _is_initialization_message(self, message: str, current_step: int) -> bool:
        """
        Detectar mensagens de inicialização.
        """
        if current_step != 1:
            return False
        
        message_lower = message.lower().strip()
        init_messages = [
            "olá", "oi", "hello", "hi", "hey", "ola", "oii", 
            "start", "começar", "iniciar", "start_conversation",
            "bom dia", "boa tarde", "boa noite", "opa", "e ai", "eai"
        ]
        
        return (len(message.strip()) <= 10 and message_lower in init_messages) or message_lower in init_messages

    async def _handle_structured_flow(
        self,
        message: str,
        session_id: str,
        session_data: Dict[str, Any],
        platform: str
    ) -> Dict[str, Any]:
        """
        🔧 REESCRITO - Fluxo estruturado com melhor sincronização de dados.
        """
        try:
            flow = await self._get_flow_with_cache()
            current_step = session_data.get("current_step", 1)
            
            logger.info(f"📋 Fluxo estruturado | step={current_step} | msg='{message[:30]}...'")
            
            # Encontrar step atual
            current_step_data = None
            for step in flow.get("steps", []):
                if step.get("id") == current_step:
                    current_step_data = step
                    break
            
            if not current_step_data:
                logger.error(f"❌ Step {current_step} não encontrado - completando fluxo")
                return await self._complete_flow_and_collect_phone(session_id, session_data, flow)
            
            # Verificar se é mensagem de inicialização
            is_init_message = self._is_initialization_message(message, current_step)
            
            if is_init_message:
                logger.info("🚀 Mensagem de inicialização - retornando pergunta inicial")
                question_with_placeholders = self._process_placeholders_in_text(
                    current_step_data["question"], 
                    session_data
                )
                
                return {
                    "response": question_with_placeholders,
                    "response_type": "structured_question",
                    "session_id": session_id,
                    "current_step": current_step,
                    "flow_completed": False,
                    "ai_mode": False
                }
            
            # Obter nome do campo
            field_name = current_step_data.get("field", f"step_{current_step}")
            
            # Verificar se já respondeu
            if field_name in session_data.get("lead_data", {}):
                logger.info(f"⚠️ Step {current_step} já respondido, avançando")
                return await self._advance_to_next_step(session_id, session_data, flow, current_step)
            
            # Validar resposta
            if not self._validate_answer(message, current_step, current_step_data):
                logger.warning(f"❌ Resposta inválida para step {current_step}")
                error_message = current_step_data.get("error_message", "Por favor, forneça uma resposta mais completa.")
                validation_question = self._process_placeholders_in_text(
                    current_step_data["question"], 
                    session_data
                )
                
                return {
                    "response": f"{error_message} {validation_question}",
                    "response_type": "validation_error",
                    "session_id": session_id,
                    "current_step": current_step,
                    "flow_completed": False,
                    "ai_mode": False
                }
            
            # 🔧 SALVAR RESPOSTA COM MAPEAMENTO CORRETO
            logger.info(f"💾 Salvando resposta para step {current_step} no campo '{field_name}': '{message}'")
            
            if "lead_data" not in session_data:
                session_data["lead_data"] = {}
            
            # SALVAR NO CAMPO PRIMÁRIO
            session_data["lead_data"][field_name] = message.strip()
            session_data["last_user_message"] = message.strip()
            
            # 🔧 CRÍTICO: Criar aliases para compatibilidade baseado na documentação
            if field_name == "identification":
                # Nome tem múltiplos aliases
                name_value = message.strip().title()
                session_data["lead_data"]["identification"] = name_value
                session_data["lead_data"]["name"] = name_value
                session_data["lead_data"]["user_name"] = name_value
                logger.info(f"✅ FIXED: Nome salvo com aliases: identification='{name_value}'")
                
            elif field_name == "area_qualification":
                # Área do direito com aliases
                area_value = message.strip()
                session_data["lead_data"]["area_qualification"] = area_value
                session_data["lead_data"]["area"] = area_value
                session_data["lead_data"]["area_of_law"] = area_value
                logger.info(f"✅ FIXED: Área salva com aliases: area='{area_value}'")
                
            elif field_name == "contact_info":
                # Contato com aliases
                contact_value = message.strip()
                session_data["lead_data"]["contact_info"] = contact_value
                session_data["lead_data"]["contact"] = contact_value
                logger.info(f"✅ FIXED: Contato salvo com aliases")
                
            elif field_name == "problem_description":
                # Situação com aliases
                situation_value = message.strip()
                session_data["lead_data"]["problem_description"] = situation_value
                session_data["lead_data"]["situation"] = situation_value
                session_data["lead_data"]["case_details"] = situation_value
                logger.info(f"✅ FIXED: Situação salva com aliases")
            
            # 🔧 PERSISTIR IMEDIATAMENTE ANTES DE AVANÇAR
            session_data["last_updated"] = datetime.now()
            await self._persist_session_safely(session_id, session_data)
            
            # 🔧 AGUARDAR SINCRONIZAÇÃO
            import asyncio
            await asyncio.sleep(0.2)
            
            # 🔧 RECARREGAR DADOS DO FIREBASE para garantir sincronização
            try:
                fresh_session_data = await get_user_session(session_id)
                if fresh_session_data and fresh_session_data.get("lead_data"):
                    session_data = fresh_session_data
                    logger.info(f"🔄 Dados recarregados: {list(session_data['lead_data'].keys())}")
            except Exception as reload_error:
                logger.error(f"❌ Erro ao recarregar: {reload_error}")
            
            # Avançar para próximo step
            return await self._advance_to_next_step(session_id, session_data, flow, current_step)
                
        except Exception as e:
            logger.error(f"❌ Erro no fluxo estruturado: {str(e)}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            
            # Fallback robusto
            return {
                "response": "Qual é o seu nome completo?",
                "response_type": "error_fallback",
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False
            }

    async def _advance_to_next_step(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        flow: Dict[str, Any],
        current_step: int
    ) -> Dict[str, Any]:
        """
        🔧 REESCRITO - Avanço com melhor sincronização e processamento de placeholders.
        """
        try:
            next_step = current_step + 1
            logger.info(f"➡️ Avançando de step {current_step} para {next_step}")
            
            # Encontrar próximo step
            next_step_data = None
            for step in flow.get("steps", []):
                if step.get("id") == next_step:
                    next_step_data = step
                    break
            
            if next_step_data:
                # 🔧 ATUALIZAR E PERSISTIR ANTES DE PROCESSAR PLACEHOLDERS
                session_data["current_step"] = next_step
                session_data["last_updated"] = datetime.now()
                await self._persist_session_safely(session_id, session_data)
                
                # 🔧 AGUARDAR SINCRONIZAÇÃO
                import asyncio
                await asyncio.sleep(0.3)
                
                # 🔧 RECARREGAR DADOS ATUALIZADOS
                try:
                    fresh_session_data = await get_user_session(session_id)
                    if fresh_session_data:
                        session_data = fresh_session_data
                        logger.info(f"🔄 Dados frescos carregados para processamento de placeholders")
                except Exception:
                    logger.warning("⚠️ Não foi possível recarregar - usando dados em memória")
                
                # 🔧 PROCESSAR PLACEHOLDERS COM DADOS ATUALIZADOS
                next_question_with_placeholders = self._process_placeholders_in_text(
                    next_step_data["question"], 
                    session_data
                )
                
                return {
                    "response": next_question_with_placeholders,
                    "response_type": "structured_question",
                    "session_id": session_id,
                    "current_step": next_step,
                    "flow_completed": False,
                    "ai_mode": False
                }
            else:
                # Fluxo completo
                logger.info("🏁 Fluxo estruturado completo")
                return await self._complete_flow_and_collect_phone(session_id, session_data, flow)
        
        except Exception as e:
            logger.error(f"❌ Erro ao avançar step: {str(e)}")
            return {
                "response": "Qual o melhor telefone/WhatsApp para contato?",
                "response_type": "advance_error_fallback",
                "session_id": session_id,
                "current_step": current_step + 1,
                "flow_completed": False,
                "ai_mode": False
            }

    def _get_hardcoded_flow(self) -> Dict[str, Any]:
        """
        Fluxo hardcoded como fallback.
        """
        return {
            "steps": [
                {
                    "id": 1,
                    "question": "👋 Olá! Seja bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?",
                    "field": "identification",
                    "context": "",
                    "error_message": "Por favor, informe seu nome completo para que possamos te atender adequadamente.",
                    "validation": {
                        "required": True,
                        "min_length": 2
                    }
                },
                {
                    "id": 2,
                    "question": "Prazer em conhecê-lo, {username}!\n\n📱 Qual o melhor telefone/WhatsApp para contato?\n\n📧 Você poderia informar seu e-mail também?",
                    "field": "contact_info",
                    "context": "contact_collection",
                    "error_message": "Por favor, informe seu telefone (com DDD) e e-mail para contato.",
                    "validation": {
                        "required": True,
                        "min_length": 10,
                        "type": "contact_combined"
                    }
                },
                {
                    "id": 3,
                    "question": "Perfeito, {username}! Com qual área do direito você precisa de ajuda? Penal ou Saúde (ações e liminares médicas)?",
                    "field": "area_qualification",
                    "context": "area_qualification",
                    "error_message": "Por favor, especifique a área do direito que precisa de ajuda.",
                    "validation": {
                        "required": True,
                        "min_length": 3
                    }
                },
                {
                    "id": 4,
                    "question": "Perfeito, {username}! Com qual área do direito você precisa de ajuda? Penal ou Saúde (ações e liminares médicas)? Vim do firestone",
                    "field": "problem_description",
                    "context": "problem_gathering",
                    "error_message": "Por favor, descreva sua situação com mais detalhes.",
                    "validation": {
                        "required": True,
                        "min_length": 10
                    }
                }
            ]
        }

    async def _complete_flow_and_collect_phone(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        flow: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Completar fluxo e iniciar coleta de telefone.
        """
        try:
            lead_data_raw = session_data.get("lead_data", {})
            
            # Marcar fluxo como completo
            session_data["flow_completed"] = True
            session_data["collecting_phone"] = True
            
            # Preparar dados do lead
            lead_data = {
                "name": lead_data_raw.get("identification", "Não informado"),
                "contact_info": lead_data_raw.get("contact_info", "Não informado"),
                "area_of_law": lead_data_raw.get("area_qualification", "Não informado"),
                "situation": lead_data_raw.get("problem_description", "Não informado"),
                "session_id": session_id,
                "platform": session_data.get("platform", "web"),
                "completed_at": datetime.now(),
                "status": "intake_completed"
            }
            
            # Salvar dados do lead
            try:
                lead_id = await save_lead_data(lead_data)
                session_data["lead_id"] = lead_id
                logger.info(f"✅ Lead data saved with ID: {lead_id}")
            except Exception as e:
                logger.error(f"⚠️ Erro ao salvar lead data: {str(e)}")
                session_data["lead_id"] = f"temp_{session_id}"
            
            await self._persist_session_safely(session_id, session_data)
            
            # Personalizar mensagem com nome do usuário
            user_name = lead_data.get("name", "")
            if user_name and user_name != "Não informado":
                phone_message = f"Perfeito, {user_name}! Suas informações foram registradas. Para finalizar, me informe seu número de WhatsApp com DDD (ex: 11999999999):"
            else:
                phone_message = "Perfeito! Suas informações foram registradas. Para finalizar, me informe seu número de WhatsApp com DDD (ex: 11999999999):"
            
            return {
                "response": phone_message,
                "response_type": "phone_collection",
                "session_id": session_id,
                "flow_completed": True,
                "collecting_phone": True,
                "lead_id": session_data.get("lead_id"),
                "ai_mode": False
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao completar fluxo: {str(e)}")
            return {
                "response": "Para finalizar, me informe seu número de WhatsApp:",
                "response_type": "phone_collection_fallback",
                "session_id": session_id,
                "flow_completed": True,
                "collecting_phone": True,
                "ai_mode": False
            }

    async def _handle_phone_collection(
        self,
        message: str,
        session_id: str,
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Lidar com coleta de número de telefone.
        """
        try:
            phone_clean = re.sub(r'[^\d]', '', message)
            
            # Validar número
            if len(phone_clean) < 10 or len(phone_clean) > 11:
                return {
                    "response": "Número inválido. Por favor, digite seu WhatsApp com DDD (ex: 11999999999):",
                    "response_type": "phone_validation_error",
                    "session_id": session_id,
                    "collecting_phone": True,
                    "flow_completed": True,
                    "ai_mode": False
                }
            
            # Formatar número
            if len(phone_clean) == 10:
                phone_formatted = f"55{phone_clean[:2]}9{phone_clean[2:]}"
            else:
                phone_formatted = f"55{phone_clean}"
            
            # Atualizar sessão
            session_data["phone_collected"] = True
            session_data["collecting_phone"] = False
            session_data["ai_mode"] = True
            session_data["phone_number"] = phone_clean
            session_data["phone_formatted"] = phone_formatted
            
            await self._persist_session_safely(session_id, session_data)
            
            # Enviar confirmações
            try:
                await self._send_whatsapp_confirmation_and_notify(session_data, phone_formatted)
            except Exception as e:
                logger.error(f"⚠️ Erro ao enviar confirmação WhatsApp: {str(e)}")
            
            # Personalizar confirmação com nome do usuário
            user_name = session_data.get("lead_data", {}).get("identification", "")
            if user_name and user_name != "Não informado":
                confirmation_message = f"✅ Número confirmado: {phone_clean}\n\n{user_name}, suas informações foram registradas com sucesso! Nossa equipe entrará em contato em breve."
            else:
                confirmation_message = f"✅ Número confirmado: {phone_clean}\n\nSuas informações foram registradas com sucesso! Nossa equipe entrará em contato em breve."
            
            return {
                "response": confirmation_message,
                "response_type": "phone_collected",
                "session_id": session_id,
                "flow_completed": True,
                "phone_collected": True,
                "collecting_phone": False,
                "ai_mode": True,
                "phone_number": phone_clean
            }
            
        except Exception as e:
            logger.error(f"❌ Erro na coleta de telefone: {str(e)}")
            return {
                "response": "Erro ao processar seu número. Vamos continuar! Como posso ajudá-lo?",
                "response_type": "phone_error_fallback",
                "session_id": session_id,
                "flow_completed": True,
                "ai_mode": True,
                "phone_collected": False
            }

    async def _send_whatsapp_confirmation_and_notify(
        self,
        session_data: Dict[str, Any],
        phone_formatted: str
    ):
        """
        Enviar confirmação WhatsApp e notificar advogados.
        """
        try:
            lead_data = session_data.get("lead_data", {})
            user_name = lead_data.get("identification", "Cliente")
            area_of_law = lead_data.get("area_qualification", "Não informado")
            situation = lead_data.get("problem_description", "Não informado")
            
            user_message = f"""Olá {user_name}! 👋

Recebemos suas informações e nossa equipe jurídica especializada vai entrar em contato em breve.

📋 Resumo do seu caso:
• Área: {area_of_law}
• Situação: {situation[:100]}{'...' if len(situation) > 100 else ''}

Obrigado por escolher nossos serviços! 🤝"""

            try:
                await baileys_service.send_whatsapp_message(
                    f"{phone_formatted}@s.whatsapp.net",
                    user_message
                )
                logger.info(f"✅ Confirmação enviada para: {phone_formatted}")
            except Exception as e:
                logger.error(f"❌ Erro ao enviar confirmação: {str(e)}")
            
            # Notificar advogados
            try:
                await lawyer_notification_service.notify_lawyers_of_new_lead(
                    lead_name=user_name,
                    lead_phone=session_data.get("phone_number", ""),
                    category=area_of_law,
                    additional_info={
                        "situation": situation,
                        "platform": session_data.get("platform", "web"),
                        "session_id": session_data.get("session_id")
                    }
                )
                logger.info(f"✅ Advogados notificados para: {user_name}")
            except Exception as e:
                logger.error(f"❌ Erro ao notificar advogados: {str(e)}")
                
        except Exception as e:
            logger.error(f"❌ Erro na confirmação WhatsApp: {str(e)}")

    async def _handle_ai_conversation(
        self,
        message: str,
        session_id: str,
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Lidar com conversa AI após completar o fluxo.
        """
        try:
            # Tentar Gemini AI primeiro
            if not self._is_gemini_unavailable():
                try:
                    context = {
                        "name": session_data.get("lead_data", {}).get("identification"),
                        "contact_info": session_data.get("lead_data", {}).get("contact_info"),
                        "area_of_law": session_data.get("lead_data", {}).get("area_qualification"),
                        "situation": session_data.get("lead_data", {}).get("problem_description"),
                        "platform": session_data.get("platform", "web")
                    }
                    
                    ai_response = await ai_orchestrator.generate_response(
                        message, session_id, context
                    )
                    
                    await self._persist_session_safely(session_id, session_data)
                    
                    return {
                        "response": ai_response,
                        "response_type": "ai_intelligent",
                        "session_id": session_id,
                        "flow_completed": True,
                        "phone_collected": True,
                        "ai_mode": True,
                        "gemini_available": True
                    }
                    
                except Exception as e:
                    if self._is_quota_error(str(e)):
                        self._mark_gemini_unavailable()
                        logger.warning("🚫 Gemini quota exceeded, using fallback")
                    else:
                        logger.error(f"❌ Gemini error: {str(e)}")
            
            # Fallback personalizado
            user_name = session_data.get("lead_data", {}).get("identification", "")
            area_of_law = session_data.get("lead_data", {}).get("area_qualification", "")
            
            if user_name and user_name != "Não informado":
                if area_of_law and area_of_law != "Não informado":
                    fallback_response = f"Obrigado pela sua mensagem, {user_name}! Entendi que você precisa de ajuda com {area_of_law}. Nossa equipe especializada já tem suas informações e entrará em contato em breve para dar continuidade ao seu caso."
                else:
                    fallback_response = f"Obrigado pela sua mensagem, {user_name}! Nossa equipe já tem suas informações e entrará em contato em breve para dar continuidade ao seu caso."
            else:
                fallback_response = "Obrigado pela sua mensagem! Nossa equipe já tem suas informações e entrará em contato em breve para dar continuidade ao seu caso."
            
            return {
                "response": fallback_response,
                "response_type": "ai_fallback",
                "session_id": session_id,
                "flow_completed": True,
                "phone_collected": True,
                "ai_mode": True,
                "gemini_available": False
            }
            
        except Exception as e:
            logger.error(f"❌ Erro na conversa AI: {str(e)}")
            return {
                "response": "Como posso ajudá-lo?",
                "response_type": "ai_error_fallback",
                "session_id": session_id,
                "ai_mode": True
            }

    def _validate_answer(self, answer: str, step: int, step_data: Dict[str, Any] = None) -> bool:
        """
        Validar respostas do usuário baseado no step.
        """
        logger.info(f"🔍 Validando resposta para step {step}: '{answer}' (length: {len(answer.strip())})")
        
        if not answer or len(answer.strip()) < 1:
            logger.warning(f"❌ Resposta vazia para step {step}")
            return False
        
        # Se for mensagem de inicialização, não é resposta válida
        if self._is_initialization_message(answer, step):
            logger.warning(f"❌ Mensagem de inicialização não é resposta válida para step {step}")
            return False
        
        # Usar validação do Firebase se disponível
        if step_data and "validation" in step_data:
            validation = step_data["validation"]
            
            if validation.get("required", True) and len(answer.strip()) == 0:
                logger.warning(f"❌ Campo obrigatório vazio para step {step}")
                return False
            
            min_length = validation.get("min_length", 2)
            if len(answer.strip()) < min_length:
                logger.warning(f"❌ Resposta muito curta para step {step} (mín: {min_length})")
                return False
            
            validation_type = validation.get("type")
            if validation_type == "contact_combined":
                has_phone = bool(re.search(r'\d{8,}', answer))
                has_email = bool(re.search(r'\S+@\S+\.\S+', answer))
                if not (has_phone or has_email):
                    logger.warning(f"❌ Contato inválido para step {step}")
                    return False
        
        # Validação padrão
        try:
            if step == 1:  # Nome
                answer_clean = answer.strip()
                if (answer_clean.isdigit() or 
                    len(answer_clean) < 2 or 
                    answer_clean.lower() in ["oi", "olá", "hello", "hi"]):
                    return False
                return True
            elif step == 2:  # Contato
                has_phone = bool(re.search(r'\d{8,}', answer))
                has_email = bool(re.search(r'\S+@\S+\.\S+', answer))
                return has_phone or has_email
            elif step == 3:  # Área
                return len(answer.strip()) >= 3
            elif step == 4:  # Situação
                return len(answer.strip()) >= 10
        except Exception as e:
            logger.error(f"❌ Erro na validação: {str(e)}")
            return True
        
        return True

    def _is_phone_number(self, text: str) -> bool:
        """Verificar se texto parece número de telefone."""
        phone_clean = re.sub(r'[^\d]', '', text)
        return 10 <= len(phone_clean) <= 13

    def _is_quota_error(self, error_message: str) -> bool:
        """Verificar se erro é relacionado a quota/limite de API."""
        error_lower = error_message.lower()
        quota_indicators = [
            "429", "quota", "rate limit", "resourceexhausted", 
            "billing", "exceeded", "too many requests"
        ]
        return any(indicator in error_lower for indicator in quota_indicators)

    def _mark_gemini_unavailable(self):
        """Marcar Gemini como temporariamente indisponível."""
        self.gemini_unavailable_until = datetime.now() + self.gemini_check_interval
        logger.warning(f"🚫 Gemini marcado indisponível até {self.gemini_unavailable_until}")

    def _is_gemini_unavailable(self) -> bool:
        """Verificar se Gemini está marcado como indisponível."""
        if self.gemini_unavailable_until is None:
            return False
        
        if datetime.now() > self.gemini_unavailable_until:
            self.gemini_unavailable_until = None
            logger.info("✅ Disponibilidade do Gemini restaurada")
            return False
        
        return True

    # Métodos adicionais para compatibilidade
    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Lidar com autorização WhatsApp."""
        try:
            session_id = auth_data.get("session_id")
            phone_number = auth_data.get("phone_number")
            
            session_data = {
                "session_id": session_id,
                "platform": "whatsapp",
                "current_step": 1,
                "flow_completed": False,
                "collecting_phone": False,
                "phone_collected": False,
                "ai_mode": False,
                "lead_data": {},
                "message_count": 0,
                "phone_number": phone_number,
                "created_at": datetime.now(),
                "last_updated": datetime.now(),
                "flow_source": "firebase"
            }
            
            await self._persist_session_safely(session_id, session_data)
            
            # Enviar mensagem inicial
            flow = await self._get_flow_with_cache()
            initial_step = next((s for s in flow["steps"] if s["id"] == 1), None)
            if initial_step:
                welcome_message = f"👋 Olá! Bem-vindo ao nosso escritório de advocacia.\n\n{initial_step['question']}"
            else:
                welcome_message = "👋 Olá! Qual é o seu nome completo?"
            
            try:
                await baileys_service.send_whatsapp_message(
                    f"{phone_number}@s.whatsapp.net",
                    welcome_message
                )
            except Exception as e:
                logger.error(f"❌ Erro ao enviar mensagem inicial: {str(e)}")
            
            return {"success": True, "session_id": session_id}
            
        except Exception as e:
            logger.error(f"❌ Erro na autorização WhatsApp: {str(e)}")
            return {"success": False, "error": str(e)}

    async def handle_phone_number_submission(self, phone_number: str, session_id: str, user_name: str = "Cliente") -> Dict[str, Any]:
        """Lidar com submissão de número de telefone."""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"success": False, "error": "Session not found"}
            
            phone_clean = re.sub(r'[^\d]', '', phone_number)
            
            if len(phone_clean) < 10 or len(phone_clean) > 11:
                return {"success": False, "error": "Invalid phone number format"}
            
            if len(phone_clean) == 10:
                phone_formatted = f"55{phone_clean[:2]}9{phone_clean[2:]}"
            else:
                phone_formatted = f"55{phone_clean}"
            
            session_data["phone_collected"] = True
            session_data["phone_number"] = phone_clean
            session_data["phone_formatted"] = phone_formatted
            session_data["ai_mode"] = True
            session_data["collecting_phone"] = False
            
            await self._persist_session_safely(session_id, session_data)
            
            try:
                await self._send_whatsapp_confirmation_and_notify(session_data, phone_formatted)
            except Exception as e:
                logger.error(f"⚠️ Erro ao enviar confirmações: {str(e)}")
            
            return {"success": True, "phone_number": phone_clean}
            
        except Exception as e:
            logger.error(f"❌ Erro na submissão de telefone: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Obter contexto da sessão."""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"exists": False}
            
            return {
                "exists": True,
                "session_data": session_data,
                "current_step": session_data.get("current_step"),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_collected": session_data.get("phone_collected", False),
                "ai_mode": session_data.get("ai_mode", False),
                "collecting_phone": session_data.get("collecting_phone", False),
                "platform": session_data.get("platform", "unknown"),
                "lead_data": session_data.get("lead_data", {}),
                "message_count": session_data.get("message_count", 0),
                "flow_source": session_data.get("flow_source", "unknown")
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter contexto da sessão: {str(e)}")
            return {"exists": False, "error": str(e)}

    async def reset_session(self, session_id: str) -> Dict[str, Any]:
        """Resetar sessão para testes."""
        try:
            fresh_session = {
                "session_id": session_id,
                "platform": "web",
                "current_step": 1,
                "flow_completed": False,
                "collecting_phone": False,
                "phone_collected": False,
                "ai_mode": False,
                "lead_data": {},
                "message_count": 0,
                "created_at": datetime.now(),
                "last_updated": datetime.now(),
                "reset_at": datetime.now(),
                "flow_source": "firebase"
            }
            
            await self._persist_session_safely(session_id, fresh_session)
            logger.info(f"✅ Sessão resetada: {session_id}")
            
            return {"success": True, "message": "Session reset successfully"}
        except Exception as e:
            logger.error(f"❌ Erro ao resetar sessão: {str(e)}")
            return {"success": False, "error": str(e)}


# Instância global do orchestrador
intelligent_orchestrator = IntelligentHybridOrchestrator()