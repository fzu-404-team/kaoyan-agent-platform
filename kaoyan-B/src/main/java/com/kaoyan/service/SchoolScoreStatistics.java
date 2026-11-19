package com.kaoyan.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kaoyan.dto.response.ScoreStatisticVO;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Reads V16 score statistics; an older database without V16 keeps its original responses. */
@Service
@RequiredArgsConstructor
public class SchoolScoreStatistics {
    public static final String NOTICE = "用户提供数据，经用户审核批准，非学校官网原文；"
            + "公布录取数可能为多个专业共用的录取池，不能相加；往年数据不代表今后分数线。";
    /** Known quality flags and their display labels; any other flag makes a row unusable. */
    public static final Map<String, String> FLAG_LABELS = Map.of(
            "POSSIBLE_SAME_POOL", "可能与其他专业同一录取池",
            "SAME_SCORES_DIFFERENT_CODES", "与其他专业代码分数完全相同",
            "MAX_BELOW_MEDIAN", "最高分低于中位分",
            "MIN_ABOVE_MEDIAN", "最低分高于中位分",
            "AVG_OUT_OF_RANGE", "平均分超出最低至最高范围",
            "LINE_ABOVE_MIN", "复试线高于录取最低分");
    public static final Set<String> FLAGS = FLAG_LABELS.keySet();
    private static final TypeReference<List<String>> STRINGS = new TypeReference<>() {};
    private static final String COLUMNS = "t.id, t.stat_year, t.college, t.major_code, t.major_name, t.exam_combo, "
            + "t.retest_line, t.min_score, t.median_score, t.avg_score, t.max_score, t.admitted_count, t.flags_json";

    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    /**
     * Rows for one school, newest year first; null when the V16 table does not exist.
     * Rows whose stored flags are not a known string list are omitted instead of shown unmarked.
     */
    public List<ScoreStatisticVO> forSchool(long schoolId) {
        return query("SELECT " + COLUMNS + " FROM school_score_statistic t "
                        + "WHERE t.school_id=? AND t.review_status IN ('USER_APPROVED', 'verified') "
                        + "ORDER BY t.stat_year DESC, CASE WHEN t.major_code IS NULL THEN 1 ELSE 0 END, t.major_code, t.id",
                (result, row) -> read(result), schoolId);
    }

    public record ComparisonRow(long schoolId, String schoolName, String province, ScoreStatisticVO score) {}

    /** Approved observations matching the requested exam and optional scope. Null means V16 is absent. */
    public List<ComparisonRow> forComparison(String examCombo, Long schoolId, String majorCode, String province) {
        var sql = new StringBuilder("SELECT ").append(COLUMNS).append("""
                , s.id AS school_id, s.name AS school_name, s.province FROM school_score_statistic t
                JOIN school s ON s.id=t.school_id WHERE t.review_status IN ('USER_APPROVED', 'verified') AND t.exam_combo=?
                """);
        var args = new ArrayList<Object>();
        args.add(examCombo);
        if (schoolId != null) {
            sql.append(" AND t.school_id=?");
            args.add(schoolId);
        }
        if (majorCode != null) {
            sql.append(" AND t.major_code=?");
            args.add(majorCode);
        }
        if (province != null) {
            sql.append(" AND s.province=?");
            args.add(province);
        }
        sql.append(" ORDER BY s.name, s.id, t.stat_year DESC, t.college, t.major_code, t.major_name, t.id");
        return query(sql.toString(), (result, row) -> {
            var score = read(result);
            return score == null ? null : new ComparisonRow(result.getLong("school_id"), result.getString("school_name"),
                    result.getString("province"), score);
        }, args.toArray());
    }

    private <T> List<T> query(String sql, RowMapper<T> reader, Object... args) {
        List<T> rows = new ArrayList<>();
        try {
            jdbc.query(sql, (RowCallbackHandler) result -> {
                T row = reader.mapRow(result, rows.size());
                if (row != null) rows.add(row);
            }, args);
            return List.copyOf(rows);
        } catch (BadSqlGrammarException exception) {
            SQLException cause = exception.getSQLException();
            if (cause != null && ("42S02".equals(cause.getSQLState()) || cause.getErrorCode() == 1146
                    || cause.getErrorCode() == 42102 || cause.getErrorCode() == 42104)) {
                return null; // V16 is optional; other SQL failures must propagate.
            }
            throw exception;
        }
    }

    private ScoreStatisticVO read(ResultSet result) throws SQLException {
        List<String> flags;
        try {
            flags = mapper.readValue(result.getString("flags_json"), STRINGS);
        } catch (JsonProcessingException | IllegalArgumentException exception) {
            return null;
        }
        if (flags == null || flags.stream().anyMatch(flag -> flag == null || !FLAGS.contains(flag))) return null;
        return new ScoreStatisticVO(result.getLong("id"), result.getInt("stat_year"), result.getString("college"),
                result.getString("major_code"), result.getString("major_name"), result.getString("exam_combo"),
                number(result, "retest_line"), number(result, "min_score"), number(result, "median_score"),
                number(result, "avg_score"), number(result, "max_score"), result.getInt("admitted_count"),
                List.copyOf(flags));
    }

    private static Double number(ResultSet result, String column) throws SQLException {
        var value = result.getBigDecimal(column);
        return value == null ? null : value.doubleValue();
    }
}
