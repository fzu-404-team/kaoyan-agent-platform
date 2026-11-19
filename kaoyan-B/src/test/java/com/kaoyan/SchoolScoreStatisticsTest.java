package com.kaoyan;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kaoyan.service.SchoolCatalogService;
import com.kaoyan.service.SchoolScoreStatistics;
import com.kaoyan.service.SchoolService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties = {
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.datasource.url=jdbc:h2:mem:school-scores;MODE=MySQL;DB_CLOSE_DELAY=-1;NON_KEYWORDS=USER,YEAR",
    "spring.datasource.username=sa", "spring.datasource.password=", "spring.sql.init.mode=always",
    "spring.sql.init.schema-locations=classpath:schema-test.sql,classpath:schema-school-test.sql,"
        + "classpath:schema-school-metrics-test.sql,classpath:schema-school-score-test.sql",
    "jwt.secret=test-only-jwt-key-at-least-32-characters", "kaoyan.agent.internal-key=test-only-internal-key-12345"
})
@Transactional
class SchoolScoreStatisticsTest {
    @Autowired SchoolCatalogService catalog;
    @Autowired SchoolService schools;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;
    @MockitoBean StringRedisTemplate redis;

    private void score(long id, String college, String code, String major, int year, String median, String flags) {
        jdbc.update("INSERT INTO school_score_statistic(id,school_id,college,major_code,major_name,stat_year,exam_combo,"
                + "retest_line,min_score,median_score,avg_score,max_score,admitted_count,review_status,flags_json,source_json,row_key)"
                + " VALUES(?,21,?,?,?,?,'22408',300,301.5,?,NULL,390,20,'USER_APPROVED',?,'{}',?)",
            id, college, code, major, year, new java.math.BigDecimal(median), flags, String.format("%064d", id));
    }

    private void seed() {
        jdbc.update("INSERT INTO school(id,name,province,level) VALUES(21,'深圳大学','广东',NULL)");
        jdbc.update("INSERT INTO school_detail(id,school_id,major_name,major_code,year) VALUES(31,21,'计算机技术','085404',2027)");
        score(1, "计算机与软件学院", "085404", "计算机技术", 2026, "367", "[\"POSSIBLE_SAME_POOL\"]");
        score(2, "人工智能学院", "085410", "人工智能（26年新增）", 2026, "358", "[]");
        score(3, "计算机与软件学院", "081200", "计算机科学与技术", 2025, "354", "[]");
        score(4, "未知", "081200", "计算机科学与技术", 2026, "350", "[\"UNKNOWN_FLAG\"]");
        jdbc.update("UPDATE school_score_statistic SET review_status='verified' WHERE id IN (1, 3)");
    }

    @Test void detailReturnsOrderedStatisticsAndSkipsUnknownFlags() {
        seed();
        var detail = json.valueToTree(schools.detail(21L));
        var rows = detail.path("scoreStatistics");
        assertEquals(3, rows.size());
        assertEquals(List.of(2026, 2026, 2025), List.of(rows.get(0).path("year").asInt(), rows.get(1).path("year").asInt(), rows.get(2).path("year").asInt()));
        assertEquals("085404", rows.get(0).path("majorCode").asText());
        assertEquals(301.5, rows.get(0).path("minScore").asDouble());
        assertTrue(rows.get(0).path("avgScore").isNull());
        assertEquals("POSSIBLE_SAME_POOL", rows.get(0).path("flags").get(0).asText());
        assertFalse(detail.toString().contains("source_json") || detail.toString().contains("rowKey"));
    }

    @Test void scoreQuestionUsesLookupAndFiltersByYearAndMajorName() {
        seed();
        String query = "深圳大学计算机技术2026年复试线多少";
        var plan = SchoolCatalogService.plan(query);
        assertNotNull(plan);
        assertEquals("SCHOOL_LOOKUP", plan.get("action"));
        assertEquals(Map.of("schoolName", "深圳大学", "year", 2026), withoutNull(plan.get("schoolLookup")));
        assertDoesNotThrow(() -> SchoolCatalogService.validatePlan(plan, query));
        var answer = json.valueToTree(catalog.answer(plan, Map.of(), Map.of()));
        var block = answer.path("schoolCatalog").path("scoreStatistics");
        assertEquals(1, block.path("total").asInt());
        assertEquals("计算机技术", block.path("items").get(0).path("majorName").asText());
        assertTrue(block.path("notice").asText().contains("非学校官网原文"));
        assertTrue(answer.path("answer").asText().startsWith("收录深圳大学往年录取分数统计1条"));
        assertEquals("rules", answer.path("explanationMode").asText());
        assertTrue(answer.path("references").isEmpty());
    }

    @Test void departmentNamesAndCodesDoNotBecomeSecondSchool() {
        seed();
        var plan = SchoolCatalogService.plan("深圳大学人工智能学院的录取分数是多少");
        assertNull(plan.get("clarification"));
        var answer = json.valueToTree(catalog.answer(plan, Map.of(), Map.of()));
        var items = answer.path("schoolCatalog").path("scoreStatistics");
        assertEquals(1, items.path("total").asInt());
        assertEquals("085410", items.path("items").get(0).path("majorCode").asText());
        var coded = json.valueToTree(catalog.answer(SchoolCatalogService.plan("深圳大学081200中位分"), Map.of(), Map.of()));
        assertEquals(1, coded.path("schoolCatalog").path("scoreStatistics").path("total").asInt());
        var none = json.valueToTree(catalog.answer(SchoolCatalogService.plan("深圳大学2024年复试线"), Map.of(), Map.of()));
        assertEquals(0, none.path("schoolCatalog").path("scoreStatistics").path("total").asInt());
        assertTrue(none.path("answer").asText().startsWith("深圳大学暂无符合本次条件的往年录取分数统计"));
    }

    @Test void scoreTriggerKeepsOtherPipelines() {
        assertNull(SchoolCatalogService.plan("推荐复试线低于320的院校"));
        assertNull(SchoolCatalogService.plan("帮我择校，深圳大学复试线高吗"));
        assertNull(SchoolCatalogService.plan("如何查询深圳大学复试线"));
        assertNull(SchoolCatalogService.plan("深圳大学复试线官网链接"));
        assertNull(SchoolCatalogService.plan("复试线一般多少分"));
        assertNotNull(SchoolCatalogService.plan("北京大学和清华大学复试线").get("clarification"));
        assertEquals(AdmissionSplit(), SchoolCatalogService.plan("查询四川大学招生信息并解释TCP").get("clarification"));
    }

    @Test void missingV16KeepsOldResponseAndConnectionFailurePropagates() {
        var missing = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:no-school-v16", "sa", ""));
        assertNull(new SchoolScoreStatistics(missing, new ObjectMapper()).forSchool(1L));
        try (var connection = missing.getDataSource().getConnection(); var statement = connection.createStatement()) {
            statement.execute("CREATE TABLE school (id BIGINT, name VARCHAR(100), province VARCHAR(50))");
            assertNull(new SchoolScoreStatistics(missing, new ObjectMapper()).forComparison("22408", null, null, null));
        } catch (java.sql.SQLException exception) {
            fail(exception);
        }
        var broken = mock(JdbcTemplate.class);
        doThrow(new DataAccessResourceFailureException("synthetic unavailable database")).when(broken)
                .query(anyString(), any(RowCallbackHandler.class), any(Object[].class));
        assertThrows(DataAccessResourceFailureException.class,
                () -> new SchoolScoreStatistics(broken, new ObjectMapper()).forSchool(1L));
    }

    @Test void majorCoreStripsQualifiers() {
        assertEquals("计算机技术", SchoolCatalogService.majorCore("计算机技术（非全）"));
        assertEquals("软件工程", SchoolCatalogService.majorCore("软件工程 (专硕)"));
    }

    private static String AdmissionSplit() {
        return com.kaoyan.service.AdmissionLinksValidator.SPLIT;
    }

    private static Map<String, Object> withoutNull(Object value) {
        @SuppressWarnings("unchecked")
        var map = new java.util.LinkedHashMap<>((Map<String, Object>) value);
        map.values().removeIf(java.util.Objects::isNull);
        return map;
    }
}
