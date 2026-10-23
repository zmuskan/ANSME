from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import analyze as analyze_module
from app.api.analytics import router as analytics_router
from app.api.history import router as history_router
from app.api.leaderboard import router as leaderboard_router
from app.auth import get_current_user_id
from app.db.database import Base, get_db
from app.main import app as production_app
from app.models.analysis import Analysis
from app.models.evidence import Evidence
from app.models.price_history import PriceHistory
from app.repositories.analysis_repository import AnalysisRepository


class UserDataApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.user_id = uuid4()
        self.other_user_id = uuid4()
        self.app = FastAPI()
        self.app.include_router(analyze_module.router)
        self.app.include_router(history_router)
        self.app.include_router(analytics_router)
        self.app.include_router(leaderboard_router)

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

    def add_analysis(
        self,
        user_id: UUID,
        *,
        days_ago: int = 0,
        url: str | None = None,
        score: float = 7.0,
    ) -> Analysis:
        analysis = Analysis(
            user_id=user_id,
            url=url or f"https://shop.example/product/{uuid4()}",
            title="Example product",
            overall_score=score,
            verdict="CONSIDER",
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        with self.session_factory() as session:
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            return analysis

    def test_history_pagination_returns_all_owned_rows_over_50(self) -> None:
        for _ in range(156):
            self.add_analysis(self.user_id)
        self.add_analysis(self.other_user_id)

        first = self.client.get("/history?limit=100&offset=0")
        second = self.client.get("/history?limit=100&offset=100")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_records = first.json()
        second_records = second.json()
        self.assertEqual(len(first_records), 100)
        self.assertEqual(len(second_records), 56)
        self.assertEqual(len({item["id"] for item in first_records + second_records}), 156)

    def test_history_detail_and_price_history_are_analysis_scoped(self) -> None:
        shared_url = "https://shop.example/shared"
        first = self.add_analysis(self.user_id, url=shared_url)
        second = self.add_analysis(self.user_id, url=shared_url)
        with self.session_factory() as session:
            session.add_all(
                [
                    PriceHistory(analysis_id=first.id, price=100, price_currency="USD"),
                    PriceHistory(analysis_id=second.id, price=200, price_currency="USD"),
                ]
            )
            session.commit()

        response = self.client.get(f"/history/{first.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["price"] for row in response.json()["price_history"]["history"]],
            [100],
        )

    def test_user_cannot_read_or_delete_another_users_analysis(self) -> None:
        private_analysis = self.add_analysis(self.other_user_id)
        with self.session_factory() as session:
            session.add_all(
                [
                    Evidence(
                        analysis_id=private_analysis.id,
                        source_type="pro",
                        evidence_text="Private evidence",
                    ),
                    PriceHistory(
                        analysis_id=private_analysis.id,
                        price=100,
                        price_currency="USD",
                    ),
                ]
            )
            session.commit()

        self.assertEqual(self.client.get(f"/history/{private_analysis.id}").status_code, 404)
        self.assertEqual(
            self.client.delete(f"/history/{private_analysis.id}").status_code,
            404,
        )
        with self.session_factory() as session:
            self.assertIsNotNone(session.get(Analysis, private_analysis.id))
            self.assertEqual(
                session.query(Evidence)
                .filter(Evidence.analysis_id == private_analysis.id)
                .count(),
                1,
            )
            self.assertEqual(
                session.query(PriceHistory)
                .filter(PriceHistory.analysis_id == private_analysis.id)
                .count(),
                1,
            )

    def test_deleting_analysis_removes_only_its_child_records(self) -> None:
        analysis = self.add_analysis(self.user_id)
        unrelated = self.add_analysis(self.user_id)
        with self.session_factory() as session:
            session.add_all(
                [
                    Evidence(
                        analysis_id=analysis.id,
                        source_type="pro",
                        evidence_text="Analysis evidence",
                    ),
                    Evidence(
                        analysis_id=unrelated.id,
                        source_type="pro",
                        evidence_text="Unrelated evidence",
                    ),
                    PriceHistory(
                        analysis_id=analysis.id,
                        price=100,
                        price_currency="USD",
                    ),
                    PriceHistory(
                        analysis_id=unrelated.id,
                        price=200,
                        price_currency="USD",
                    ),
                ]
            )
            session.commit()

        response = self.client.delete(f"/history/{analysis.id}")

        self.assertEqual(response.status_code, 200)
        with self.session_factory() as session:
            self.assertIsNone(session.get(Analysis, analysis.id))
            self.assertEqual(
                session.query(Evidence)
                .filter(Evidence.analysis_id == analysis.id)
                .count(),
                0,
            )
            self.assertEqual(
                session.query(PriceHistory)
                .filter(PriceHistory.analysis_id == analysis.id)
                .count(),
                0,
            )
            self.assertIsNotNone(session.get(Analysis, unrelated.id))
            self.assertEqual(
                session.query(Evidence)
                .filter(Evidence.analysis_id == unrelated.id)
                .count(),
                1,
            )
            self.assertEqual(
                session.query(PriceHistory)
                .filter(PriceHistory.analysis_id == unrelated.id)
                .count(),
                1,
            )

    def test_analytics_are_user_scoped_and_date_filtered(self) -> None:
        self.add_analysis(self.user_id, days_ago=2)
        self.add_analysis(self.user_id, days_ago=12)
        self.add_analysis(self.other_user_id, days_ago=1)

        seven_days = self.client.get("/analytics?days=7")
        thirty_days = self.client.get("/analytics?days=30")

        self.assertEqual(seven_days.status_code, 200)
        self.assertEqual(thirty_days.status_code, 200)
        self.assertEqual(seven_days.json()["total_analyses"], 1)
        self.assertEqual(thirty_days.json()["total_analyses"], 2)
        self.assertEqual(len(seven_days.json()["history"]), 1)

    def test_empty_analytics_and_leaderboard_return_empty_data(self) -> None:
        analytics = self.client.get("/analytics")
        leaderboard = self.client.get("/leaderboard")

        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(analytics.json()["total_analyses"], 0)
        self.assertEqual(analytics.json()["history"], [])
        self.assertEqual(leaderboard.status_code, 200)
        self.assertEqual(leaderboard.json(), {"highest": [], "lowest": []})

    def test_leaderboard_requires_opt_in_and_omits_analysis_identifiers(self) -> None:
        self.add_analysis(
            self.user_id,
            url="https://alice:secret@shop.example/product?token=secret&color=blue#details",
        )
        self.add_analysis(self.user_id, url="ftp://shop.example/private")
        self.add_analysis(self.other_user_id)

        self.assertEqual(self.client.get("/leaderboard").json()["highest"], [])
        preference = self.client.put(
            "/leaderboard/participation",
            json={"enabled": True},
        )
        self.assertEqual(preference.status_code, 200)
        response = self.client.get("/leaderboard")
        self.assertEqual(response.status_code, 200)
        entries = response.json()["highest"]
        self.assertEqual(len(entries), 2)
        sanitized = next(item for item in entries if item["url"] is not None)
        self.assertEqual(sanitized["url"], "https://shop.example/product")
        self.assertNotIn("secret", str(entries))
        unsafe = next(item for item in entries if item["url"] is None)
        self.assertEqual(unsafe["title"], "Example product")
        self.assertNotIn("id", sanitized)
        self.assertNotIn("created_at", sanitized)

        self.client.put("/leaderboard/participation", json={"enabled": False})
        self.assertEqual(self.client.get("/leaderboard").json()["highest"], [])

    def test_analysis_can_succeed_without_saving_history(self) -> None:
        result = {"url": "https://shop.example/item", "status": "success"}
        with (
            patch.object(analyze_module, "_process_url", new=AsyncMock(return_value=result)),
            patch.object(analyze_module, "_persist_successful_products") as persist,
        ):
            response = self.client.post(
                "/analyze",
                json={"urls": [result["url"]], "save_history": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["successful_count"], 1)
        persist.assert_not_called()

    def test_analysis_saved_to_history_can_be_retrieved_by_same_user(self) -> None:
        result = {
            "url": "https://shop.example/saved-item",
            "status": "success",
            "overall_score": 7.5,
            "verdict": "CONSIDER",
            "analysis": {"pros": [], "cons": []},
        }
        with patch.object(
            analyze_module,
            "_process_url",
            new=AsyncMock(return_value=result),
        ):
            response = self.client.post(
                "/analyze",
                json={"urls": [result["url"]], "save_history": True},
            )

        self.assertEqual(response.status_code, 200)
        saved_product = response.json()["products"][0]
        self.assertTrue(saved_product["history_saved"])

        history = self.client.get("/history?limit=100&offset=0")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        analysis_id = history.json()[0]["id"]
        detail = self.client.get(f"/history/{analysis_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["url"], result["url"])

    def test_production_cors_covers_put_and_unhandled_errors(self) -> None:
        fastapi_app = production_app.app
        original_overrides = dict(fastapi_app.dependency_overrides)

        def override_get_db():
            with self.session_factory() as session:
                yield session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[get_current_user_id] = lambda: self.user_id
        try:
            with TestClient(
                production_app,
                raise_server_exceptions=False,
            ) as client:
                with patch.object(
                    AnalysisRepository,
                    "list_analyses",
                    side_effect=RuntimeError("simulated unhandled failure"),
                ):
                    failure = client.get(
                        "/history",
                        headers={"Origin": "http://localhost:8080"},
                    )
                success = client.get(
                    "/history",
                    headers={"Origin": "http://localhost:8080"},
                )
                handled_error = client.get(
                    "/history/999999",
                    headers={"Origin": "http://localhost:8080"},
                )
                preflight = client.options(
                    "/leaderboard/participation",
                    headers={
                        "Origin": "http://127.0.0.1:8080",
                        "Access-Control-Request-Method": "PUT",
                        "Access-Control-Request-Headers": (
                            "authorization,content-type"
                        ),
                    },
                )

            self.assertEqual(failure.status_code, 500)
            self.assertEqual(
                failure.headers.get("access-control-allow-origin"),
                "http://localhost:8080",
            )
            self.assertEqual(success.status_code, 200)
            self.assertEqual(
                success.headers.get("access-control-allow-origin"),
                "http://localhost:8080",
            )
            self.assertEqual(handled_error.status_code, 404)
            self.assertEqual(
                handled_error.headers.get("access-control-allow-origin"),
                "http://localhost:8080",
            )
            self.assertEqual(preflight.status_code, 200)
            self.assertEqual(
                preflight.headers.get("access-control-allow-origin"),
                "http://127.0.0.1:8080",
            )
            self.assertIn(
                "PUT",
                preflight.headers.get("access-control-allow-methods", ""),
            )
        finally:
            fastapi_app.dependency_overrides.clear()
            fastapi_app.dependency_overrides.update(original_overrides)

    def test_analysis_reports_persistence_failure_and_cleans_partial_row(self) -> None:
        result = {
            "url": "https://shop.example/item",
            "status": "success",
            "overall_score": 7.5,
            "verdict": "CONSIDER",
            "price": 100,
        }
        with (
            patch.object(analyze_module, "_process_url", new=AsyncMock(return_value=result)),
            patch.object(
                analyze_module.PriceHistoryRepository,
                "create",
                side_effect=SQLAlchemyError("simulated database failure"),
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
        self.assertEqual(
            payload["products"][0]["history_save_error"],
            "Analysis completed, but it could not be saved to your history.",
        )
        with self.session_factory() as session:
            self.assertEqual(
                session.query(Analysis)
                .filter(Analysis.url == result["url"])
                .count(),
                0,
            )

    def test_analysis_returns_per_url_failure_without_claiming_success(self) -> None:
        failure = {
            "url": "https://shop.example/missing",
            "status": "error",
            "error": "Product page unavailable.",
        }
        with patch.object(
            analyze_module,
            "_process_url",
            new=AsyncMock(return_value=failure),
        ):
            response = self.client.post(
                "/analyze",
                json={"urls": [failure["url"]], "save_history": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["successful_count"], 0)
        self.assertEqual(response.json()["failed_count"], 1)
        self.assertEqual(response.json()["products"][0]["status"], "error")

    def test_delete_database_failure_is_not_a_success_response(self) -> None:
        analysis = self.add_analysis(self.user_id)
        client = TestClient(self.app, raise_server_exceptions=False)
        with patch.object(
            AnalysisRepository,
            "delete_analysis",
            side_effect=SQLAlchemyError("database unavailable"),
        ):
            response = client.delete(f"/history/{analysis.id}")

        client.close()
        self.assertEqual(response.status_code, 500)

    def test_history_routes_require_authentication(self) -> None:
        self.app.dependency_overrides.pop(get_current_user_id)
        protected_requests = (
            ("get", "/history"),
            ("get", "/history/1"),
            ("delete", "/history/1"),
            ("get", "/analytics?days=30"),
            ("get", "/leaderboard/participation"),
            ("put", "/leaderboard/participation"),
        )
        for method, path in protected_requests:
            response = getattr(self.client, method)(
                path,
                **({"json": {"enabled": True}} if method == "put" else {}),
            )
            self.assertEqual(response.status_code, 401, f"{method.upper()} {path}")

        self.assertEqual(self.client.get("/leaderboard").status_code, 200)


if __name__ == "__main__":
    unittest.main()
