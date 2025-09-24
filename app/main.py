from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
import os
import asyncio
from dotenv import load_dotenv

# Import routes
from app.routes.test import router as test_router
from app.routes.chat import router as chat_router
from app.routes.conversation import router as conversation_router
from app.routes.whatsapp import router as whatsapp_router
from app.routes.leads import router as leads_router

# Import services for startup
from app.services.firebase_service import initialize_firebase
from app.services.baileys_service import baileys_service

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI instance
app = FastAPI(
    title="Law Firm AI Chat Backend",
    description="Production-ready FastAPI backend for law firm client intake with WhatsApp integration",
    version="2.0.0"
)

# -------------------------
# CORS Configuration - MUST COME BEFORE ALL ROUTERS
# -------------------------
# Define allowed origins
allowed_origins = [
    "https://projectlawyer.netlify.app",
    "https://68cdc61---projectlawyer.netlify.app",
    "https://*.netlify.app",
    "https://law-firm-backend-936902782519.us-central1.run.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8000",
]

# Function to check if origin is allowed
def is_origin_allowed(origin: str) -> bool:
    """Check if origin is allowed, including wildcard patterns."""
    if not origin:
        return False
    
    # Direct match
    if origin in allowed_origins:
        return True
    
    # Check localhost patterns
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        return True
    
    # Check netlify patterns
    if ".netlify.app" in origin and origin.startswith("https://"):
        return True
    
    return False

# Add CORS middleware with comprehensive configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now, we'll handle it manually
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-Request-ID",
        "X-HTTP-Method-Override",
        "Cache-Control",
        "Pragma",
        "Expires"
    ],
    expose_headers=[
        "Content-Type",
        "Authorization",
        "X-Request-ID",
        "Cache-Control"
    ],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Add manual CORS headers for additional safety
@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    """Add CORS headers manually for additional safety."""
    # Handle preflight requests first
    if request.method == "OPTIONS":
        origin = request.headers.get("origin")
        
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-Request-ID, X-HTTP-Method-Override, Cache-Control, Pragma, Expires",
            "Access-Control-Expose-Headers": "Content-Type, Authorization, X-Request-ID, Cache-Control",
            "Access-Control-Max-Age": "3600",
            "Access-Control-Allow-Credentials": "true",
            "Content-Length": "0"
        }
        
        # Set appropriate origin
        if is_origin_allowed(origin):
            headers["Access-Control-Allow-Origin"] = origin
        else:
            headers["Access-Control-Allow-Origin"] = "*"
        
        from fastapi.responses import Response
        return Response(status_code=200, headers=headers)
    
    # Process normal requests
    response = await call_next(request)
    
    # Get origin from request
    origin = request.headers.get("origin")
    
    # Set CORS headers based on origin
    if is_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        # Allow all origins as fallback
        response.headers["Access-Control-Allow-Origin"] = "*"
    
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-Request-ID, X-HTTP-Method-Override, Cache-Control, Pragma, Expires"
    response.headers["Access-Control-Expose-Headers"] = "Content-Type, Authorization, X-Request-ID, Cache-Control"
    response.headers["Access-Control-Max-Age"] = "3600"
    
    return response

# Handle preflight OPTIONS requests globally
@app.options("/{full_path:path}")
async def options_handler(request: Request, full_path: str):
    """Handle preflight OPTIONS requests for all routes."""
    origin = request.headers.get("origin")
    
    # Set appropriate origin
    if is_origin_allowed(origin):
        allowed_origin = origin
    else:
        allowed_origin = "*"
    
    headers = {
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-Request-ID, X-HTTP-Method-Override, Cache-Control, Pragma, Expires",
        "Access-Control-Expose-Headers": "Content-Type, Authorization, X-Request-ID, Cache-Control",
        "Access-Control-Max-Age": "3600",
        "Content-Length": "0"
    }
    
    return JSONResponse(content="", status_code=200, headers=headers)

# -------------------------
# Include routers (AFTER CORS)
# -------------------------
app.include_router(test_router, prefix="/api/v1", tags=["Test"])
app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])
app.include_router(conversation_router, prefix="/api/v1", tags=["Conversation"])
app.include_router(whatsapp_router, prefix="/api/v1", tags=["WhatsApp"])
app.include_router(leads_router, prefix="/api/v1", tags=["Leads"])

# -------------------------
# Startup & Shutdown Events
# -------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting up FastAPI application...")

    try:
        # Initialize Firebase (rápido, essencial)
        try:
            initialize_firebase()
            logger.info("✅ Firebase initialized successfully")
        except Exception as firebase_error:
            logger.error(f"❌ Firebase initialization failed: {str(firebase_error)}")

        logger.info("✅ Essential services initialized - FastAPI ready to serve")

        # Inicializar Baileys em background (não bloquear startup)
        asyncio.create_task(initialize_baileys_background())

    except Exception as e:
        logger.error(f"❌ Startup initialization failed: {str(e)}")

async def initialize_baileys_background():
    try:
        await asyncio.sleep(3)
        logger.info("🔌 Initializing Baileys WhatsApp service in background...")
        await baileys_service.initialize()
        logger.info("✅ Baileys WhatsApp service connection initialized")
    except Exception as baileys_error:
        logger.error(f"❌ Baileys background initialization failed: {str(baileys_error)}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("📴 Shutting down FastAPI application...")
    try:
        await baileys_service.cleanup()
        logger.info("✅ Services cleaned up successfully")
    except Exception as e:
        logger.warning(f"⚠️ Cleanup warning: {str(e)}")

# -------------------------
# Health Check
# -------------------------
@app.get("/health")
@app.head("/health")
async def health_check():
    try:
        basic_response = {
            "status": "healthy",
            "message": "Law Firm AI Chat Backend is running",
            "services": {
                "fastapi": "active"
            },
            "uptime": "active"
        }

        try:
            whatsapp_status = await asyncio.wait_for(
                baileys_service.get_connection_status(),
                timeout=2.0
            )
            basic_response["services"]["whatsapp_bot"] = whatsapp_status.get("status", "unknown")

        except asyncio.TimeoutError:
            logger.warning("⏰ WhatsApp status check timed out")
            basic_response["services"]["whatsapp_bot"] = "timeout"
        except Exception as e:
            logger.warning(f"⚠️ WhatsApp status check failed: {str(e)}")
            basic_response["services"]["whatsapp_bot"] = "error"

        return basic_response

    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return JSONResponse(
            status_code=200,
            content={
                "status": "degraded",
                "message": "FastAPI is running but some services may be unavailable",
                "services": {
                    "fastapi": "active",
                    "whatsapp_bot": "unknown",
                    "firebase": "unknown",
                    "gemini_ai": "unknown"
                },
                "error": "health_check_partial_failure",
                "uptime": "active"
            }
        )

# -------------------------
# Status Detalhado
# -------------------------
@app.get("/api/v1/status")
async def detailed_status():
    try:
        from app.services.orchestration_service import intelligent_orchestrator
        service_status = await intelligent_orchestrator.get_overall_service_status()
        whatsapp_status = await baileys_service.get_connection_status()

        return {
            "overall_status": service_status["overall_status"],
            "services": {
                "fastapi": "active",
                "whatsapp_bot": whatsapp_status,
                "firebase": service_status["firebase_status"],
                "gemini_ai": service_status["ai_status"]
            },
            "features": [
                "guided_conversation_flow",
                "whatsapp_integration",
                "ai_powered_responses" if service_status.get("gemini_available") else "fallback_responses",
                "lead_management",
                "session_persistence"
            ],
            "fallback_mode": service_status.get("fallback_mode", True),
            "phone_number": os.getenv("WHATSAPP_PHONE_NUMBER", "not-configured"),
            "detailed_status": service_status
        }
    except Exception as e:
        logger.error(f"Detailed status error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")

# -------------------------
# Exception Handlers
# -------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "message": exc.detail, "status_code": exc.status_code},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "message": "Validation error",
            "details": exc.errors(),
            "status_code": 422,
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unexpected error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": True, "message": "Internal server error", "status_code": 500},
    )

# -------------------------
# Root Endpoint
# -------------------------
@app.get("/")
async def root():
    return {
        "message": "Law Firm AI Chat Backend API",
        "version": "2.0.0",
        "docs_url": "/docs",
        "health_check": "/health",
        "status_check": "/api/v1/status",
        "endpoints": {
            "conversation_start": "/api/v1/conversation/start",
            "conversation_respond": "/api/v1/conversation/respond",
            "chat": "/api/v1/chat",
            "whatsapp_status": "/api/v1/whatsapp/status"
        }
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
        loop="asyncio"
    )