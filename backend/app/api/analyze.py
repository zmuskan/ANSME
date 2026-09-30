from fastapi import APIRouter

from app.models.analysis import AnalyzeRequest
from app.services.product_extractor import extract_product_data

router = APIRouter()


@router.post("/analyze")
async def analyze(request: AnalyzeRequest):

    products = []

    for url in request.urls:
        data = await extract_product_data(url)
        products.append(data)

    return {
        "status": "success",
        "count": len(products),
        "products": products
    }