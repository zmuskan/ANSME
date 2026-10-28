from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import analyze as analyze_module
from app.api.analytics import router as analytics_router
from app.auth import get_current_user_id
from app.db.database import Base, get_db
from app.models.analysis import Analysis
from app.services.comparison_engine import compare_products


class AnalysisComparisonFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.user_id = uuid4()
        self.app = FastAPI()
        self.app.include_router(analyze_module.router)
        self.app.include_router(analytics_router)

        def override_get_db():
            with self.session_factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_get_db
        self.app.dependency_overrides[get_current_user_id] = lambda: self.user_id
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    @staticmethod
    def success(url: str, score: float = 7.0) -> dict:
        return {
            "url": url,
            "status": "success",
            "title": f"Product at {url}",
            "overall_score": score,
            "verdict": "CONSIDER",
        }

    @staticmethod
    def failure(url: str) -> dict:
        return {"url": url, "status": "error", "error": "Could not extract product."}

    def test_two_and_three_successful_products_keep_the_api_contract(self) -> None:
        for count in (2, 3):
            urls = [f"https://shop.example/item-{index}" for index in range(count)]
            expected = [self.success(url, 8.0 - index) for index, url in enumerate(urls)]
            with self.subTest(count=count), patch.object(
                analyze_module,
                "_process_url",
                new=AsyncMock(side_effect=expected),
            ):
                response = self.client.post(
                    "/analyze",
                    json={"urls": urls, "save_history": False},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["processed_count"], count)
            self.assertEqual(payload["successful_count"], count)
            self.assertEqual(payload["failed_count"], 0)
            self.assertEqual([product["url"] for product in payload["products"]], urls)
            self.assertEqual(
                [product["overall_score"] for product in payload["products"]],
                [item["overall_score"] for item in expected],
            )

    def test_one_successful_and_one_failed_extraction_preserves_both(self) -> None:
        urls = ["https://shop.example/good", "https://shop.example/missing"]
        results = [self.success(urls[0]), self.failure(urls[1])]
        with patch.object(
            analyze_module,
            "_process_url",
            new=AsyncMock(side_effect=results),
        ):
            response = self.client.post(
                "/analyze",
                json={"urls": urls, "save_history": False},
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["successful_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual([product["status"] for product in payload["products"]], ["success", "error"])

    def test_all_failed_extractions_return_each_failure_without_server_error(self) -> None:
        urls = ["https://shop.example/missing-a", "https://shop.example/missing-b"]
        failures = [self.failure(url) for url in urls]
        with patch.object(
            analyze_module,
            "_process_url",
            new=AsyncMock(side_effect=failures),
        ):
            response = self.client.post(
                "/analyze",
                json={"urls": urls, "save_history": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["successful_count"], 0)
        self.assertEqual(response.json()["failed_count"], 2)
        self.assertEqual(
            [product["error"] for product in response.json()["products"]],
            [failure["error"] for failure in failures],
        )

    def test_persistence_runtime_error_does_not_fail_successful_analysis(self) -> None:
        result = {
            "url": "https://shop.example/item",
            "status": "success",
            "title": "Product",
            "price": 100.0,
            "overall_score": 7.5,
            "verdict": "CONSIDER",
            "analysis": {"pros": [], "cons": []},
        }
        with (
            patch.object(
                analyze_module,
                "_process_url",
                new=AsyncMock(return_value=result),
            ),
            patch.object(
                analyze_module.PriceHistoryRepository,
                "create",
                side_effect=RuntimeError("simulated persistence failure"),
            ),
        ):
            response = self.client.post(
                "/analyze",
                json={"urls": [result["url"]], "save_history": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["successful_count"], 1)
        self.assertEqual(payload["products"][0]["status"], "success")
        self.assertFalse(payload["products"][0]["history_saved"])
        with self.session_factory() as session:
            self.assertEqual(
                session.query(Analysis)
                .filter(Analysis.url == result["url"])
                .count(),
                0,
            )

    def test_currency_mismatch_does_not_apply_budget_and_requirements_stay_separate(self) -> None:
        product = {
            "url": "https://shop.example/phone",
            "title": "Gaming phone",
            "description": "Battery lasts all day",
            "price": 150.0,
            "price_currency": "INR",
            "rating": 4.0,
            "status": "success",
        }

        async def process(currency: str | None, requirements: str | None):
            with patch.object(
                analyze_module,
                "extract_product_data",
                new=AsyncMock(return_value=product),
            ):
                return await analyze_module._process_url(
                    product["url"],
                    100.0,
                    asyncio.Semaphore(1),
                    requirements,
                    currency,
                    True,
                )

        matching_budget = asyncio.run(process("INR", "gaming battery"))
        mismatched_budget = asyncio.run(process("USD", "gaming battery"))
        without_requirements = asyncio.run(process("USD", None))

        self.assertEqual(matching_budget["budget_status"], "applied")
        self.assertEqual(matching_budget["metrics"]["value_score"], 5.0)
        self.assertEqual(mismatched_budget["budget_status"], "unverified")
        self.assertEqual(mismatched_budget["metrics"]["value_score"], 7.0)
        self.assertEqual(mismatched_budget["analysis"]["requirement_match"], 10.0)
        self.assertEqual(without_requirements["analysis"]["requirement_match"], 5.0)
        self.assertEqual(
            mismatched_budget["overall_score"],
            without_requirements["overall_score"],
        )

    def test_unmarked_legacy_budget_keeps_numeric_behavior(self) -> None:
        product = {
            "url": "https://shop.example/phone",
            "title": "Phone",
            "price": 150.0,
            "price_currency": "INR",
            "rating": 4.0,
            "status": "success",
        }
        with patch.object(
            analyze_module,
            "extract_product_data",
            new=AsyncMock(return_value=product),
        ):
            result = asyncio.run(
                analyze_module._process_url(
                    product["url"],
                    100.0,
                    asyncio.Semaphore(1),
                )
            )

        self.assertEqual(result["budget_status"], "legacy_numeric")
        self.assertEqual(result["metrics"]["value_score"], 5.0)

    def test_currency_marked_budget_is_unverified_without_a_price(self) -> None:
        product = {
            "url": "https://shop.example/unknown-price",
            "title": "Phone",
            "price": None,
            "price_currency": "INR",
            "rating": 4.0,
            "status": "success",
        }
        with patch.object(
            analyze_module,
            "extract_product_data",
            new=AsyncMock(return_value=product),
        ):
            result = asyncio.run(
                analyze_module._process_url(
                    product["url"],
                    100.0,
                    asyncio.Semaphore(1),
                    budget_currency="INR",
                    budget_currency_is_explicit=True,
                )
            )

        self.assertEqual(result["budget_status"], "unverified")
        self.assertEqual(result["metrics"]["value_score"], 7.0)

    def test_pairwise_comparison_handles_missing_fields_and_currency_mismatch(self) -> None:
        result = compare_products(
            {
                "title": "Unknown price",
                "price": None,
                "rating": None,
                "overall_score": 7.0,
                "price_currency": "INR",
            },
            {
                "title": "Different currency",
                "price": 20.0,
                "rating": 4.0,
                "overall_score": 7.0,
                "price_currency": "USD",
            },
        )

        self.assertEqual(result["winning_key"], "tie")
        self.assertEqual(result["dimension_winners"]["rating_winner"], "Different currency")
        self.assertEqual(result["dimension_winners"]["price_winner"], "N/A")
        self.assertIn("unavailable", result["comparison"]["rating"])
        self.assertIn("shared currency", result["comparison"]["price"])

    def test_pairwise_comparison_reports_ties(self) -> None:
        product = {
            "title": "Same product",
            "price": 100.0,
            "price_currency": "INR",
            "rating": 4.0,
            "overall_score": 8.0,
        }
        result = compare_products(product, product)

        self.assertEqual(result["winning_key"], "tie")
        self.assertEqual(result["winner"], "tie")
        self.assertEqual(result["score_difference"], 0.0)

    def test_analytics_compare_endpoint_reuses_pairwise_engine_tie_breakers(self) -> None:
        response = self.client.post(
            "/analytics/compare",
            json={
                "product_a": {
                    "title": "Product A",
                    "overall_score": 8.0,
                    "rating": 4.2,
                    "price": 100.0,
                    "price_currency": "INR",
                },
                "product_b": {
                    "title": "Product B",
                    "overall_score": 8.0,
                    "rating": 4.7,
                    "price": 150.0,
                    "price_currency": "INR",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["winning_key"], "product_b")


if __name__ == "__main__":
    unittest.main()
