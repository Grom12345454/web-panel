from .base import db
class StudentQuotaStat(db.Model):
    __tablename__ = "student_quota_stats"
    __bind_key__ = "stats"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=False)
    direction_id = db.Column(db.Integer, nullable=False)
    total_quotas = db.Column(db.Integer, default=0)
    attended_count = db.Column(db.Integer, default=0)
    @property
    def student(self):
        from .core import Student
        return Student.query.get(self.student_id)
    @property
    def direction(self):
        from .core import Direction
        return Direction.query.get(self.direction_id)
