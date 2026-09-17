from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Optional

from agents import FundamentalTechnicalAgent, NewsContextAgent, PersonalizedAdviceAgent, RiskEvidenceReviewer
from data.market_snapshot_service import MarketSnapshotService
from database import AgentOutput, AnalysisRun, SessionLocal
from llm_service import LLMService
from models.analysis_models import AdviceOutput


class ReportWorkflow:
    """Deterministic orchestration around narrow, auditable reasoning roles."""

    def __init__(self, snapshot_service=None, llm=None, db_session=None):
        self.db = db_session
        self.snapshot_service = snapshot_service or MarketSnapshotService(db_session=db_session)
        shared_llm = llm or LLMService()
        self.news_agent = NewsContextAgent(shared_llm)
        self.analysis_agent = FundamentalTechnicalAgent(shared_llm)
        self.advice_agent = PersonalizedAdviceAgent(shared_llm)
        self.reviewer = RiskEvidenceReviewer(shared_llm)

    def run(self, symbol: str, profile: Dict[str, str], user_id: Optional[int] = None) -> Dict:
        owns_session = self.db is None
        db = self.db or SessionLocal()
        if self.snapshot_service.db is None:
            self.snapshot_service.db = db
        run = AnalysisRun(user_id=user_id, symbol=symbol.upper(), status='running')
        db.add(run)
        db.commit()
        try:
            snapshot, snapshot_id = self.snapshot_service.get_or_collect(symbol)
            run.snapshot_id = snapshot_id
            db.commit()

            with ThreadPoolExecutor(max_workers=2) as executor:
                news_future = executor.submit(self.news_agent.run, snapshot)
                analysis_future = executor.submit(self.analysis_agent.run, snapshot)
                news = news_future.result()
                analysis = analysis_future.result()
            self._save_output(db, run.id, news.agent_name, news.dict())
            self._save_output(db, run.id, analysis.agent_name, analysis.dict())

            advice = self.advice_agent.run(snapshot, news, analysis, profile)
            self._save_output(db, run.id, self.advice_agent.name, advice.dict())
            review = self.reviewer.run(snapshot, advice)
            self._save_output(db, run.id, self.reviewer.name, review.dict())

            final_advice = review.corrected_advice or advice
            if review.status.lower() == 'revise' and review.notes:
                final_advice.risks = list(dict.fromkeys(final_advice.risks + review.notes))[:3]

            result = self._to_result(snapshot, final_advice, review.status, review.notes)
            run.status = 'completed' if review.status.lower() != 'reject' else 'review_rejected'
            run.result_json = json.dumps(result, ensure_ascii=False, default=str)
            run.completed_at = datetime.utcnow()
            db.commit()
            return result
        except Exception as exc:
            run.status = 'failed'
            run.error_message = str(exc)[:1000]
            run.completed_at = datetime.utcnow()
            db.commit()
            raise
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def _save_output(db, run_id: int, name: str, payload: Dict) -> None:
        db.add(AgentOutput(analysis_run_id=run_id, agent_name=name, output_json=json.dumps(payload, ensure_ascii=False, default=str)))
        db.commit()

    @staticmethod
    def _to_result(snapshot, advice: AdviceOutput, review_status: str, review_notes) -> Dict:
        outlook = advice.outlook if advice.outlook in ('Positive', 'Neutral', 'Cautious') else 'Neutral'
        return {
            'symbol': snapshot.symbol,
            'signal': outlook,
            'reason': advice.summary,
            'news_summary': ' | '.join(advice.reasons[:2]) or 'ไม่มีข้อมูลข่าวที่ตรวจสอบได้ในรอบนี้',
            'metrics': {'price': snapshot.price, 'pe_ratio': snapshot.pe_ratio, 'div_yield': snapshot.div_yield, 'technicals': snapshot.technicals},
            'history': snapshot.history,
            'news': [source.title for source in snapshot.sources],
            'technicals': snapshot.technicals,
            'advice': advice.dict(),
            'review_status': review_status,
            'review_notes': review_notes,
            'updated_at': snapshot.collected_at.isoformat(),
            'freshness_minutes': snapshot.freshness_minutes,
        }
