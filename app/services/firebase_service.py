import os
import json
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import HTTPException, status
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global Firebase app instance
_firebase_app = None
_firestore_client = None
_memory_sessions = {}

def render_question(question_template: str, context: Dict[str, Any]) -> str:
    """
    🔧 ENHANCED: Renders question with comprehensive placeholder replacement
    """
    try:
        if not question_template or "{" not in question_template:
            return question_template
        
        logger.info(f"🔧 RENDER_QUESTION - Template: '{question_template[:100]}...'")
        logger.info(f"🔧 RENDER_QUESTION - Context keys: {list(context.keys())}")
        
        # Create comprehensive placeholder mapping
        placeholder_map = {}
        
        # 1. Map all direct context fields
        for key, value in context.items():
            if value and str(value).strip():
                clean_value = str(value).strip()
                placeholder_map[f"{{{key}}}"] = clean_value
                # Also map with underscores and without
                placeholder_map[f"{{{key.replace('_', '')}}}"] = clean_value
                placeholder_map[f"{{{key.replace('_', ' ')}}}"] = clean_value
        
        # 2. CRITICAL: Handle all name variations
        identification = context.get("identification") or context.get("name") or context.get("user_name", "")
        if identification:
            clean_name = str(identification).strip()
            name_aliases = [
                "{user_name}", "{user name}", "{username}", "{name}", "{identification}", 
                "{nome}", "{usuario}", "{cliente}", "{userName}", "{user-name}",
                # Handle case variations
                "{User_Name}", "{USER_NAME}", "{Name}", "{USERNAME}"
            ]
            for alias in name_aliases:
                placeholder_map[alias] = clean_name
                placeholder_map[alias.lower()] = clean_name
        
        # 3. Handle contact information
        contact_info = context.get("contact_info") or context.get("contact") or context.get("phone", "")
        if contact_info:
            clean_contact = str(contact_info).strip()
            contact_aliases = [
                "{contact_info}", "{contact}", "{phone}", "{telefone}", 
                "{contato}", "{whatsapp}", "{phone_number}"
            ]
            for alias in contact_aliases:
                placeholder_map[alias] = clean_contact
        
        # 4. Handle area/legal field
        area_qualification = context.get("area_qualification") or context.get("area") or context.get("area_of_law", "")
        if area_qualification:
            clean_area = str(area_qualification).strip()
            area_aliases = [
                "{area}", "{area_of_law}", "{area_qualification}", 
                "{area_direito}", "{especialidade}", "{areaoflaw}"
            ]
            for alias in area_aliases:
                placeholder_map[alias] = clean_area
        
        # 5. Handle situation/problem description
        problem_description = context.get("problem_description") or context.get("situation") or context.get("case_details", "")
        if problem_description:
            clean_situation = str(problem_description).strip()
            situation_aliases = [
                "{situation}", "{case_details}", "{problem_description}", 
                "{situacao}", "{problema}", "{caso}", "{casedetails}"
            ]
            for alias in situation_aliases:
                placeholder_map[alias] = clean_situation
        
        logger.info(f"🔧 PLACEHOLDER_MAP created with {len(placeholder_map)} mappings")
        
        # 6. Apply all substitutions (case-insensitive)
        processed_text = question_template
        
        # First pass: exact matches
        for placeholder, value in placeholder_map.items():
            if placeholder in processed_text:
                processed_text = processed_text.replace(placeholder, value)
                logger.info(f"✅ Replaced '{placeholder}' with '{value[:30]}...'")
        
        # Second pass: case-insensitive matches for remaining placeholders
        import re
        remaining_placeholders = re.findall(r'\{[^}]+\}', processed_text)
        for remaining in remaining_placeholders:
            for placeholder, value in placeholder_map.items():
                if remaining.lower() == placeholder.lower():
                    processed_text = processed_text.replace(remaining, value)
                    logger.info(f"✅ Case-insensitive replaced '{remaining}' with '{value[:30]}...'")
                    break
        
        # 7. Handle any remaining unsubstituted placeholders
        remaining_placeholders = re.findall(r'\{[^}]+\}', processed_text)
        if remaining_placeholders:
            logger.warning(f"⚠️ Unresolved placeholders: {remaining_placeholders}")
            logger.warning(f"⚠️ Available context: {list(context.keys())}")
            
            # Try to fill with fallback values
            for placeholder in remaining_placeholders:
                if any(name_word in placeholder.lower() for name_word in ['name', 'user', 'nome', 'usuario']):
                    # Try to find any name-like value in context
                    fallback_name = (
                        context.get("identification") or 
                        context.get("name") or 
                        context.get("user_name") or
                        "Cliente"
                    )
                    processed_text = processed_text.replace(placeholder, str(fallback_name))
                    logger.info(f"🔄 Fallback replaced '{placeholder}' with '{fallback_name}'")
                else:
                    # Remove unresolved placeholders to avoid showing {placeholder} to user
                    processed_text = processed_text.replace(placeholder, "")
                    logger.warning(f"🗑️ Removed unresolved placeholder: '{placeholder}'")
        
        # 8. Clean up formatting
        processed_text = processed_text.replace("\\n", "\n")
        processed_text = re.sub(r'\n\s*\n', '\n\n', processed_text)
        processed_text = re.sub(r'[ \t]+', ' ', processed_text)
        processed_text = processed_text.strip()
        
        logger.info(f"🔧 FINAL RESULT: '{processed_text[:100]}...'")
        return processed_text
        
    except Exception as e:
        logger.error(f"❌ Error rendering question: {str(e)}")
        import traceback
        logger.error(f"🔍 Traceback: {traceback.format_exc()}")
        # Return original template if rendering fails
        return question_template or "Como posso ajudá-lo?"

def _load_credentials_from_secret():
    """Carrega credenciais do Firebase a partir de múltiplas fontes."""
    try:
        firebase_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        if firebase_json:
            logger.info("Carregando credenciais via FIREBASE_SERVICE_ACCOUNT_JSON")
            return json.loads(firebase_json)
        
        firebase_config = {}
        config_fields = {
            "FIREBASE_TYPE": "type",
            "FIREBASE_PROJECT_ID": "project_id", 
            "FIREBASE_PRIVATE_KEY_ID": "private_key_id",
            "FIREBASE_PRIVATE_KEY": "private_key",
            "FIREBASE_CLIENT_EMAIL": "client_email",
            "FIREBASE_CLIENT_ID": "client_id",
            "FIREBASE_AUTH_URI": "auth_uri",
            "FIREBASE_TOKEN_URI": "token_uri",
            "FIREBASE_AUTH_PROVIDER_X509_CERT_URL": "auth_provider_x509_cert_url",
            "FIREBASE_CLIENT_X509_CERT_URL": "client_x509_cert_url"
        }
        
        for env_var, firebase_key in config_fields.items():
            value = os.getenv(env_var)
            if value:
                if firebase_key == "private_key":
                    firebase_config[firebase_key] = value.replace("\\n", "\n")
                else:
                    firebase_config[firebase_key] = value
        
        if firebase_config.get("project_id") and firebase_config.get("client_email"):
            logger.info("Carregando credenciais via variáveis separadas")
            return firebase_config
        
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        secret_name = os.getenv("FIREBASE_SECRET_NAME", "firebase-key-2")
        
        if project_id:
            try:
                from google.cloud import secretmanager
                client = secretmanager.SecretManagerServiceClient()
                secret_version = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
                response = client.access_secret_version(request={"name": secret_version})
                secret_data = response.payload.data.decode("UTF-8")
                logger.info(f"Carregando credenciais via Secret Manager - {secret_name}")
                return json.loads(secret_data)
            except ImportError:
                logger.warning("google-cloud-secretmanager não disponível")
            except Exception as e:
                logger.warning(f"Erro ao acessar Secret Manager: {str(e)}")
        
        return None
        
    except Exception as e:
        logger.error(f"Erro ao carregar credenciais: {str(e)}")
        return None

def initialize_firebase():
    """Inicializa o Firebase Admin SDK."""
    global _firebase_app, _firestore_client

    if _firebase_app is not None:
        logger.info("Firebase já inicializado")
        return

    try:
        cred = None
        credentials_data = _load_credentials_from_secret()
        if credentials_data:
            cred = credentials.Certificate(credentials_data)
        else:
            cred_path = os.getenv("FIREBASE_CREDENTIALS", "/firebase-key.json")
            if not os.path.isabs(cred_path):
                cred_path = os.path.join(os.getcwd(), cred_path)
            
            if os.path.exists(cred_path):
                logger.info(f"Usando arquivo local: {cred_path}")
                cred = credentials.Certificate(cred_path)
            else:
                try:
                    cred = credentials.ApplicationDefault()
                    logger.info("Usando Google Application Default Credentials")
                except Exception:
                    pass
        
        if not cred:
            raise ValueError("Nenhuma credencial Firebase encontrada")

        _firebase_app = firebase_admin.initialize_app(cred)
        _firestore_client = firestore.client()
        
        test_doc = _firestore_client.collection("_test").document("connection")
        test_doc.set({"test": True, "timestamp": datetime.now()})
        test_doc.delete()
        
        logger.info("Firebase inicializado com sucesso")

    except Exception as e:
        logger.error(f"Falha ao inicializar Firebase: {str(e)}")
        _firebase_app = None
        _firestore_client = None

def get_firestore_client():
    if _firestore_client is None:
        initialize_firebase()

    if _firestore_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase não disponível - verifique configuração"
        )
    return _firestore_client

async def get_conversation_flow() -> Dict[str, Any]:
    """Busca o fluxo de conversa do Firestore."""
    try:
        logger.info("Carregando fluxo de conversa do Firestore")
        
        db = get_firestore_client()
        flow_ref = db.collection("conversation_flows").document("law_firm_intake")
        flow_doc = flow_ref.get()

        if not flow_doc.exists:
            logger.warning("Documento de fluxo não existe, usando fallback")
            return _get_fallback_flow()

        flow_data = flow_doc.to_dict()
        if not flow_data:
            logger.warning("Flow data vazio, usando fallback")
            return _get_fallback_flow()

        steps = flow_data.get("steps", [])
        if not steps:
            logger.warning("Nenhum step encontrado, usando fallback")
            return _get_fallback_flow()

        processed_steps = []
        for idx, step in enumerate(steps, start=1):
            if isinstance(step, dict):
                processed_step = step.copy()
                if "id" not in processed_step or processed_step["id"] is None:
                    processed_step["id"] = idx
                if "question" not in processed_step:
                    processed_step["question"] = ""
                processed_steps.append(processed_step)

        flow_data["steps"] = processed_steps
        if "completion_message" not in flow_data:
            flow_data["completion_message"] = "Obrigado, {user_name}! Nossa equipe entrará em contato em breve."
        
        logger.info(f"Flow carregado com sucesso: {len(processed_steps)} steps")
        return flow_data

    except Exception as e:
        logger.error(f"Erro ao buscar fluxo do Firestore: {str(e)}")
        logger.warning("Usando fallback hardcoded")
        return _get_fallback_flow()

def _get_fallback_flow() -> Dict[str, Any]:
    """
    🔧 ENHANCED: Fallback flow with proper placeholder templates
    """
    return {
        "steps": [
            {
                "id": 1,
                "field": "identification",
                "question": "👋 Olá! Seja bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?",
                "validation": {"min_length": 2, "required": True, "type": "name"},
                "error_message": "Por favor, informe seu nome completo para que possamos te atender adequadamente.",
                "context": "identification_phase"
            },
            {
                "id": 2,
                "field": "contact_info",
                "question": "Prazer em conhecê-lo, {user_name}!\n\n📱 Qual o melhor telefone/WhatsApp para contato?\n\n📧 Você poderia informar seu e-mail também?",
                "validation": {"min_length": 10, "required": True, "type": "contact_combined"},
                "error_message": "Por favor, informe seu telefone (com DDD) e e-mail para contato.",
                "context": "contact_collection"
            },
            {
                "id": 3,
                "field": "area_qualification",
                "question": "Obrigado pelas informações de contato!\n\n⚖️ Em qual área do direito você precisa de ajuda?\n\n(Ex: Trabalhista, Civil, Criminal, Família, Previdenciário, etc.)",
                "validation": {"min_length": 3, "required": True, "type": "area"},
                "error_message": "Por favor, especifique a área do direito que você precisa de ajuda.",
                "context": "area_qualification"
            },
            {
                "id": 4,
                "field": "problem_description",
                "question": "Entendi que você precisa de ajuda com {area}.\n\n📝 Descreva brevemente sua situação ou problema jurídico:",
                "validation": {"min_length": 10, "required": True, "type": "case_description"},
                "error_message": "Por favor, descreva sua situação com mais detalhes para que possamos te ajudar melhor.",
                "context": "case_assessment"
            }
        ],
        "completion_message": "Perfeito, {user_name}! Um de nossos advogados especialistas em {area} já vai assumir seu atendimento.",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }

async def get_user_session(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        db = get_firestore_client()
        doc = db.collection("user_sessions").document(session_id).get()
        if doc.exists:
            session_data = doc.to_dict()
            logger.info(f"🔍 SESSÃO CARREGADA do Firebase: {session_data.get('lead_data', {})}")
            return session_data
        return None
    except Exception as e:
        logger.warning(f"Erro ao buscar sessão {session_id}: {str(e)}")
        return _memory_sessions.get(session_id)

async def save_user_session(session_id: str, session_data: Optional[Dict[str, Any]]) -> bool:
    """🔧 CORRIGIDO: Salva sessão com sincronização garantida."""
    try:
        if session_data is None:
            _memory_sessions.pop(session_id, None)
        else:
            session_data["last_updated"] = datetime.now()
            if "created_at" not in session_data:
                session_data["created_at"] = datetime.now()

            lead_data = session_data.get("lead_data", {})
            session_data["lead_data"] = lead_data

            # 🔧 CRÍTICO: Usar heurística melhorada
            session_data = ensure_lead_step_from_message(session_data)
            
            # 🔧 NOVO: Log detalhado antes de salvar
            logger.info(f"💾 SALVANDO SESSÃO - lead_data: {session_data.get('lead_data', {})}")

            _memory_sessions[session_id] = session_data.copy()
        
        try:
            db = get_firestore_client()
            if session_data is None:
                db.collection("user_sessions").document(session_id).delete()
            else:
                # 🔧 CRÍTICO: Usar set() ao invés de merge para garantir que dados sejam escritos
                db.collection("user_sessions").document(session_id).set(session_data)
                
                # 🔧 NOVO: Verificação pós-salvamento
                await asyncio.sleep(0.1)  # Pequena pausa para sincronização
                
                # Verificar se foi salvo corretamente
                saved_doc = db.collection("user_sessions").document(session_id).get()
                if saved_doc.exists:
                    saved_data = saved_doc.to_dict()
                    saved_lead_data = saved_data.get("lead_data", {})
                    logger.info(f"✅ VERIFICAÇÃO - dados salvos no Firebase: {saved_lead_data}")
                    
                    # Se identification ainda não está lá, forçar salvamento
                    if not saved_lead_data.get("identification") and session_data.get("lead_data", {}).get("identification"):
                        logger.warning("⚠️ FORÇANDO re-salvamento com identification")
                        db.collection("user_sessions").document(session_id).update({
                            "lead_data.identification": session_data["lead_data"]["identification"]
                        })
                else:
                    logger.error("❌ Documento não foi salvo no Firebase!")
                    
        except Exception as firestore_error:
            logger.warning(f"Erro ao salvar no Firestore: {firestore_error}")
        
        return True
    except Exception as e:
        logger.error(f"Erro crítico ao salvar sessão {session_id}: {str(e)}")
        return False

async def save_lead_data(lead_data: Dict[str, Any]) -> str:
    try:
        db = get_firestore_client()
        # 🔧 CORRIGIDO: Mapear campos corretamente para salvar no Firestore
        lead_doc = {
            "name": lead_data.get("name", "Não informado"),
            "contact_info": lead_data.get("contact_info", "Não informado"),
            "area_qualification": lead_data.get("area_of_law", lead_data.get("area_qualification", "Não informado")),
            "case_details": lead_data.get("situation", lead_data.get("case_details", "Não informado")), 
            "urgency_level": lead_data.get("urgency", "Não informado"),
            "meeting_preference": lead_data.get("wants_meeting", "Não informado"),
            "session_id": lead_data.get("session_id"),
            "platform": lead_data.get("platform", "web"),
            "phone_number": lead_data.get("phone_number"),
            "timestamp": datetime.now(),
            "status": "new",
            "source": "chatbot_intake",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        leads_ref = db.collection("leads")
        doc_ref = leads_ref.add(lead_doc)
        return doc_ref[1].id
    except Exception as e:
        logger.error(f"Erro ao salvar lead: {str(e)}")
        return f"offline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

async def update_lead_data(lead_id: str, update_data: Dict[str, Any]) -> bool:
    try:
        db = get_firestore_client()
        update_data["updated_at"] = datetime.now()
        db.collection("leads").document(lead_id).update(update_data)
        return True
    except Exception as e:
        logger.error(f"Erro ao atualizar lead {lead_id}: {str(e)}")
        return False

async def get_firebase_service_status() -> Dict[str, Any]:
    try:
        db = get_firestore_client()
        list(db.collection("conversation_flows").limit(1).get())
        health_doc = db.collection("_health_check").document("status")
        health_doc.set({
            "last_check": datetime.now(),
            "status": "healthy"
        })
        return {
            "service": "firebase_service",
            "status": "active",
            "firestore_connected": True,
            "collections": ["conversation_flows", "leads", "user_sessions", "_health_check"],
            "features": {"read_operations": True,"write_operations": True,"session_persistence": True,"lead_storage": True},
            "memory_cache": {"active_sessions": len(_memory_sessions),"fallback_ready": True},
            "message": "Firebase Firestore totalmente operacional",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check falhou: {str(e)}")
        return {
            "service": "firebase_service", 
            "status": "degraded",
            "firestore_connected": False,
            "error": str(e),
            "fallback_mode": True,
            "memory_cache": {"active_sessions": len(_memory_sessions),"fallback_ready": True},
            "message": f"Firebase indisponível, usando fallbacks: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }

async def update_firestore_flow_with_placeholders():
    try:
        db = get_firestore_client()
        flow_ref = db.collection("conversation_flows").document("law_firm_intake")
        updated_flow = _get_fallback_flow()
        updated_flow["force_updated_at"] = datetime.now()
        updated_flow["update_reason"] = "manual_placeholder_update"
        flow_ref.set(updated_flow, merge=False)
        return {"success": True, "message": "Flow atualizado com sucesso"}
    except Exception as e:
        logger.error(f"Erro ao atualizar flow: {str(e)}")
        return {"success": False, "error": str(e)}

def create_context_from_session_data(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    🔧 ENHANCED: Creates comprehensive context with all possible name variations
    """
    lead_data = session_data.get("lead_data", {})
    
    logger.info(f"🔍 CREATE_CONTEXT - lead_data keys: {list(lead_data.keys())}")
    
    # Extract the best available name from multiple possible fields
    best_name = (
        lead_data.get("identification") or 
        lead_data.get("name") or 
        lead_data.get("user_name") or
        lead_data.get("username") or
        session_data.get("user_name") or
        ""
    )
    
    if best_name:
        best_name = str(best_name).strip()
        logger.info(f"🔍 CREATE_CONTEXT - best_name found: '{best_name}'")
    
    context = {
        # Campos primários do Firebase
        "identification": lead_data.get("identification", ""),
        "contact_info": lead_data.get("contact_info", ""), 
        "area_qualification": lead_data.get("area_qualification", ""),
        "problem_description": lead_data.get("problem_description", ""),
        "urgency_level": lead_data.get("urgency_level", ""),
        "meeting_preference": lead_data.get("meeting_preference", ""),
        
        # CRITICAL: All name variations use the best available name
        "user_name": best_name,
        "username": best_name,
        "name": best_name,
        "userName": best_name,
        "user-name": best_name,
        "nome": best_name,
        "usuario": best_name,
        "cliente": best_name or "Cliente",
        
        # Other aliases for compatibility
        "contact": lead_data.get("contact_info", ""),
        "area": lead_data.get("area_qualification", ""),
        "area_of_law": lead_data.get("area_qualification", ""),
        "situation": lead_data.get("problem_description", ""),
        "case_details": lead_data.get("problem_description", ""),
        "urgency": lead_data.get("urgency_level", ""),
        "meeting": lead_data.get("meeting_preference", ""),
        
        # Dados da sessão
        "platform": session_data.get("platform", "web"),
        "phone_number": session_data.get("phone_number", ""),
        "session_id": session_data.get("session_id", ""),
        "email": lead_data.get("email", session_data.get("email", "")),
        "whatsapp": lead_data.get("whatsapp", lead_data.get("contact_info", "")),
    }
    
    # Log only the name-related fields for debugging
    name_fields = {k: v for k, v in context.items() if 'name' in k.lower() or k in ['identification', 'nome', 'usuario', 'cliente']}
    logger.info(f"🔍 CREATE_CONTEXT - name fields: {name_fields}")
    
    return context

def ensure_lead_step_from_message(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    🔧 ENHANCED: Robust identification filling with better validation
    """
    if not session_data:
        return session_data or {}

    lead_data = session_data.get("lead_data", {})
    last_msg = (session_data.get("last_user_message") or "").strip()
    current_step = session_data.get("current_step", 1)

    try:
        # Only apply heuristic on step 1 and if no name exists yet
        existing_name = (
            lead_data.get("identification") or 
            lead_data.get("name") or 
            lead_data.get("user_name")
        )
        
        if current_step == 1 and last_msg and not existing_name:
            # Lista de mensagens genéricas a ignorar
            invalid_greetings = {
                "oi", "olá", "ola", "hello", "hi", "hey", "bom dia", "boa tarde", 
                "boa noite", "eae", "e ai", "opa", "start", "iniciar", "começar",
                "sim", "não", "nao", "ok", "tudo bem", "beleza"
            }

            normalized_msg = last_msg.lower().strip()

            # Enhanced validation for names
            if (
                normalized_msg not in invalid_greetings
                and 2 <= len(last_msg) <= 120  # Tamanho razoável para um nome
                and re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", last_msg)  # Deve ter letras
                and not last_msg.isdigit()  # Não pode ser só números
                and len(last_msg.split()) >= 1  # Pelo menos uma palavra
                and not any(char in last_msg for char in ['@', 'http', 'www'])  # Não é email/link
                and not any(word in normalized_msg for word in ['telefone', 'email', 'whatsapp', 'contato'])  # Not contact info
            ):
                # Save in all name fields for consistency
                processed_name = last_msg.strip().title()
                lead_data["identification"] = processed_name
                lead_data["name"] = processed_name
                lead_data["user_name"] = processed_name
                lead_data["username"] = processed_name
                
                logger.info(f"🔧 HEURISTIC APPLIED: All name fields = '{processed_name}'")
            else:
                logger.info(f"🔧 HEURISTIC IGNORED: message doesn't look like a name: '{last_msg}'")

        session_data["lead_data"] = lead_data
        
    except Exception as e:
        logger.warning(f"Erro em ensure_lead_step_from_message: {e}")

    return session_data

async def clear_user_session(session_id: str) -> None:
    """Remove sessão de memória e Firestore."""
    try:
        _memory_sessions.pop(session_id, None)
        db = get_firestore_client()
        db.collection("user_sessions").document(session_id).delete()
    except Exception as e:
        logger.error(f"Erro ao limpar sessão {session_id}: {str(e)}")

async def update_lead_data_field(session_id: str, field: str, value: str) -> bool:
    """
    🔧 MELHORADO: Atualiza um campo específico com verificação de persistência.
    """
    try:
        session_data = await get_user_session(session_id)
        if session_data is None:
            session_data = {"session_id": session_id, "lead_data": {}}

        lead_data = session_data.get("lead_data", {})
        old_value = lead_data.get(field, "VAZIO")
        lead_data[field] = value.strip()

        # Atualiza nomes derivados se for o campo identification
        if field == "identification":
            lead_data["name"] = value.strip().title()
            lead_data["user_name"] = lead_data["name"]

        session_data["lead_data"] = lead_data
        success = await save_user_session(session_id, session_data)

        logger.info(f"🔧 UPDATE_FIELD: {field} alterado de '{old_value}' para '{value}' | sucesso: {success}")
        
        # 🔧 NOVO: Verificação adicional
        if success:
            # Pequena pausa e verificação
            await asyncio.sleep(0.1)
            verification_data = await get_user_session(session_id)
            if verification_data:
                saved_value = verification_data.get("lead_data", {}).get(field, "NÃO_ENCONTRADO")
                logger.info(f"🔧 VERIFICAÇÃO: valor salvo = '{saved_value}'")
                
        return success
    except Exception as e:
        logger.error(f"Erro ao atualizar lead_data {session_id}: {str(e)}")
        return False

async def enrich_lead_with_message(session_id: str, message: str) -> None:
    """
    Enriquecer dados do lead baseado em mensagens do usuário.
    """
    try:
        session_data = await get_user_session(session_id)
        if not session_data:
            return

        lead_data = session_data.get("lead_data", {})

        # Detecta email
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", message)
        if email_match:
            lead_data["email"] = email_match.group(0)

        # Detecta telefone (BR)
        phone_match = re.search(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}", message)
        if phone_match:
            lead_data["phone"] = phone_match.group(0)

        session_data["lead_data"] = lead_data
        await save_user_session(session_id, session_data)

    except Exception as e:
        logger.error(f"Erro em enrich_lead_with_message: {e}")

async def force_update_identification(session_id: str, name: str) -> bool:
    """
    🔧 NOVO: Força atualização do campo identification de forma direta.
    """
    try:
        db = get_firestore_client()
        
        # Atualizar diretamente no Firestore
        session_ref = db.collection("user_sessions").document(session_id)
        session_ref.update({
            "lead_data.identification": name.strip().title(),
            "lead_data.name": name.strip().title(),
            "lead_data.user_name": name.strip().title(),
            "last_updated": datetime.now()
        })
        
        # Também atualizar em memória
        if session_id in _memory_sessions:
            _memory_sessions[session_id]["lead_data"]["identification"] = name.strip().title()
            _memory_sessions[session_id]["lead_data"]["name"] = name.strip().title()
            _memory_sessions[session_id]["lead_data"]["user_name"] = name.strip().title()
        
        logger.info(f"🔧 FORCE_UPDATE: identification atualizado para '{name.strip().title()}'")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao forçar update de identification: {str(e)}")
        return False