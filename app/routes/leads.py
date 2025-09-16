"""
Lead Assignment Routes

Routes for handling lead assignments with clickable links.
"""

import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.lead_assignment_service import lead_assignment_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/leads/{lead_id}/assign/{lawyer_id}")
async def assign_lead_to_lawyer(lead_id: str, lawyer_id: str):
    """
    Assign a lead to a lawyer via clickable link.
    
    Args:
        lead_id (str): ID of the lead to assign
        lawyer_id (str): ID/phone of the lawyer
        
    Returns:
        RedirectResponse or HTMLResponse: WhatsApp redirect or error message
    """
    try:
        logger.info(f"🎯 Lead assignment request - Lead: {lead_id}, Lawyer: {lawyer_id}")
        
        # Process the assignment
        result = await lead_assignment_service.assign_lead_to_lawyer(lead_id, lawyer_id)
        
        if result["success"]:
            # Success - redirect to WhatsApp
            whatsapp_url = result.get("whatsapp_url")
            if whatsapp_url:
                logger.info(f"✅ Redirecting to WhatsApp: {whatsapp_url}")
                return RedirectResponse(url=whatsapp_url, status_code=302)
            else:
                # Fallback if WhatsApp URL generation failed
                html_content = f"""
                <!DOCTYPE html>
                <html lang="pt-BR">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>✅ Lead Assigned Successfully</title>
                    <style>
                        body {{
                            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            margin: 0;
                            padding: 20px;
                            min-height: 100vh;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                        }}
                        .container {{
                            background: white;
                            border-radius: 15px;
                            padding: 40px;
                            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                            text-align: center;
                            max-width: 500px;
                            width: 100%;
                        }}
                        .success-icon {{
                            font-size: 4rem;
                            color: #28a745;
                            margin-bottom: 20px;
                        }}
                        .title {{
                            color: #28a745;
                            font-size: 1.8rem;
                            font-weight: bold;
                            margin-bottom: 15px;
                        }}
                        .message {{
                            color: #333;
                            font-size: 1.1rem;
                            line-height: 1.6;
                            margin-bottom: 20px;
                        }}
                        .lead-info {{
                            background: #f8f9fa;
                            border-radius: 10px;
                            padding: 20px;
                            margin: 20px 0;
                            border-left: 4px solid #28a745;
                        }}
                        .footer {{
                            color: #666;
                            font-size: 0.9rem;
                            margin-top: 30px;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="success-icon">✅</div>
                        <h1 class="title">Lead Successfully Assigned!</h1>
                        <p class="message">{result['message']}</p>
                        <div class="lead-info">
                            <strong>Lead:</strong> {result.get('lead_name', 'N/A')}<br>
                            <strong>Assigned to:</strong> {result.get('assigned_to', 'N/A')}
                        </div>
                        <div class="footer">
                            Please contact the client as soon as possible.<br>
                            <small>Law Firm Assignment System</small>
                        </div>
                    </div>
                </body>
                </html>
                """
                return HTMLResponse(content=html_content, status_code=200)
        
        else:
            # Error or already assigned
            status_code = 409 if result["status"] == "already_assigned" else 404
            error_color = "#ffc107" if result["status"] == "already_assigned" else "#dc3545"
            error_icon = "⚠️" if result["status"] == "already_assigned" else "❌"
            
            html_content = f"""
            <!DOCTYPE html>
            <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{error_icon} Assignment Error</title>
                <style>
                    body {{
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        margin: 0;
                        padding: 20px;
                        min-height: 100vh;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                    }}
                    .container {{
                        background: white;
                        border-radius: 15px;
                        padding: 40px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                        text-align: center;
                        max-width: 500px;
                        width: 100%;
                    }}
                    .error-icon {{
                        font-size: 4rem;
                        color: {error_color};
                        margin-bottom: 20px;
                    }}
                    .title {{
                        color: {error_color};
                        font-size: 1.8rem;
                        font-weight: bold;
                        margin-bottom: 15px;
                    }}
                    .message {{
                        color: #333;
                        font-size: 1.1rem;
                        line-height: 1.6;
                        margin-bottom: 20px;
                    }}
                    .info-box {{
                        background: #f8f9fa;
                        border-radius: 10px;
                        padding: 20px;
                        margin: 20px 0;
                        border-left: 4px solid {error_color};
                    }}
                    .footer {{
                        color: #666;
                        font-size: 0.9rem;
                        margin-top: 30px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error-icon">{error_icon}</div>
                    <h1 class="title">Assignment Not Possible</h1>
                    <p class="message">{result['message']}</p>
                    {f'<div class="info-box"><strong>Assigned to:</strong> {result.get("assigned_to", "N/A")}</div>' if result.get("assigned_to") else ''}
                    <div class="footer">
                        <small>Law Firm Assignment System</small>
                    </div>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content, status_code=status_code)
            
    except Exception as e:
        logger.error(f"❌ Error in lead assignment endpoint: {str(e)}")
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>❌ System Error</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    margin: 0;
                    padding: 20px;
                    min-height: 100vh;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                }}
                .container {{
                    background: white;
                    border-radius: 15px;
                    padding: 40px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                    text-align: center;
                    max-width: 500px;
                    width: 100%;
                }}
                .error-icon {{
                    font-size: 4rem;
                    color: #dc3545;
                    margin-bottom: 20px;
                }}
                .title {{
                    color: #dc3545;
                    font-size: 1.8rem;
                    font-weight: bold;
                    margin-bottom: 15px;
                }}
                .message {{
                    color: #333;
                    font-size: 1.1rem;
                    line-height: 1.6;
                    margin-bottom: 20px;
                }}
                .footer {{
                    color: #666;
                    font-size: 0.9rem;
                    margin-top: 30px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error-icon">❌</div>
                <h1 class="title">System Error</h1>
                <p class="message">An internal error occurred while processing your request. Please try again later or contact support.</p>
                <div class="footer">
                    <small>Law Firm Assignment System</small>
                </div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=500)


@router.get("/leads/{lead_id}")
async def get_lead_details(lead_id: str):
    """
    Get lead details by ID.
    
    Args:
        lead_id (str): ID of the lead
        
    Returns:
        Dict: Lead details
    """
    try:
        lead_data = await lead_assignment_service._get_lead_from_firebase(lead_id)
        
        if not lead_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        return {
            "success": True,
            "lead": lead_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting lead details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get lead details"
        )


@router.post("/leads/test-assignment")
async def test_lead_assignment():
    """
    Test endpoint to create a sample lead with assignment links.
    """
    try:
        result = await lead_assignment_service.create_lead_with_assignment_links(
            lead_name="João Silva (TESTE)",
            lead_phone="11999999999",
            category="Penal",
            situation="Teste do sistema de atribuição de leads com links clicáveis"
        )
        
        return {
            "success": True,
            "message": "Test lead created and notifications sent",
            "result": result
        }
        
    except Exception as e:
        logger.error(f"❌ Error in test assignment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create test lead"
        )