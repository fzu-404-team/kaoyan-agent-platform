-- Apply once after V16. The original source and flags are retained.
ALTER TABLE school_score_statistic
    DROP CHECK ck_score_status,
    ADD CONSTRAINT ck_score_review_status CHECK (review_status IN ('USER_APPROVED', 'verified'));
