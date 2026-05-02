from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from app.services.predictor_service import predictor
from app.database import get_database
from datetime import datetime

router = APIRouter(tags=["predictor"])

class PredictionRequest(BaseModel):
    rank: int
    category: str = "OPEN"
    gender: str = "Gender-Neutral"

class LeadRequest(BaseModel):
    rank: int
    email: EmailStr

@router.post("/predict")
async def predict_colleges(request: PredictionRequest):
    results = predictor.predict(request.rank, request.category, request.gender)
    if not results:
        return {"colleges": [], "message": "no colleges found with your rank"}
    return {"colleges": results}

@router.post("/predict/lead")
async def save_lead(request: LeadRequest):
    db = get_database()
    lead = {
        "email": request.email,
        "rank": request.rank,
        "created_at": datetime.utcnow(),
        "source": "college_predictor"
    }
    await db.predictor_leads.insert_one(lead)
    return {"status": "success", "message": "We will get back to you soon!"}
