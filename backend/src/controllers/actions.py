from src.models.entities import Audit

def audit(db, user, action):
    db.add(Audit(actor=user.email, action=action))
