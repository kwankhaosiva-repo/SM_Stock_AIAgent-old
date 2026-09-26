from __future__ import annotations

import json
import operator
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import (
    FundamentalTechnicalAgent,
    NewsContextAgent,
    PersonalizedAdviceAgent,
    RiskEvidenceReviewer,
)
from data.market_snapshot_service import MarketSnapshotService
import store
from llm_service import LLMService
from models.analysis_models import AdviceOutput, AgentFinding, MarketSnapshotData, ReviewResult

# Bound the reviewer <-> advice reflection loop to keep cost and latency predictable.
MAX_REVISIONS = 1


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ReportState(TypedDict, total=False):
    """Shared state flowing through the LangGraph report workflow."""

    symbol: str
    profile: Dict[str, str]
    snapshot: MarketSnapshotData
    news: AgentFinding
    analysis: AgentFinding
    advice: AdviceOutput
    review: ReviewResult
    revision_count: int
    review_notes: Annotated[List[str], operator.add]
    final_advice: AdviceOutput
    result: Dict


class ReportWorkflow:
    """LangGraph orchestration around narrow, auditable reasoning roles.

    Graph topology:

        START -> collect_snapshot -> [news_agent, fundamental_technical] (parallel)
              -> synthesize_advice -> review
              -> (approve|reject)  -> finalize -> END
              -> (revise, budget left) -> revise_advice -> review  (reflection loop)
    """

    def __init__(self, snapshot_service=None, llm=None):
        self.snapshot_service = snapshot_service or MarketSnapshotService()
        shared_llm = llm or LLMService()
        self.news_agent = NewsContextAgent(shared_llm)
        self.analysis_agent = FundamentalTechnicalAgent(shared_llm)
        self.advice_agent = PersonalizedAdviceAgent(shared_llm)
        self.reviewer = RiskEvidenceReviewer(shared_llm)

    # ------------------------------------------------------------------ graph

    def _build_graph(self, run_id: str):
        """Build the StateGraph with the run id captured in node closures.

        LangGraph runs parallel nodes on worker threads; audit writes go
        through the store layer which is safe for concurrent use.
        """

        def save_output(name: str, payload: Dict) -> None:
            store.add_agent_output(
                run_id, name,
                json.dumps(payload, ensure_ascii=False, default=str),
            )

        def collect_snapshot(state: ReportState) -> Dict:
            snapshot, snapshot_id = self.snapshot_service.get_or_collect(state['symbol'])
            store.update_analysis_run(run_id, snapshot_id=snapshot_id)
            return {'snapshot': snapshot}

        def run_news(state: ReportState) -> Dict:
            news = self.news_agent.run(state['snapshot'])
            save_output(news.agent_name, news.to_dict())
            return {'news': news}

        def run_analysis(state: ReportState) -> Dict:
            analysis = self.analysis_agent.run(state['snapshot'])
            save_output(analysis.agent_name, analysis.to_dict())
            return {'analysis': analysis}

        def synthesize_advice(state: ReportState) -> Dict:
            advice = self.advice_agent.run(
                state['snapshot'], state['news'], state['analysis'], state['profile']
            )
            save_output(self.advice_agent.name, advice.to_dict())
            return {'advice': advice}

        def review_advice(state: ReportState) -> Dict:
            review = self.reviewer.run(state['snapshot'], state['advice'])
            save_output(self.reviewer.name, review.to_dict())
            return {'review': review, 'review_notes': list(review.notes or [])}

        def revise_advice(state: ReportState) -> Dict:
            advice = self.advice_agent.run(
                state['snapshot'],
                state['news'],
                state['analysis'],
                state['profile'],
                review_notes=state.get('review_notes') or [],
            )
            save_output(self.advice_agent.name, advice.to_dict())
            return {
                'advice': advice,
                'revision_count': state.get('revision_count', 0) + 1,
            }

        def finalize(state: ReportState) -> Dict:
            review = state['review']
            advice = state['advice']
            final_advice = review.corrected_advice or advice
            if review.status.lower() == 'revise' and review.notes:
                final_advice.risks = list(dict.fromkeys(final_advice.risks + review.notes))[:3]
            return {'final_advice': final_advice}

        def route_after_review(state: ReportState) -> str:
            status = state['review'].status.lower()
            if status == 'reject':
                return 'finalize'
            if status == 'revise' and state.get('revision_count', 0) < MAX_REVISIONS:
                return 'revise_advice'
            return 'finalize'

        graph = StateGraph(ReportState)
        graph.add_node('collect_snapshot', collect_snapshot)
        graph.add_node('news_agent', run_news)
        graph.add_node('fundamental_technical', run_analysis)
        graph.add_node('synthesize_advice', synthesize_advice)
        graph.add_node('review', review_advice)
        graph.add_node('revise_advice', revise_advice)
        graph.add_node('finalize', finalize)

        graph.add_edge(START, 'collect_snapshot')
        # Fan-out: news and fundamental/technical agents run concurrently.
        graph.add_edge('collect_snapshot', 'news_agent')
        graph.add_edge('collect_snapshot', 'fundamental_technical')
        # Fan-in: synthesis waits for both branches.
        graph.add_edge('news_agent', 'synthesize_advice')
        graph.add_edge('fundamental_technical', 'synthesize_advice')
        graph.add_edge('synthesize_advice', 'review')
        graph.add_conditional_edges('review', route_after_review)
        graph.add_edge('revise_advice', 'review')
        graph.add_edge('finalize', END)

        return graph.compile()

    # -------------------------------------------------------------------- run

    def run(self, symbol: str, profile: Dict[str, str], user_key: Optional[str] = None) -> Dict:
        run_id = store.create_analysis_run(user_key, symbol.upper())

        try:
            graph = self._build_graph(run_id)
            final_state: ReportState = graph.invoke(
                {'symbol': symbol.upper(), 'profile': profile, 'revision_count': 0}
            )

            review = final_state['review']
            final_advice = final_state['final_advice']
            result = self._to_result(
                final_state['snapshot'], final_advice, review.status, review.notes
            )

            store.update_analysis_run(
                run_id,
                status='completed' if review.status.lower() != 'reject' else 'review_rejected',
                result=json.dumps(result, ensure_ascii=False, default=str),
                completed_at=_utcnow_naive(),
            )
            return result
        except Exception as exc:
            store.update_analysis_run(
                run_id,
                status='failed',
                error_message=str(exc)[:1000],
                completed_at=_utcnow_naive(),
            )
            raise

    @staticmethod
    def _categorized_reasons_from_list(raw_reasons) -> Dict[str, List[str]]:
        """Tag a flat reason list into news / financials / stats buckets."""
        raw = list(raw_reasons or [])
        if not raw:
            return {'news': [], 'financials': [], 'stats': []}
        news_kw = ('ข่าว', 'ประกาศ', 'คดี', 'เข้าซื้อ', 'ควบ', 'น้ำมัน', 'เฟด', 'fed',
                   'ดอกเบี้ย', 'ภาษี', 'guidance', 'สั่งซื้อ', 'ส่งออก', 'มหภาค')
        fin_kw = ('งบ', 'กำไร', 'รายได้', 'หนี้', 'ทุน', 'ปันผล', 'dividend', 'roa',
                  'roe', 'หนี้สิน', 'กระแสเงินสด', 'de', 'asset', 'equity')
        news, fin, stats = [], [], []
        for reason in raw:
            text = str(reason).lower()
            if any(k in text for k in news_kw):
                news.append(str(reason))
            elif any(k in text for k in fin_kw):
                fin.append(str(reason))
            else:
                stats.append(str(reason))
        return {'news': news[:2], 'financials': fin[:2], 'stats': stats[:2]}

    @classmethod
    def _categorized_reasons(cls, snapshot: MarketSnapshotData, advice: AdviceOutput) -> Dict[str, List[str]]:
        """Split evidence into news / financials / accounting-stats buckets."""
        return cls._categorized_reasons_from_list(advice.reasons or [])

    @staticmethod
    def _to_result(snapshot: MarketSnapshotData, advice: AdviceOutput, review_status: str, review_notes) -> Dict:
        from analysis.news_cleaning import clean_headline

        outlook = advice.outlook if advice.outlook in ('Positive', 'Neutral', 'Cautious') else 'Neutral'
        categorized = ReportWorkflow._categorized_reasons(snapshot, advice)
        clean_titles: List[str] = []
        seen_titles = set()
        for source in snapshot.sources:
            title = clean_headline(source.title)
            if title and title.lower() not in seen_titles:
                seen_titles.add(title.lower())
                clean_titles.append(title)
        return {
            'symbol': snapshot.symbol,
            'signal': outlook,
            'reason': advice.summary,
            'news_summary': ' | '.join(advice.reasons[:2]) or 'ไม่มีข้อมูลข่าวที่ตรวจสอบได้ในรอบนี้',
            'metrics': {
                'price': snapshot.price,
                'pe_ratio': snapshot.pe_ratio,
                'div_yield': snapshot.div_yield,
                'technicals': snapshot.technicals,
            },
            'history': snapshot.history,
            'news': clean_titles,
            'reason_categories': categorized,
            'technicals': snapshot.technicals,
            'advice': advice.to_dict(),
            'review_status': review_status,
            'review_notes': review_notes,
            'updated_at': str(snapshot.collected_at)[:19].replace('T', ' '),
            'freshness_minutes': snapshot.freshness_minutes,
        }
