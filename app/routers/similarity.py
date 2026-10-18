import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.deps import get_current_user
from app.services.similarity_service import IntakePayload, ModelUnavailable, run_similarity

router = APIRouter(prefix="/api/v1", tags=["Similarity V2"])
logger = logging.getLogger(__name__)

@router.post("/predict_similarity")
def predict_similarity(payload: IntakePayload, me=Depends(get_current_user)):
    # V2 intake is self-service; a submitted identifier does not grant patient access.
    if str(payload.patient_id) != str(me.id):
        raise HTTPException(status_code=403, detail="patient_id must match the signed-in user")
    try:
        return run_similarity(payload)
    except ModelUnavailable:
        logger.exception("similarity_model_unavailable")
        raise HTTPException(status_code=503, detail="V2 prediction model is not available")
    except Exception:
        logger.exception("similarity_inference_failed")
        raise HTTPException(status_code=500, detail="Unable to calculate similarity")
