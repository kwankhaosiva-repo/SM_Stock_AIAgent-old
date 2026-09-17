from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session
from datetime import datetime
from config import Config

# Setup SQLAlchemy
engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, echo=False)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    
    # Preferences
    investment_goal = Column(String, default="Medium") # Short, Medium, Long
    core_strategy = Column(String, default="AI-Auto") # Value, Growth, Dividend, Technical, AI-Auto
    risk_appetite = Column(String, default="Medium") # Low, Medium, High
    report_format = Column(String, default="Short") # Short, Long
    
    # Relationships
    watchlist = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    schedule = relationship("Schedule", uselist=False, back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.line_user_id}>"

class Watchlist(Base):
    __tablename__ = 'watchlist'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    symbol = Column(String, nullable=False) # e.g., PTT.BK
    
    # Specific Settings (Override Global if not None)
    strategy = Column(String, nullable=True) # DCA, AI-Auto, Value, Growth, Dividend, Technical
    goal = Column(String, nullable=True) # Short, Medium, Long
    risk = Column(String, nullable=True) # Low, Medium, High
    report_format = Column(String, nullable=True) # Summary, Full
    
    target_price = Column(Float, nullable=True)
    alert_on_drop_percent = Column(Float, nullable=True)
    
    user = relationship("User", back_populates="watchlist")
    
    def __repr__(self):
        return f"<Stock {self.symbol} (Strat: {self.strategy or 'Global'})>"

class Schedule(Base):
    __tablename__ = 'schedules'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    frequency_days = Column(Integer, default=1) # 1 = Every day
    alert_time = Column(String, default="06:00") # HH:MM (Local Time)
    last_run = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    user = relationship("User", back_populates="schedule")


class MarketSnapshot(Base):
    """Reusable, source-labelled market data collected for one symbol."""
    __tablename__ = 'market_snapshots'

    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    provider = Column(String, nullable=False, default='legacy')
    data_json = Column(Text, nullable=False)
    collected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)


class SourceDocument(Base):
    __tablename__ = 'source_documents'

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey('market_snapshots.id'), nullable=False, index=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=True)
    published_at = Column(String, nullable=True)
    source_type = Column(String, nullable=False, default='news')
    content = Column(Text, nullable=True)


class AnalysisRun(Base):
    __tablename__ = 'analysis_runs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    snapshot_id = Column(Integer, ForeignKey('market_snapshots.id'), nullable=True)
    status = Column(String, nullable=False, default='queued', index=True)
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class AgentOutput(Base):
    __tablename__ = 'agent_outputs'

    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey('analysis_runs.id'), nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default='completed')
    output_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReportDelivery(Base):
    __tablename__ = 'report_deliveries'
    __table_args__ = (UniqueConstraint('idempotency_key', name='uq_report_delivery_idempotency_key'),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    analysis_run_id = Column(Integer, ForeignKey('analysis_runs.id'), nullable=True)
    idempotency_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default='queued', index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)

def init_db():
    """Initializes the database tables."""
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully.")

def get_db():
    """Utility to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
