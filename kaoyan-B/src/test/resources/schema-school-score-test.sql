-- Isolated H2 copy of V16; never run on a business database.
CREATE TABLE school_score_statistic (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, school_id BIGINT NOT NULL, college VARCHAR(255) NOT NULL,
 major_code VARCHAR(6), major_name VARCHAR(500) NOT NULL, stat_year INT NOT NULL, exam_combo CHAR(5) NOT NULL,
 retest_line DECIMAL(5,2), min_score DECIMAL(5,2) NOT NULL, median_score DECIMAL(5,2) NOT NULL,
 avg_score DECIMAL(5,2), max_score DECIMAL(5,2), admitted_count INT NOT NULL, review_status VARCHAR(24) NOT NULL,
 flags_json VARCHAR(2000) NOT NULL, source_json VARCHAR(4000) NOT NULL, row_key CHAR(64) NOT NULL UNIQUE,
 imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
