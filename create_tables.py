from app.models import User, RefreshToken, Prediction, SleepLog, CognitiveTest, CaregiverLink  # noqa
from app.database import engine, Base

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("tables created")
