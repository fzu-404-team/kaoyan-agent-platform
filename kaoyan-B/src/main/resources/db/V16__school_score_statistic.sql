-- Apply ONCE after backup, restore verification and isolated rehearsal.
-- No startup auto-migration. User-provided, user-approved admission score
-- statistics; never official data and never written back to school_detail.
CREATE TABLE school_score_statistic (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
 school_id BIGINT UNSIGNED NOT NULL,
 college VARCHAR(255) NOT NULL,
 major_code VARCHAR(6) NULL,
 major_name VARCHAR(500) NOT NULL,
 stat_year INT NOT NULL,
 exam_combo CHAR(5) NOT NULL,
 retest_line DECIMAL(5,2) NULL,
 min_score DECIMAL(5,2) NOT NULL,
 median_score DECIMAL(5,2) NOT NULL,
 avg_score DECIMAL(5,2) NULL,
 max_score DECIMAL(5,2) NULL,
 admitted_count INT NOT NULL,
 review_status VARCHAR(24) NOT NULL,
 flags_json JSON NOT NULL,
 source_json JSON NOT NULL,
 row_key CHAR(64) NOT NULL,
 imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (id),
 UNIQUE KEY uk_score_row (row_key),
 KEY idx_score_school_year (school_id, stat_year),
 KEY idx_score_major_code (major_code),
 CONSTRAINT fk_score_school FOREIGN KEY (school_id) REFERENCES school(id) ON DELETE CASCADE,
 CONSTRAINT ck_score_status CHECK (review_status = 'USER_APPROVED'),
 CONSTRAINT ck_score_year CHECK (stat_year BETWEEN 2000 AND 2100),
 CONSTRAINT ck_score_count CHECK (admitted_count >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户提供并经用户审核批准的院校录取分数统计';
